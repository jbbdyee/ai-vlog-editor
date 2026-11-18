"""TODO 32-2: a 181-cut plan made a command line longer than Windows allows (CONCAT_START_FAILED)."""

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from backend.app.services.clip_renderer import RenderedClip
from backend.app.services.project_rendering import MAX_COMMAND_CHARS, _command_chars, _concat_commands


def clips(count: int, folder: Path) -> list[RenderedClip]:
    long_dir = folder / ("x" * 150)
    return [RenderedClip(long_dir / "source.mp4", long_dir / f"{index:04d}-{'c' * 40}.mp4", Decimal(0), Decimal(2),
                         2.0, "h264", "aac") for index in range(count)]


class LongPlanConcatTests(TestCase):
    def test_short_plan_keeps_one_command(self):
        with tempfile.TemporaryDirectory() as root:
            commands = _concat_commands(clips(5, Path(root)), [True] * 5, Path(root) / "final.mp4", "ffmpeg", Path(root))
            self.assertEqual(len(commands), 1)
            self.assertIn("-filter_complex", commands[0])

    def test_long_plan_is_joined_in_groups_then_copied(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            durations = [2.0] * 181
            commands = _concat_commands(clips(181, workspace), [True] * 180 + [False], workspace / "final.mp4",
                                        "ffmpeg", workspace, audio_durations=durations)
            self.assertEqual(len(commands), 6)  # 5 groups of up to 40 + the copy
            self.assertTrue(all(_command_chars(command) <= MAX_COMMAND_CHARS for command in commands))
            self.assertEqual(commands[-1][-1], str(workspace / "final.mp4"))
            self.assertIn("copy", commands[-1])
            listing = (workspace / "groups.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(listing, [f"file 'group-{index:03d}.mp4'" for index in range(5)])
            self.assertIn("anullsrc", " ".join(commands[4]))  # the last clip without sound is still padded
