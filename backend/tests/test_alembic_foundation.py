from pathlib import Path
from unittest import TestCase

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.config import PROJECT_ROOT
from backend.app.database import Base
import backend.app.models  # noqa: F401  # Register v1 product metadata.


class AlembicFoundationTests(TestCase):
    def test_alembic_configuration_loads_without_stored_database_url(self) -> None:
        config_path = PROJECT_ROOT / "alembic.ini"
        config = Config(config_path)
        script = ScriptDirectory.from_config(config)

        self.assertEqual(Path(script.dir).resolve(), PROJECT_ROOT / "backend" / "alembic")
        self.assertIsNone(config.get_main_option("sqlalchemy.url", None))
        self.assertTrue((Path(script.dir) / "env.py").is_file())
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "projects",
                "source_videos",
                "processing_stages",
                "transcripts",
                "edit_memos",
            },
        )
