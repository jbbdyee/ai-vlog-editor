import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from dotenv import load_dotenv

from app.config import DOTENV_PATH, PROJECT_ROOT


class ConfigTests(TestCase):
    def test_dotenv_path_points_to_project_root(self) -> None:
        self.assertEqual(PROJECT_ROOT, Path(__file__).resolve().parent.parent)
        self.assertEqual(DOTENV_PATH, PROJECT_ROOT / ".env")

    def test_dotenv_does_not_override_existing_process_value(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            dotenv_path.write_text("TEST_CONFIG_VALUE=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"TEST_CONFIG_VALUE": "from-process"}):
                load_dotenv(dotenv_path=dotenv_path, override=False)
                self.assertEqual(os.environ["TEST_CONFIG_VALUE"], "from-process")
