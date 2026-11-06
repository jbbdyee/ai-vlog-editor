"""Render terminal events for an n8n webhook (follow-up only; the DB row stays authoritative).

Events are built only after a terminal status was committed. Delivery runs on its own
thread, never raises into the render path, and records outcomes without the URL, token or payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import queue
import re
from threading import Event, Lock, Thread
import time
from typing import Callable, Iterable, Mapping
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx


logger = logging.getLogger("cutory.render_events")

SCHEMA_VERSION = 1
TERMINAL_EVENT_STATUSES = ("COMPLETED", "FAILED", "RECONCILIATION_REQUIRED")
EVENT_ID_PATTERN = re.compile(r"^render-[0-9a-f]{32}-(completed|failed|reconciliation_required)$")
URL_ENV = "CUTORY_N8N_WEBHOOK_URL"
TOKEN_ENV = "CUTORY_N8N_WEBHOOK_TOKEN"
LOG_ENV = "CUTORY_RENDER_EVENT_LOG"
MIN_TOKEN_LENGTH = 32
LOOPBACK_NAMES = {"localhost"}
DEFAULT_BACKOFF_SECONDS = (1.0, 4.0, 15.0)  # 1 attempt + 3 retries
RECEIVER_RESULTS = {"recorded", "duplicate"}


class RenderEventConfigError(ValueError):
    """Invalid webhook configuration. Carries a code only, never the offending value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, repr=False)
class RenderEventSettings:
    url: str
    token: str
    timeout_seconds: float = 3.0
    log_path: Path | None = None

    def __repr__(self) -> str:  # never print the URL path or the token
        return f"RenderEventSettings(url=<set>, token=<hidden>, timeout_seconds={self.timeout_seconds})"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "RenderEventSettings | None":
        values = os.environ if environment is None else environment
        url = (values.get(URL_ENV) or "").strip()
        token = values.get(TOKEN_ENV) or ""
        if not url and not token:
            return None  # disabled: current behaviour is unchanged
        if not url:
            raise RenderEventConfigError("RENDER_EVENT_URL_MISSING")
        if not token:
            raise RenderEventConfigError("RENDER_EVENT_TOKEN_MISSING")
        validate_webhook_url(url)
        validate_token(token)
        log_value = (values.get(LOG_ENV) or "").strip()
        return cls(url=url, token=token, log_path=Path(log_value) if log_value else None)


def validate_webhook_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # raises ValueError on a malformed port
    except ValueError as error:
        raise RenderEventConfigError("RENDER_EVENT_URL_INVALID") from error
    if parts.scheme not in {"http", "https"} or not host or not parts.path.strip("/"):
        raise RenderEventConfigError("RENDER_EVENT_URL_INVALID")
    if parts.username or parts.password or parts.query or parts.fragment:
        # The token travels only in a header; no secrets or extras in the URL.
        raise RenderEventConfigError("RENDER_EVENT_URL_HAS_CREDENTIALS_OR_QUERY")
    if host.lower() in LOOPBACK_NAMES:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RenderEventConfigError("RENDER_EVENT_URL_NOT_LOOPBACK")


def validate_token(token: str) -> None:
    if len(token) < MIN_TOKEN_LENGTH:
        raise RenderEventConfigError("RENDER_EVENT_TOKEN_TOO_SHORT")
    if not all(33 <= ord(char) <= 126 for char in token):
        raise RenderEventConfigError("RENDER_EVENT_TOKEN_INVALID_CHARACTERS")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:  # SQLite returns naive values; the registry always writes UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def event_id_for(render_id: UUID, status: str) -> str:
    """Stable per (render, terminal status): live sends and replays share it."""
    return f"render-{render_id.hex}-{status.lower()}"


@dataclass(frozen=True)
class RenderTerminalEvent:
    project_id: UUID
    render_id: UUID
    status: str
    safe_error_code: str | None
    finished_at: str
    duration_seconds: float | None
    file_size_bytes: int | None

    @property
    def event_id(self) -> str:
        return event_id_for(self.render_id, self.status)

    def payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "event_type": f"render.{self.status.lower()}",
            "project_id": str(self.project_id),
            "render_id": str(self.render_id),
            "status": self.status,
            "safe_error_code": self.safe_error_code,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "file_size_bytes": self.file_size_bytes,
            "status_url": f"/projects/{self.project_id}/rendering",
        }

    def body(self) -> bytes:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def terminal_event(*, project_id: UUID, render_id: UUID, status: str, safe_error_code: str | None,
                   finished_at: datetime, duration_seconds: float | None = None,
                   file_size_bytes: int | None = None) -> RenderTerminalEvent:
    if status not in TERMINAL_EVENT_STATUSES:
        raise ValueError("not a terminal event status")
    completed = status == "COMPLETED"
    return RenderTerminalEvent(
        project_id=project_id, render_id=render_id, status=status,
        safe_error_code=None if completed else safe_error_code,
        finished_at=_utc_text(finished_at),
        duration_seconds=float(duration_seconds) if completed and duration_seconds is not None else None,
        file_size_bytes=int(file_size_bytes) if completed and file_size_bytes is not None else None,
    )


def event_from_row(row) -> RenderTerminalEvent:
    """Same event as the live one, rebuilt from the stored project_render_runs row."""
    return terminal_event(project_id=row.project_id, render_id=row.render_id, status=row.status,
                          safe_error_code=row.safe_error_code, finished_at=row.finished_at,
                          duration_seconds=row.duration_seconds, file_size_bytes=row.base_size_bytes)


class DeliveryLog:
    """JSON Lines trace of delivery attempts. Only ids, outcomes and error classes."""

    def __init__(self, path: Path | None) -> None:
        self._path = Path(path) if path else None
        self._lock = Lock()

    def write(self, record: dict) -> None:
        line = " ".join(f"{key}={value}" for key, value in record.items() if value is not None)
        level = logging.INFO if record.get("outcome") in {"delivered", "would_send"} else logging.WARNING
        try:
            logger.log(level, "render_event_delivery %s", line)
        except Exception:
            pass
        if self._path is None:
            return
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            pass  # tracing must never break delivery or rendering


def _classify(response: httpx.Response) -> tuple[str, bool]:
    code = response.status_code
    if 200 <= code < 300:
        return "delivered", False
    if code in {408, 429} or code >= 500:
        return "retrying", True
    return "rejected", False  # 3xx (redirects are not followed), 400/401/403/404/409, ...


def _receiver_result(response: httpx.Response) -> str | None:
    try:
        value = response.json().get("result")
    except Exception:
        return None
    return value if value in RECEIVER_RESULTS else None


_SENTINEL = object()


class RenderEventDispatcher:
    """Single background worker that POSTs events. `submit` never blocks and never raises."""

    def __init__(self, settings: RenderEventSettings, *, transport: httpx.BaseTransport | None = None,
                 backoff_seconds: Iterable[float] = DEFAULT_BACKOFF_SECONDS, log_path: Path | None = None,
                 max_queue: int = 1000, start: bool = True) -> None:
        self._settings = settings
        self._backoff = tuple(backoff_seconds)
        self._log = DeliveryLog(log_path if log_path is not None else settings.log_path)
        self._client = httpx.Client(transport=transport, timeout=settings.timeout_seconds,
                                    follow_redirects=False, trust_env=False)
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._stop = Event()
        self._closed = False
        self._thread = Thread(target=self._worker, name="cutory-render-events", daemon=True)
        if start:
            self._thread.start()

    @property
    def max_attempts(self) -> int:
        return len(self._backoff) + 1

    def submit(self, event: RenderTerminalEvent) -> None:
        try:
            if self._closed:
                self._record(event, None, "dropped_shutdown", trigger="live")
                return
            self._queue.put_nowait(event)
        except queue.Full:
            self._record(event, None, "dropped_queue_full", trigger="live")
        except Exception:
            pass

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            if self._stop.is_set():
                self._record(item, None, "dropped_shutdown", trigger="live")
                continue
            try:
                self.deliver(item, trigger="live")
            except Exception:
                pass
        while True:  # anything submitted after close started
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not _SENTINEL:
                self._record(item, None, "dropped_shutdown", trigger="live")

    def deliver(self, event: RenderTerminalEvent, *, trigger: str = "live") -> str:
        """Send one event with bounded retries. Returns the final outcome."""
        delivery_id = uuid4().hex
        body = event.body()
        headers = {
            "Authorization": f"Bearer {self._settings.token}",
            "Content-Type": "application/json",
            "X-Cutory-Event-Id": event.event_id,
            "X-Cutory-Delivery-Id": delivery_id,
        }
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            status_code = error_type = result = None
            try:
                response = self._client.post(self._settings.url, content=body,
                                             headers={**headers, "X-Cutory-Attempt": str(attempt)})
                status_code = response.status_code
                outcome, retry = _classify(response)
                result = _receiver_result(response) if outcome == "delivered" else None
            except httpx.HTTPError as error:
                outcome, retry, error_type = "retrying", True, type(error).__name__
            except Exception as error:  # misconfiguration etc.: do not loop
                outcome, retry, error_type = "failed", False, type(error).__name__
            last = attempt == self.max_attempts
            if retry and last:
                outcome = "failed"
            elapsed = int((time.monotonic() - started) * 1000)
            self._record(event, attempt, outcome, trigger=trigger, delivery_id=delivery_id,
                         http_status=status_code, error_type=error_type, receiver_result=result, elapsed_ms=elapsed)
            if outcome != "retrying":
                return outcome
            if self._stop.wait(self._backoff[attempt - 1]):
                self._record(event, attempt, "abandoned_shutdown", trigger=trigger, delivery_id=delivery_id)
                return "abandoned_shutdown"
        return "failed"  # pragma: no cover

    def _record(self, event: RenderTerminalEvent, attempt: int | None, outcome: str, *, trigger: str,
                delivery_id: str | None = None, **extra) -> None:
        record = {"ts": _utc_text(datetime.now(timezone.utc)), "event_id": event.event_id,
                  "render_id": str(event.render_id), "status": event.status, "trigger": trigger,
                  "delivery_id": delivery_id, "attempt": attempt,
                  "max_attempts": self.max_attempts if attempt else None, "outcome": outcome}
        record.update({key: value for key, value in extra.items() if value is not None})
        self._log.write(record)

    def close(self, timeout: float = 10.0) -> None:
        """Stop accepting events, give queued ones `timeout` seconds, then abort retries."""
        if self._closed:
            return
        self._closed = True
        if self._thread.is_alive():
            deadline = time.monotonic() + timeout
            try:
                self._queue.put(_SENTINEL, timeout=max(timeout, 0.01))
            except queue.Full:
                self._stop.set()  # worker now drops the rest quickly
                try:
                    self._queue.put(_SENTINEL, timeout=self._settings.timeout_seconds + 2)
                except queue.Full:
                    pass
            self._thread.join(max(deadline - time.monotonic(), 0))
            if self._thread.is_alive():
                self._stop.set()  # abort backoff waits; an in-flight request ends within its timeout
                self._thread.join(self._settings.timeout_seconds + 2)
        else:  # never started (replay / tests): nothing will drain the queue
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not _SENTINEL:
                    self._record(item, None, "dropped_shutdown", trigger="live")
        self._client.close()


def collect_terminal_events(session_factory, *, since: datetime, until: datetime | None = None,
                            project_id: UUID | None = None, limit: int = 500) -> list[RenderTerminalEvent]:
    """Read-only: terminal rows finished in [since, until), oldest first."""
    from sqlalchemy import select
    from backend.app.models import ProjectRenderRun

    query = select(ProjectRenderRun).where(ProjectRenderRun.status.in_(TERMINAL_EVENT_STATUSES),
                                           ProjectRenderRun.finished_at.is_not(None),
                                           ProjectRenderRun.finished_at >= since)
    if until is not None:
        query = query.where(ProjectRenderRun.finished_at < until)
    if project_id is not None:
        query = query.where(ProjectRenderRun.project_id == project_id)
    query = query.order_by(ProjectRenderRun.finished_at, ProjectRenderRun.render_id).limit(limit)
    with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            session.execute(text("SET TRANSACTION READ ONLY"))
        events = [event_from_row(row) for row in session.scalars(query).all()]
        session.rollback()
    return events


TerminalCallback = Callable[[RenderTerminalEvent], None]
