"""TODO 12: the saved reel draft becomes a vertical 1080x1920 video with the title, name tags and lines burned in."""

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import EpisodeSplitPolicy, Project, SourceVideo
from backend.app.models.reel import ProjectReelDraft
from backend.app.services.reel_draft import ReelDraft, ReelScene
from backend.app.services.reel_render import (DEFAULT_FONT, ReelRenderError, build_ass, clean_text, draft_fingerprint,
                                              render_reel, saved_video)
from backend.app.services.reel_text import TEMPLATES, TextStyle, font_files, normalize, split_title, wrap

VERTICAL = "00000000-0000-0000-0000-00000000000a"
WIDE = "00000000-0000-0000-0000-00000000000b"
HAVE_TOOLS = shutil.which("ffmpeg") is not None and DEFAULT_FONT.is_file()


def draft(*scenes, title="이 3벌 중에 골라줘 😍"):
    return ReelDraft("short", "haul", "옷 입어보기·하울", "normal", "보통", 15, 0.0, title, "llm:test",
                     tuple(scenes), len(scenes))


def scene(index, source, start, end, caption="", label="", hook=False):
    return ReelScene(index, source, f"{source[-1]}.mp4", start, end, caption, label, hook)


def make_video(path: Path, width: int, height: int, seconds: float, audio: bool) -> Path:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=60:d={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(command + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         check=True, capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1]), float(out[2])


class SubtitleTextTests(TestCase):
    def test_emoji_dropped_and_braces_cannot_become_ass_commands(self):
        self.assertEqual(clean_text("핏 미쳤다 😍✨ {\\b1}진짜  "), "핏 미쳤다 (b1)진짜")

    def events(self, ass):
        """(start, end, text) of every Dialogue line; text is what follows the {tags}."""
        rows = []
        for line in ass.splitlines():
            if line.startswith("Dialogue"):
                parts = line.split(",", 9)
                rows.append((parts[1], parts[2], parts[9].split("}", 1)[1]))
        return rows

    def three_scenes(self):
        return draft(scene(3, VERTICAL, 1.0, 2.0, "첫 장면", "브라운 미니스커트", True),
                     scene(1, VERTICAL, 0.0, 2.5, "핏 예쁘지?", "첫 번째 · 브라운 미니스커트"),
                     scene(2, WIDE, 0.0, 1.5, ""))

    def test_title_on_first_scene_and_each_scene_gets_its_tag_and_line_back_to_back(self):
        ass = build_ass(self.three_scenes())
        rows = self.events(ass)
        # Hook is 1 s, but the title stays at least 2.5 s so it can be read.
        self.assertIn(("0:00:00.00", "0:00:02.50", "이 3벌 중에 골라줘"), rows)
        self.assertIn(("0:00:01.00", "0:00:03.50", "핏 예쁘지?"), rows)
        self.assertIn(("0:00:01.00", "0:00:03.50", "첫 번째 · 브라운 미니스커트"), rows)
        self.assertEqual(len(rows), 5, "an empty line makes no subtitle")
        self.assertIn("PlayResY: 1920", ass)

    def test_every_template_keeps_all_the_words_and_looks_different(self):
        seen = set()
        for template in TEMPLATES:
            ass = build_ass(self.three_scenes(), TextStyle(template=template.key))
            words = "".join(text for _, _, text in self.events(ass))
            for expected in ("골라줘", "핏 예쁘지?", "브라운 미니스커트"):
                self.assertIn(expected, words, template.key)
            seen.add(ass)
            self.assertTrue(all(file.is_file() for file in font_files(TextStyle(template=template.key))))
        self.assertEqual(len(seen), len(TEMPLATES))

    def test_colour_place_and_size_change_the_result_and_unknown_choices_fall_back(self):
        base = build_ass(self.three_scenes(), TextStyle("pixel"))
        for change in (TextStyle("pixel", color="pink"), TextStyle("pixel", position="bottom"), TextStyle("pixel", size="large")):
            self.assertNotEqual(build_ass(self.three_scenes(), change), base)
        self.assertEqual(normalize({"template": "nope", "color": "?", "position": 3, "size": None}), TextStyle())
        self.assertEqual(build_ass(self.three_scenes(), {"template": "nope"}), build_ass(self.three_scenes()))

    def test_lines_wait_under_the_title_when_both_sit_at_the_top(self):
        def top_of(ass, text):
            line = next(row for row in ass.splitlines() if row.endswith("}" + text))
            if "\\move(" in line:  # TODO 15: where a rising line comes to rest
                return int(line.split("\\move(")[1].split(")")[0].split(",")[3])
            return int(line.split("\\pos(")[1].split(")")[0].split(",")[1])

        ass = build_ass(self.three_scenes(), TextStyle("pixel"))  # title and lines both at the top
        self.assertGreater(top_of(ass, "첫 장면"), top_of(ass, "중에 골라줘") + 100, "under the title while it is up")
        late = draft(scene(1, VERTICAL, 0.0, 3.0, "첫 장면", hook=True), scene(2, VERTICAL, 0.0, 2.0, "나중 장면"))
        self.assertEqual(top_of(build_ass(late, TextStyle("pixel")), "나중 장면"), 300, "back at the top afterwards")

    def test_lead_in_from_the_draft_is_its_own_text_box(self):
        """TODO 14: Blo's title is two text boxes; the AI writes both, nothing is cut in the middle."""
        from dataclasses import replace
        two = replace(draft(scene(1, "s1", 0, 3, hook=True), title="첫 댄스곡 도전기"), title_lead="나만 아는 가수의")
        for key in ("pixel", "clean", "basic"):
            ass = build_ass(two, TextStyle(key))
            self.assertRegex(ass, r"}나만 아는 가수의\n", key)
            self.assertRegex(ass, r"}첫 댄스곡 도전기\n", key)

    def line_of(self, ass, text):
        return next(row for row in ass.splitlines() if row.endswith("}" + text))

    def test_pill_template_has_no_dark_box_but_keeps_the_coloured_name_tag(self):
        """TODO 15: no dark box behind the lines; the name tag keeps its coloured pill."""
        ass = build_ass(self.three_scenes(), TextStyle("box", motion="none"))
        drawings = [row for row in ass.splitlines() if "\\p1" in row]
        self.assertTrue(drawings, "the name tag and the big title still sit on pills")
        self.assertFalse(any("&H141010&" in row for row in drawings), "no dark box")
        self.assertEqual(len(drawings), 3, "big title + two name tags, none for the plain lines")

    def test_motion_pop_rise_and_none(self):
        """TODO 15: the title pops (or rises) in within 0.25 s and fades out; scene lines rise in with each cut."""
        pop = build_ass(self.three_scenes(), TextStyle("pixel"))  # default motion is pop
        title = self.line_of(pop, "중에 골라줘")
        self.assertIn("\\fscx70", title)
        self.assertIn("\\t(230,330,\\fscx100\\fscy100)", title, "big line starts 80 ms after the lead, done by 0.33 s")
        self.assertRegex(title, r"\\fade\(255,0,255,80,200,2300,2500\)", "fades out over the last 0.2 s")
        caption = self.line_of(pop, "핏 예쁘지?")
        self.assertRegex(caption, r"\\move\(540,\d+,540,\d+,0,150\)")
        self.assertRegex(caption, r"\\fade\(255,0,0,0,150,2500,2500\)", "leaves with the cut")
        rise = self.line_of(build_ass(self.three_scenes(), TextStyle("pixel", motion="rise")), "중에 골라줘")
        self.assertIn("\\move(", rise)
        self.assertNotIn("\\fscx70", rise)
        still = build_ass(self.three_scenes(), TextStyle(motion="none"))
        self.assertNotIn("\\fade", still)
        self.assertNotIn("\\move", still)
        self.assertEqual(normalize({"motion": "spin"}).motion, "pop")

    def test_diary_template_uses_the_ownglyph_hand_and_sparkles_the_lead_in(self):
        from dataclasses import replace
        two = replace(draft(scene(1, "s1", 0, 3, "회 진짜 맛있어", hook=True), title="고흥 회 맛집"), title_lead="새벽에 달려간")
        ass = build_ass(two, TextStyle("diary"))
        self.assertRegex(ass, r"}✦ 새벽에 달려간 ✦\n")
        self.assertIn("\\fnOwnglyph PDH Regular", self.line_of(ass, "고흥 회 맛집"))
        self.assertIn("\\fnOwnglyph Shin Yebin Regular", build_ass(two, TextStyle("hand")))

    def test_long_lines_are_wrapped_and_the_title_splits_into_lead_and_punch_line(self):
        self.assertEqual(split_title("직접 입어본 추천템 3가지"), ["직접 입어본", "추천템 3가지"])
        self.assertEqual(split_title("골라줘"), ["골라줘"])
        lines = wrap("선생님이 진짜 잘 가르쳐주심 최고였다 다음에도 꼭 다시 오고 싶은 수업", 84)
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines), "선생님이 진짜 잘 가르쳐주심 최고였다 다음에도 꼭 다시 오고 싶은 수업")


@skipUnless(HAVE_TOOLS, "needs FFmpeg and the Malgun Gothic font")
class RenderReelTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = {VERTICAL: make_video(self.root / "v.mp4", 360, 640, 4, audio=True),
                        WIDE: make_video(self.root / "w.mp4", 640, 360, 4, audio=False)}

    def test_vertical_and_wide_sources_become_one_1080x1920_video_of_the_draft_length(self):
        reel = draft(scene(2, VERTICAL, 2.0, 3.0, "첫 장면", "", True), scene(1, WIDE, 0.0, 1.5, "가로 영상 😎"),
                     scene(3, VERTICAL, 0.5, 2.25, "마지막", "두 번째 · 블라우스"))
        steps = []
        video = render_reel(reel, self.sources, self.root / "out", on_progress=lambda s, d, t: steps.append(s),
                            text_style=TextStyle("clean", color="pink"))
        width, height, seconds = probe(video.path)
        self.assertEqual((width, height), (1080, 1920))
        self.assertAlmostEqual(seconds, 4.25, delta=0.1)
        self.assertEqual(video.scene_count, 3)
        self.assertEqual(steps[-1], "제목·문구 글자 입히기")
        self.assertEqual(saved_video(self.root / "out").draft_fingerprint, draft_fingerprint(reel))
        self.assertEqual(saved_video(self.root / "out").text_style, TextStyle("clean", color="pink"))
        self.assertEqual([p.name for p in (self.root / "out").iterdir()], ["reel.json", "reel.mp4"],
                         "work files are cleaned up")

    def test_missing_source_is_reported_before_anything_is_cut(self):
        with self.assertRaises(ReelRenderError) as caught:
            render_reel(draft(scene(1, str(uuid4()), 0, 1, "x", hook=True)), self.sources, self.root / "out")
        self.assertEqual(caught.exception.code, "REEL_SOURCE_MISSING")


class ReelVideoApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite+pysqlite:///{root / 'reel.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start()
        self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        output = patch.object(app.state, "project_render_output_root", root / "outputs", create=True)
        output.start()
        self.addCleanup(output.stop)
        resolve = patch.object(app.state.source_storage, "resolve", lambda reference: root / "originals" / "a.mp4")
        resolve.start()
        self.addCleanup(resolve.stop)
        with self.factory() as session:
            project = Project(name="reels", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.flush()
            source = SourceVideo(project_id=project.id, original_filename="a.mp4",
                                 storage_reference=f"projects/{project.id.hex}/sources/a.mp4", duration_seconds=5)
            session.add(source)
            session.flush()
            self.project_id, self.source_id = project.id, source.id
            session.commit()

    def save_draft(self, caption="문구"):
        reel = draft(scene(1, str(self.source_id), 0, 1, caption, hook=True))
        with self.factory() as session:
            record = session.get(ProjectReelDraft, self.project_id) or ProjectReelDraft(project_id=self.project_id)
            record.format, record.mode, record.pace, record.target_seconds = "short", "haul", "normal", 15
            record.analysis_fingerprint, record.shots, record.draft = "x", [], reel.to_json()
            session.add(record)
            session.commit()

    def wait(self):
        for _ in range(200):
            body = self.client.get(f"/projects/{self.project_id}/reel-video").json()
            if body["status"] != "RUNNING":
                return body
            time.sleep(0.02)
        self.fail("reel video did not finish")

    def fake_render(self, reel, sources, output_dir, on_progress=None, text_style=None):
        self.seen_sources, self.seen_style = sources, text_style
        output_dir.mkdir(parents=True)
        (output_dir / "reel.mp4").write_bytes(b"mp4")
        (output_dir / "reel.json").write_text(
            f'{{"duration_seconds": 1.0, "file_size_bytes": 3, "draft_fingerprint": "{draft_fingerprint(reel)}", '
            f'"scene_count": 1, "text_style": {{"template": "{text_style.template}"}}}}', encoding="utf-8")

    def test_needs_a_draft_first(self):
        refused = self.client.post(f"/projects/{self.project_id}/reel-video")
        self.assertEqual((refused.status_code, refused.json()["detail"]["code"]), (409, "REEL_DRAFT_MISSING"))
        self.assertEqual(self.client.get(f"/projects/{uuid4()}/reel-video").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/reel-video/file").status_code, 404)

    def test_make_play_and_notice_when_the_draft_changes_afterwards(self):
        self.save_draft()
        with patch("backend.app.services.reel_render.render_reel", self.fake_render):
            started = self.client.post(f"/projects/{self.project_id}/reel-video",
                                       json={"text_style": {"template": "hook", "color": "sky", "size": "huge"}})
            self.assertEqual(started.status_code, 202)
            body = self.wait()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertEqual(self.seen_style, TextStyle("hook", color="sky"), "an unknown size falls back to normal")
        self.assertEqual(body["video"]["text_style"]["template"], "hook")
        options = self.client.get("/projects/reel-options").json()
        self.assertEqual([t["key"] for t in options["text_templates"]], [t.key for t in TEMPLATES])
        self.assertEqual(options["text_positions"][0], {"key": "auto", "label": "템플릿 기본"})
        self.assertIn(str(self.source_id), self.seen_sources)
        self.assertTrue(body["video"]["matches_draft"])
        file = self.client.get(body["video"]["url"])
        self.assertEqual((file.status_code, file.content, file.headers["content-type"]), (200, b"mp4", "video/mp4"))
        self.save_draft(caption="바뀐 문구")
        self.assertFalse(self.client.get(f"/projects/{self.project_id}/reel-video").json()["video"]["matches_draft"])
