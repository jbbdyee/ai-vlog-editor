"""n8n render terminal events: no real render, LLM, VLM, n8n or Docker.

SQLite + ManualExecutor for the registry, httpx.MockTransport for delivery, and a local fake receiver
(127.0.0.1, random port) that follows the same contract as deploy/n8n/record-render-event.js.
"""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Lock, Thread
import time
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import create_render_event_dispatcher
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectRenderRun, ProjectSceneEditPlan, ProjectSceneEditPlanItem,
    SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus,
    SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.render_event_replay import replay
from backend.app.services.persistent_render_execution import PersistentProjectRenderRunRegistry, utcnow
from backend.app.services.project_rendering import ProjectRenderError, ProjectRenderResult
from backend.app.services.render_events import (
    EVENT_ID_PATTERN, RenderEventConfigError, RenderEventDispatcher, RenderEventSettings,
    collect_terminal_events, event_from_row, terminal_event,
)

TOKEN = "t" * 24 + "-test-only-0123456789"  # synthetic, never a real secret
WEBHOOK = "http://127.0.0.1:5678/webhook/cutory-render-events"
REPO = Path(__file__).resolve().parents[2]


def settings(url=WEBHOOK, token=TOKEN):
    return RenderEventSettings(url=url, token=token)


def sample_event(status="COMPLETED", render_id=None):
    return terminal_event(project_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                          render_id=render_id or UUID("01234567-89ab-cdef-0123-456789abcdef"),
                          status=status, safe_error_code=None if status == "COMPLETED" else "OUTPUT_INVALID",
                          finished_at=datetime(2026, 11, 6, 1, 2, 3, 123456, tzinfo=timezone.utc),
                          duration_seconds=12.5, file_size_bytes=2048)


class ManualExecutor:
    def __init__(self): self.operations = []
    def submit(self, operation): self.operations.append(operation)
    def run_next(self): self.operations.pop(0)()


class SettingsTests(TestCase):
    def test_disabled_without_configuration(self):
        self.assertIsNone(RenderEventSettings.from_environment({}))
        self.assertIsNone(RenderEventSettings.from_environment({"CUTORY_N8N_WEBHOOK_URL": " ", "CUTORY_N8N_WEBHOOK_TOKEN": ""}))

    def test_rejects_partial_and_unsafe_configuration_with_codes_only(self):
        cases = [
            ("RENDER_EVENT_URL_MISSING", "", TOKEN),
            ("RENDER_EVENT_TOKEN_MISSING", WEBHOOK, ""),
            ("RENDER_EVENT_URL_NOT_LOOPBACK", "http://example.com/webhook/x", TOKEN),
            ("RENDER_EVENT_URL_INVALID", "ftp://127.0.0.1/webhook/x", TOKEN),
            ("RENDER_EVENT_URL_INVALID", "http://127.0.0.1:5678/", TOKEN),
            ("RENDER_EVENT_URL_HAS_CREDENTIALS_OR_QUERY", WEBHOOK + "?token=abc", TOKEN),
            ("RENDER_EVENT_TOKEN_TOO_SHORT", WEBHOOK, "short"),
            ("RENDER_EVENT_TOKEN_INVALID_CHARACTERS", WEBHOOK, TOKEN + " x\n"),
        ]
        for code, url, token in cases:
            environment = {"CUTORY_N8N_WEBHOOK_URL": url, "CUTORY_N8N_WEBHOOK_TOKEN": token}
            with self.subTest(code=code, url=url), self.assertRaises(RenderEventConfigError) as raised:
                RenderEventSettings.from_environment(environment)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn(TOKEN, str(raised.exception))
        for host in ("192.168.0.10", "100.107.77.10", "0.0.0.0", "user:pw@127.0.0.1"):
            with self.subTest(host), self.assertRaises(RenderEventConfigError):
                RenderEventSettings.from_environment({"CUTORY_N8N_WEBHOOK_URL": f"http://{host}:5678/webhook/x",
                                                      "CUTORY_N8N_WEBHOOK_TOKEN": TOKEN})

    def test_accepts_loopback_and_hides_values(self):
        for url in (WEBHOOK, "http://localhost:5678/webhook/x", "http://[::1]:5678/webhook/x", "http://127.0.0.2/w"):
            loaded = RenderEventSettings.from_environment({"CUTORY_N8N_WEBHOOK_URL": url, "CUTORY_N8N_WEBHOOK_TOKEN": TOKEN})
            self.assertEqual(loaded.url, url)
            self.assertNotIn(TOKEN, repr(loaded))
            self.assertNotIn("webhook", repr(loaded))


class EventTests(TestCase):
    def test_stable_ids_and_deterministic_body(self):
        event = sample_event()
        self.assertEqual(event.event_id, "render-0123456789abcdef0123456789abcdef-completed")
        self.assertRegex(event.event_id, EVENT_ID_PATTERN)
        self.assertEqual(event.body(), sample_event().body())
        self.assertEqual(json.loads(event.body())["finished_at"], "2026-11-06T01:02:03.123456Z")
        naive = terminal_event(project_id=event.project_id, render_id=event.render_id, status="COMPLETED",
                               safe_error_code=None, finished_at=datetime(2026, 11, 6, 1, 2, 3, 123456),
                               duration_seconds=12.5, file_size_bytes=2048)
        self.assertEqual(naive.body(), event.body())

    def test_failure_events_carry_no_output_and_completed_no_error(self):
        failed = sample_event("RECONCILIATION_REQUIRED").payload()
        self.assertEqual((failed["event_type"], failed["duration_seconds"], failed["file_size_bytes"]),
                         ("render.reconciliation_required", None, None))
        self.assertIsNone(terminal_event(project_id=uuid4(), render_id=uuid4(), status="COMPLETED",
                                         safe_error_code="X", finished_at=utcnow()).safe_error_code)
        with self.assertRaises(ValueError):
            terminal_event(project_id=uuid4(), render_id=uuid4(), status="RUNNING", safe_error_code=None,
                           finished_at=utcnow())
        payload = sample_event().payload()
        self.assertFalse({"path", "base_relpath", "name"} & payload.keys())


class Recorder:
    """MockTransport handler that replays a scripted list of responses or exceptions."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        status, body = step if isinstance(step, tuple) else (step, {})
        return httpx.Response(status, json=body)


class DispatcherTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.log_path = Path(temporary.name) / "deliveries.jsonl"

    def dispatcher(self, recorder, backoff=(0, 0, 0), start=False, **kwargs):
        dispatcher = RenderEventDispatcher(settings(), transport=httpx.MockTransport(recorder), backoff_seconds=backoff,
                                           log_path=self.log_path, start=start, **kwargs)
        self.addCleanup(dispatcher.close, 1)
        return dispatcher

    def records(self):
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def assert_no_secret_in_trace(self, captured=""):
        trace = self.log_path.read_text(encoding="utf-8") + captured
        for secret in (TOKEN, "Bearer", "/webhook/", "127.0.0.1"):
            self.assertNotIn(secret, trace)

    def test_request_shape(self):
        recorder = Recorder((200, {"result": "recorded"}))
        self.assertEqual(self.dispatcher(recorder).deliver(sample_event()), "delivered")
        request = recorder.requests[0]
        self.assertEqual(str(request.url), WEBHOOK)
        self.assertEqual(request.headers["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(request.headers["x-cutory-event-id"], sample_event().event_id)
        self.assertEqual(request.headers["x-cutory-attempt"], "1")
        self.assertEqual(request.content, sample_event().body())
        record = self.records()[0]
        self.assertEqual((record["outcome"], record["receiver_result"], record["attempt"], record["max_attempts"]),
                         ("delivered", "recorded", 1, 4))
        self.assert_no_secret_in_trace()

    def test_retries_transient_failures_with_same_ids(self):
        recorder = Recorder(httpx.ConnectError("refused"), (503, {}), (429, {}), (200, {"result": "duplicate"}))
        with self.assertLogs("cutory.render_events", "INFO") as logs:
            self.assertEqual(self.dispatcher(recorder).deliver(sample_event()), "delivered")
        self.assertEqual([r.headers["x-cutory-attempt"] for r in recorder.requests], ["1", "2", "3", "4"])
        self.assertEqual(len({r.headers["x-cutory-delivery-id"] for r in recorder.requests}), 1)
        self.assertEqual({r.content for r in recorder.requests}, {sample_event().body()})
        outcomes = [(r["outcome"], r.get("http_status"), r.get("error_type")) for r in self.records()]
        self.assertEqual(outcomes, [("retrying", None, "ConnectError"), ("retrying", 503, None),
                                    ("retrying", 429, None), ("delivered", 200, None)])
        self.assert_no_secret_in_trace("\n".join(logs.output))

    def test_gives_up_after_bounded_attempts(self):
        recorder = Recorder(httpx.ConnectTimeout("slow"))
        self.assertEqual(self.dispatcher(recorder).deliver(sample_event()), "failed")
        self.assertEqual(len(recorder.requests), 4)
        self.assertEqual(self.records()[-1]["outcome"], "failed")

    def test_client_errors_and_redirects_are_not_retried(self):
        for status in (400, 401, 403, 404, 409, 302):
            with self.subTest(status):
                recorder = Recorder((status, {"result": "conflict"}))
                self.assertEqual(self.dispatcher(recorder).deliver(sample_event()), "rejected")
                self.assertEqual(len(recorder.requests), 1)
        self.assertNotIn("receiver_result", self.records()[-1])

    def test_submit_is_async_and_never_raises(self):
        recorder = Recorder(RuntimeError("unexpected"))
        dispatcher = self.dispatcher(recorder, start=True)
        dispatcher.submit(sample_event())
        dispatcher.close(5)
        self.assertEqual(self.records()[-1]["outcome"], "failed")
        self.assertEqual(self.records()[-1]["error_type"], "RuntimeError")
        dispatcher.submit(sample_event())  # after close: recorded, not raised
        self.assertEqual(self.records()[-1]["outcome"], "dropped_shutdown")

    def test_queue_full_is_recorded(self):
        dispatcher = self.dispatcher(Recorder(200), max_queue=1)
        dispatcher.submit(sample_event())
        dispatcher.submit(sample_event("FAILED"))
        self.assertEqual(self.records()[-1]["outcome"], "dropped_queue_full")

    def test_close_aborts_long_backoff(self):
        dispatcher = self.dispatcher(Recorder(503), backoff=(30, 30, 30), start=True)
        dispatcher.submit(sample_event())
        deadline = time.monotonic() + 5
        while not self.log_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        dispatcher.close(timeout=0.2)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.records()[-1]["outcome"], "abandoned_shutdown")

    def test_trace_write_failure_does_not_break_delivery(self):
        blocked = self.log_path.parent / "file"
        blocked.write_text("x")
        dispatcher = RenderEventDispatcher(settings(), transport=httpx.MockTransport(Recorder(200)),
                                           backoff_seconds=(0, 0, 0), log_path=blocked / "deliveries.jsonl", start=False)
        self.addCleanup(dispatcher.close, 1)
        self.assertEqual(dispatcher.deliver(sample_event()), "delivered")


class RegistryEventTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        engine = create_engine(f"sqlite+pysqlite:///{self.root / 'render.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.output = self.root / "outputs"
        self.executor = ManualExecutor()
        self.events = []
        self.seen_status = []

        def on_terminal(event):
            with self.factory() as session:  # the row must already be committed when the event exists
                self.seen_status.append(session.get(ProjectRenderRun, event.render_id).status)
            self.events.append(event)

        self.registry = PersistentProjectRenderRunRegistry(self.executor, self.factory, self.output, on_terminal=on_terminal)
        with self.factory.begin() as session:
            project = Project(name="event QA", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project); session.flush()
            self.project_id = project.id
            source = SourceVideo(project_id=project.id, original_filename="fake.mp4",
                                 storage_reference="private/fake.mp4", duration_seconds=5)
            session.add(source); session.flush()
            work = SceneAnalysisWorkItem(
                project_id=project.id, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint="source", producer="test",
                producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint="result",
            )
            session.add(work); session.flush()
            candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id,
                                       start_seconds=1, end_seconds=2, discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                                       input_fingerprint="source")
            session.add(candidate); session.flush()
            session.add_all([
                SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                              evidence_type="AUDIO_ACTIVITY", payload={}, producer="test", producer_version="1",
                              source_reference="fake"),
            ])
            plan = ProjectSceneEditPlan(project_id=project.id)
            plan.items = [ProjectSceneEditPlanItem(position=0, candidate_id=candidate.id)]
            session.add(plan)
            self.candidate_id = candidate.id

    def render_dir(self, render_id):
        directory = self.output / "projects" / self.project_id.hex / "renders" / render_id.hex
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def fake_success(self, render_id, selection):
        base = self.render_dir(render_id) / "final.mp4"
        base.write_bytes(b"valid synthetic MP4" * 10)
        return ProjectRenderResult(self.project_id, render_id, base, (self.candidate_id,), 3.25,
                                   "h264", "aac", base.stat().st_size)

    def run_render(self, operation):
        before = len(self.events)
        render_id = self.registry.start(self.project_id, operation)
        self.assertIsNotNone(render_id)
        self.assertEqual(len(self.events), before)  # QUEUED is not terminal
        self.executor.run_next()
        return render_id

    def row(self, render_id):
        with self.factory() as session:
            return session.get(ProjectRenderRun, render_id)

    def assert_replay_identical(self):
        replayed = collect_terminal_events(self.factory, since=datetime(2000, 1, 1, tzinfo=timezone.utc))
        self.assertEqual([e.body() for e in replayed], [e.body() for e in self.events])

    def test_completed_event_after_commit(self):
        render_id = self.run_render(self.fake_success)
        self.assertEqual([(e.render_id, e.status) for e in self.events], [(render_id, "COMPLETED")])
        self.assertEqual(self.seen_status, ["COMPLETED"])
        payload = self.events[0].payload()
        self.assertEqual((payload["duration_seconds"], payload["file_size_bytes"], payload["safe_error_code"]),
                         (3.25, len(b"valid synthetic MP4" * 10), None))
        self.assertEqual(event_from_row(self.row(render_id)).body(), self.events[0].body())
        self.assert_replay_identical()

    def test_failed_and_reconciliation_events(self):
        def fail(render_id, selection):
            raise ProjectRenderError("SEGMENT_RENDER_FAILED", "synthetic")

        def fail_after_output(render_id, selection):
            (self.render_dir(render_id) / "final.mp4").write_bytes(b"partial")
            raise ProjectRenderError("SEGMENT_RENDER_FAILED", "synthetic")

        first = self.run_render(fail)
        second = self.run_render(fail_after_output)
        self.assertEqual([(e.render_id, e.status, e.safe_error_code) for e in self.events],
                         [(first, "FAILED", "SEGMENT_RENDER_FAILED"),
                          (second, "RECONCILIATION_REQUIRED", "RENDER_RECOVERY_REQUIRED")])
        self.assertEqual(self.seen_status, ["FAILED", "RECONCILIATION_REQUIRED"])
        self.assert_replay_identical()

    def test_callback_error_does_not_change_the_result(self):
        def broken(event):
            raise RuntimeError("n8n hook exploded")

        self.registry = PersistentProjectRenderRunRegistry(self.executor, self.factory, self.output, on_terminal=broken)
        with self.assertLogs("cutory.render_events", "WARNING") as logs:
            render_id = self.run_render(self.fake_success)
        self.assertEqual(self.row(render_id).status, "COMPLETED")
        self.assertIn("render_event_callback_failed", logs.output[0])
        self.assertIsNotNone(self.registry.start(self.project_id, self.fake_success))  # next render still accepted

    def test_lost_ownership_emits_nothing(self):
        def steal(render_id, selection):
            result = self.fake_success(render_id, selection)
            with self.factory.begin() as session:
                session.get(ProjectRenderRun, render_id).owner_token = uuid4()
            return result

        render_id = self.run_render(steal)
        self.assertEqual(self.row(render_id).status, "RUNNING")  # not written by this worker
        self.assertEqual(self.events, [])

    def test_completion_commit_failure_emits_no_completed_event(self):
        with self.factory().bind.begin() as connection:
            connection.execute(text("CREATE TRIGGER deny_completed BEFORE UPDATE OF status ON project_render_runs "
                                    "WHEN NEW.status = 'COMPLETED' BEGIN SELECT RAISE(FAIL, 'blocked'); END"))
        render_id = self.run_render(self.fake_success)
        self.assertEqual(self.row(render_id).status, "RECONCILIATION_REQUIRED")
        self.assertEqual([e.status for e in self.events], ["RECONCILIATION_REQUIRED"])

    def test_lease_expiry_emits_reconciliation_once_and_not_interrupted(self):
        partial = self.registry.start(self.project_id, self.fake_success)
        (self.render_dir(partial) / "final.mp4").write_bytes(b"partial")
        with self.factory.begin() as session:
            session.get(ProjectRenderRun, partial).lease_expires_at = utcnow() - timedelta(seconds=100)
        self.registry.snapshot(self.project_id)
        self.registry.history(self.project_id)
        self.assertEqual([(e.render_id, e.status) for e in self.events], [(partial, "RECONCILIATION_REQUIRED")])
        self.assertEqual(self.seen_status, ["RECONCILIATION_REQUIRED"])

        plain = self.registry.start(self.project_id, self.fake_success)
        with self.factory.begin() as session:
            session.get(ProjectRenderRun, plain).lease_expires_at = utcnow() - timedelta(seconds=100)
        self.registry.snapshot(self.project_id)
        self.assertEqual(self.row(plain).status, "INTERRUPTED")
        self.assertEqual(len(self.events), 1)  # INTERRUPTED is outside the MVP event set
        self.assert_replay_identical()

    def test_rolled_back_transition_emits_nothing(self):
        running = self.registry.start(self.project_id, self.fake_success)
        (self.render_dir(running) / "final.mp4").write_bytes(b"partial")
        with self.factory.begin() as session:
            session.get(ProjectRenderRun, running).lease_expires_at = utcnow() - timedelta(seconds=100)
        with patch("backend.app.services.persistent_render_execution.plan_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.registry.start(self.project_id, self.fake_success)
        self.assertEqual(self.row(running).status, "QUEUED")
        self.assertEqual(self.events, [])

    def test_start_failure_event(self):
        class Refusing:
            def submit(self, operation): raise RuntimeError("executor down")

        self.registry._executor = Refusing()
        with self.assertRaises(RuntimeError):
            self.registry.start(self.project_id, self.fake_success)
        self.assertEqual([(e.status, e.safe_error_code) for e in self.events], [("FAILED", "RENDER_START_FAILED")])
        self.assert_replay_identical()

    def test_replay_filters_and_dry_run(self):
        first = self.run_render(self.fake_success)
        middle = datetime.now(timezone.utc)
        time.sleep(0.01)
        second = self.run_render(self.fake_success)
        lines = []
        summary = replay(self.factory, since=middle, out=lines.append)
        self.assertEqual(summary, {"events": 1, "would_send": 1})
        self.assertTrue(lines[0].startswith(f"render-{second.hex}-completed\t"))
        until = collect_terminal_events(self.factory, since=datetime(2000, 1, 1, tzinfo=timezone.utc), until=middle)
        self.assertEqual([e.render_id for e in until], [first])
        self.assertEqual(collect_terminal_events(self.factory, since=datetime(2000, 1, 1, tzinfo=timezone.utc),
                                                 project_id=uuid4()), [])


class FakeReceiver:
    """Local stand-in for the n8n workflow: header auth, validation, atomic record, verify, then answer."""

    KEYS = ("schema_version", "event_id", "event_type", "project_id", "render_id", "status", "safe_error_code",
            "finished_at", "duration_seconds", "file_size_bytes", "status_url")

    def __init__(self, directory: Path, token: str = TOKEN, fail_with: int | None = None):
        self.directory, self.token, self.fail_with = directory, token, fail_with
        self.lock = Lock()
        self.requests = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                status, answer = receiver.handle(self.path, dict(self.headers), body)
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/webhook/cutory-render-events"
        Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()

    def handle(self, path, headers, raw):
        self.requests.append(headers)
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 403, {"result": "unauthorized"}
        if self.fail_with:
            return self.fail_with, {"result": "error"}
        try:
            body = json.loads(raw)
            assert isinstance(body, dict) and tuple(sorted(body)) == tuple(sorted(self.KEYS))
            suffix = body["status"].lower()
            assert body["event_id"] == f"render-{UUID(body['render_id']).hex}-{suffix}"
            assert body["event_type"] == f"render.{suffix}"
        except Exception:
            return 400, {"result": "invalid"}
        record = json.dumps({key: body[key] for key in self.KEYS}, separators=(",", ":")) + "\n"
        target = self.directory / f"{body['event_id']}.json"
        with self.lock:
            try:
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(record)
                result = "recorded"
            except FileExistsError:
                result = "duplicate"
            if target.read_text(encoding="utf-8") != record:
                return 409, {"result": "conflict"}
        return 200, {"result": result, "event_id": body["event_id"]}


class FakeReceiverRoundTripTests(RegistryEventTests):
    """Registry → dispatcher thread → real HTTP on 127.0.0.1 → fake receiver. Inherits setUp only."""

    def setUp(self):
        super().setUp()
        self.inbox = self.root / "inbox"; self.inbox.mkdir()
        self.log_path = self.root / "deliveries.jsonl"

    def make_dispatcher(self, receiver_url, token=TOKEN):
        dispatcher = RenderEventDispatcher(RenderEventSettings(url=receiver_url, token=token),
                                           backoff_seconds=(0.01, 0.01, 0.01), log_path=self.log_path)
        self.addCleanup(dispatcher.close, 1)
        self.registry = PersistentProjectRenderRunRegistry(self.executor, self.factory, self.output,
                                                           on_terminal=dispatcher.submit)
        return dispatcher

    def records(self):
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def test_round_trip_then_replay_is_a_duplicate(self):
        receiver = FakeReceiver(self.inbox); self.addCleanup(receiver.close)
        dispatcher = self.make_dispatcher(receiver.url)
        render_id = self.run_render(self.fake_success)
        dispatcher.close(5)
        stored = json.loads((self.inbox / f"render-{render_id.hex}-completed.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "COMPLETED")
        replayer = RenderEventDispatcher(RenderEventSettings(url=receiver.url, token=TOKEN), backoff_seconds=(0, 0, 0),
                                         log_path=self.log_path, start=False)
        self.addCleanup(replayer.close, 1)
        lines = []
        self.assertEqual(replay(self.factory, since=datetime(2000, 1, 1, tzinfo=timezone.utc),
                                dispatcher=replayer, out=lines.append), {"events": 1, "delivered": 1})
        results = [(r["trigger"], r["outcome"], r.get("receiver_result")) for r in self.records()]
        self.assertEqual(results, [("live", "delivered", "recorded"), ("replay", "delivered", "duplicate")])
        self.assertEqual(len(list(self.inbox.iterdir())), 1)
        self.assertNotIn(TOKEN, self.log_path.read_text(encoding="utf-8"))

    def test_receiver_down_or_wrong_token_keeps_render_completed(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); closed_port = probe.getsockname()[1]
        dispatcher = self.make_dispatcher(f"http://127.0.0.1:{closed_port}/webhook/cutory-render-events")
        down = self.run_render(self.fake_success)
        dispatcher.close(30)  # Windows takes ~2 s per refused loopback connect
        self.assertEqual(self.row(down).status, "COMPLETED")
        self.assertEqual([r["outcome"] for r in self.records()], ["retrying", "retrying", "retrying", "failed"])
        self.assertEqual(self.records()[-1]["error_type"], "ConnectError")

        receiver = FakeReceiver(self.inbox, token="x" * 40); self.addCleanup(receiver.close)
        self.make_dispatcher(receiver.url).deliver(event_from_row(self.row(down)))
        self.assertEqual((self.records()[-1]["outcome"], self.records()[-1]["http_status"]), ("rejected", 403))
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_receiver_storage_error_is_retried_then_failed(self):
        receiver = FakeReceiver(self.inbox, fail_with=500); self.addCleanup(receiver.close)
        dispatcher = self.make_dispatcher(receiver.url)
        render_id = self.run_render(self.fake_success)
        dispatcher.close(5)
        self.assertEqual(self.row(render_id).status, "COMPLETED")
        self.assertEqual(len(receiver.requests), 4)
        self.assertEqual(self.records()[-1]["outcome"], "failed")


# Run only the round-trip tests in the subclass, not the inherited registry tests again.
for _name in [n for n in vars(RegistryEventTests) if n.startswith("test_")]:
    setattr(FakeReceiverRoundTripTests, _name, None)


class StartupWiringTests(TestCase):
    def test_dispatcher_only_with_valid_configuration_and_persistence(self):
        with patch.dict(os.environ, {"CUTORY_N8N_WEBHOOK_URL": "", "CUTORY_N8N_WEBHOOK_TOKEN": ""}):
            self.assertIsNone(create_render_event_dispatcher(True))
        with patch.dict(os.environ, {"CUTORY_N8N_WEBHOOK_URL": "http://10.0.0.5:5678/webhook/x",
                                     "CUTORY_N8N_WEBHOOK_TOKEN": TOKEN}):
            with self.assertLogs("cutory.render_events", "WARNING") as logs:
                self.assertIsNone(create_render_event_dispatcher(True))
            self.assertIn("RENDER_EVENT_URL_NOT_LOOPBACK", logs.output[0])
            self.assertNotIn("10.0.0.5", logs.output[0])
        with TemporaryDirectory() as temporary:
            environment = {"CUTORY_N8N_WEBHOOK_URL": WEBHOOK, "CUTORY_N8N_WEBHOOK_TOKEN": TOKEN,
                           "CUTORY_RENDER_EVENT_LOG": str(Path(temporary) / "d.jsonl")}
            with patch.dict(os.environ, environment):
                with self.assertLogs("cutory.render_events", "WARNING"):
                    self.assertIsNone(create_render_event_dispatcher(False))
                dispatcher = create_render_event_dispatcher(True)
                self.assertIsInstance(dispatcher, RenderEventDispatcher)
                dispatcher.close(1)


class WorkflowContractTests(TestCase):
    def test_workflow_json_is_built_from_the_code_file_and_holds_no_secret(self):
        workflow_dir = REPO / "deploy" / "n8n"
        raw = (workflow_dir / "cutory-render-events.workflow.json").read_text(encoding="utf-8")
        workflow = json.loads(raw)
        nodes = {node["type"]: node for node in workflow["nodes"]}
        webhook = nodes["n8n-nodes-base.webhook"]["parameters"]
        self.assertEqual((webhook["httpMethod"], webhook["authentication"], webhook["responseMode"]),
                         ("POST", "headerAuth", "responseNode"))
        self.assertEqual(nodes["n8n-nodes-base.code"]["parameters"]["jsCode"],
                         (workflow_dir / "record-render-event.js").read_text(encoding="utf-8"))
        self.assertIn("respondToWebhook", "".join(nodes))
        self.assertFalse(workflow["active"])
        for forbidden in ("Bearer ", "credentials", "password", "apiKey"):
            self.assertNotIn(forbidden, raw)
        build = {"__name__": "build_check", "__file__": str(workflow_dir / "build_workflow.py")}
        exec(compile((workflow_dir / "build_workflow.py").read_text(encoding="utf-8"), "build_workflow.py", "exec"), build)
        self.assertEqual(build["render"](), raw)  # JSON is not stale

    def test_workflow_and_instance_do_not_keep_execution_data(self):
        # Execution data holds the webhook headers, i.e. the Bearer token (found 2026-11-06 on n8n 2.46.6).
        workflow_dir = REPO / "deploy" / "n8n"
        settings = json.loads((workflow_dir / "cutory-render-events.workflow.json").read_text(encoding="utf-8"))["settings"]
        self.assertEqual(settings["saveDataSuccessExecution"], "none")
        self.assertEqual(settings["saveDataErrorExecution"], "none")
        self.assertIs(settings["saveManualExecutions"], False)
        self.assertIs(settings["saveExecutionProgress"], False)
        compose = (workflow_dir / "docker-compose.yml").read_text(encoding="utf-8")
        for line in ("EXECUTIONS_DATA_SAVE_ON_SUCCESS: none", "EXECUTIONS_DATA_SAVE_ON_ERROR: none",
                     'EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS: "false"', 'EXECUTIONS_DATA_SAVE_ON_PROGRESS: "false"',
                     'EXECUTIONS_DATA_HARD_DELETE_BUFFER: "0"', '"127.0.0.1:5678:5678"'):
            self.assertIn(line, compose)
        self.assertNotIn("Bearer", compose)
