"""TODO 35: light 720p copies of the sources for the edit room."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from backend.app.services import source_previews

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def probe(path: Path) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
                          "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg is needed")
class MakePreviewTest(unittest.TestCase):
    def test_portrait_source_becomes_720_wide_h264_of_the_same_length(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=60:duration=3",
                            "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)], check=True)
            target = source_previews.preview_path(root / "outputs", uuid4(), uuid4())

            source_previews.make_preview(source, target)

            info = probe(target)
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["codec_name"], video["width"], video["height"], video["r_frame_rate"]), ("h264", 720, 1280, "30/1"))
            self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
            self.assertAlmostEqual(float(info["format"]["duration"]), float(probe(source)["format"]["duration"]), delta=0.1)
            self.assertFalse(target.with_suffix(".tmp.mp4").exists())

    def test_a_broken_source_leaves_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "broken.mp4"
            source.write_bytes(b"not a video")
            target = Path(folder) / "previews" / "x.mp4"
            with self.assertRaises(source_previews.PreviewError):
                source_previews.make_preview(source, target)
            self.assertEqual(list(target.parent.iterdir()), [])


class PreviewQueueTest(unittest.TestCase):
    def test_makes_each_missing_copy_once_in_order_and_keeps_going_after_a_failure(self) -> None:
        made: list[str] = []
        gate = threading.Event()

        def fake(source: Path, target: Path) -> Path:
            gate.wait(5)
            made.append(source.name)
            if source.name == "b":
                raise source_previews.PreviewError("PREVIEW_FAILED")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            return target

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            items = [(root / name, root / "p" / f"{name}.mp4") for name in ("a", "b", "c")]
            queue = source_previews.PreviewQueue(make=fake)
            queue.ensure(items)
            for _ in range(500):
                if queue.state(items[0][1]) == "making":
                    break
                threading.Event().wait(0.01)
            queue.ensure([items[2], items[1]])  # asking again adds nothing, but "c" now goes before "b"
            gate.set()
            queue._thread.join(5)

            self.assertEqual(made, ["a", "c", "b"])
            self.assertEqual([queue.state(target) for _, target in items], ["ready", "failed", "ready"])
            queue.ensure(items)
            self.assertEqual(made, ["a", "c", "b"])


if __name__ == "__main__":
    unittest.main()
