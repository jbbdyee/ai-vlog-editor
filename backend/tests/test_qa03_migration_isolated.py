"""QA-03 Alembic revision e3a1c9d27b45 on a disposable isolated PostgreSQL database.

Run only with QA03_POSTGRES_URL pointing at an EMPTY disposable database whose
name starts with cutory_qa03_ on the isolated instance (port 55432). Never point
this at the current Cutory DB: it runs upgrade/downgrade from base.
"""

import os
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError

from backend.app.config import PROJECT_ROOT

PREVIOUS, TARGET = "b8c01e2a4f60", "e3a1c9d27b45"
COLUMNS = ("base_sha256", "srt_sha256", "hard_sha256")
DIGEST = "ab" * 32


class IsolatedMigrationTests(TestCase):
    def setUp(self):
        raw = os.getenv("QA03_POSTGRES_URL")
        if not raw:
            self.skipTest("Disposable QA-03 PostgreSQL URL is required.")
        url = make_url(raw)
        if url.port != 55432 or not (url.database or "").startswith("cutory_qa03_"):
            self.skipTest("Only an isolated cutory_qa03_* database on port 55432 is allowed.")
        self.engine = create_engine(url)
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            if inspect(connection).get_table_names():
                self.skipTest("The disposable database must start empty.")
        env = {"POSTGRES_HOST": url.host, "POSTGRES_PORT": str(url.port), "POSTGRES_DB": url.database,
               "POSTGRES_USER": url.username, "POSTGRES_PASSWORD": url.password}
        environment = patch.dict(os.environ, env)
        environment.start(); self.addCleanup(environment.stop)
        self.config = Config(PROJECT_ROOT / "alembic.ini")

    def scalar(self, sql, **params):
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()

    def counts(self):
        with self.engine.connect() as connection:
            tables = [name for name in inspect(connection).get_table_names() if name != "alembic_version"]
            return {name: connection.execute(text(f'SELECT count(*) FROM "{name}"')).scalar() for name in sorted(tables)}

    def legacy_fingerprint(self):
        # Every pre-QA-03 column of every render row, order-stable.
        return self.scalar(
            "SELECT md5(string_agg(row_to_json(r)::text, '|' ORDER BY r.render_id)) FROM ("
            "SELECT render_id, project_id, status, plan_snapshot::text AS plan, plan_fingerprint, created_at,"
            " started_at, finished_at, base_relpath, base_size_bytes, duration_seconds, video_codec, audio_codec,"
            " srt_relpath, srt_size_bytes, hard_relpath, hard_size_bytes, safe_error_code, subtitle_error_code,"
            " hard_subtitle_error_code, owner_token, lease_expires_at, heartbeat_at, interrupted_reason"
            " FROM project_render_runs) r")

    def columns(self):
        with self.engine.connect() as connection:
            return {column["name"]: column for column in inspect(connection).get_columns("project_render_runs")}

    def persistent_startup(self):
        """Start the real app lifespan with persistence on; return None or the startup error."""
        from fastapi.testclient import TestClient
        from backend.app.main import app
        with patch("backend.app.main.load_model", return_value=object()), \
                patch.dict(os.environ, {"CUTORY_RENDER_PERSISTENCE_ENABLED": "1"}):
            try:
                with TestClient(app):
                    return None
            except RuntimeError as error:
                return str(error)

    def seed_history(self):
        project_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id, name, status, split_policy) "
                                    "VALUES (:id, 'QA-03 migration', 'CREATED', 'SINGLE')"), {"id": project_id})
            for index, status in enumerate(("COMPLETED", "COMPLETED", "FAILED", "INTERRUPTED",
                                            "RECONCILIATION_REQUIRED", "QUEUED")):
                render_id = uuid4()
                completed = status == "COMPLETED"
                connection.execute(text(
                    "INSERT INTO project_render_runs (render_id, project_id, status, plan_snapshot, plan_fingerprint,"
                    " created_at, base_relpath, base_size_bytes, hard_relpath, hard_size_bytes, safe_error_code)"
                    " VALUES (:rid, :pid, :status, CAST(:plan AS json), 'fp', now() - make_interval(mins => :i),"
                    " :base, :size, :hard, :hsize, :err)"),
                    {"rid": render_id, "pid": project_id, "status": status, "plan": '[{"candidate_id": "x"}]',
                     "i": index, "base": f"projects/{project_id.hex}/renders/{render_id.hex}/final.mp4" if completed else None,
                     "size": 1234 if completed else None,
                     "hard": f"projects/{project_id.hex}/renders/{render_id.hex}/final-subtitled.mp4" if completed else None,
                     "hsize": 2345 if completed else None, "err": None if completed else "SYNTHETIC"})
        return project_id

    def test_upgrade_downgrade_reupgrade_preserves_history(self):
        heads = ScriptDirectory.from_config(self.config).get_heads()
        self.assertEqual(heads, [TARGET])
        command.upgrade(self.config, PREVIOUS)
        project_id = self.seed_history()
        before_counts, before_rows = self.counts(), self.legacy_fingerprint()
        self.assertEqual(before_counts["project_render_runs"], 6)
        self.assertFalse(set(COLUMNS) & set(self.columns()))
        self.assertIn("e3a1c9d27b45", self.persistent_startup() or "")   # new code refuses un-migrated DB

        command.upgrade(self.config, TARGET)
        self.assertEqual(self.scalar("SELECT version_num FROM alembic_version"), TARGET)
        self.assertIsNone(self.persistent_startup())
        columns = self.columns()
        for name in COLUMNS:
            self.assertTrue(columns[name]["nullable"])
            self.assertEqual(columns[name]["type"].length, 64)
        self.assertEqual(self.counts(), before_counts)
        self.assertEqual(self.legacy_fingerprint(), before_rows)
        self.assertEqual(self.scalar("SELECT count(*) FROM project_render_runs WHERE base_sha256 IS NOT NULL "
                                     "OR srt_sha256 IS NOT NULL OR hard_sha256 IS NOT NULL"), 0)  # no backfill
        self.assertEqual(self.scalar("SELECT count(*) FROM project_render_runs WHERE status = 'COMPLETED'"), 2)
        with self.engine.connect() as connection:
            checks = {item["name"] for item in inspect(connection).get_check_constraints("project_render_runs")}
        self.assertTrue({f"ck_project_render_runs_{name}" for name in COLUMNS} <= checks)
        for name in COLUMNS:
            for bad in ("A" * 64, "a" * 63, "a" * 65, "z" * 64, " " + "a" * 63):
                # 65 chars hits varchar(64) (DataError); the rest hit the CHECK (IntegrityError).
                with self.subTest(column=name, value=bad), self.assertRaises((IntegrityError, DataError)):
                    with self.engine.begin() as connection:
                        connection.execute(text(f"UPDATE project_render_runs SET {name} = :v "
                                                "WHERE status = 'COMPLETED'"), {"v": bad})
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE project_render_runs SET base_sha256 = :v WHERE render_id = ("
                                    "SELECT render_id FROM project_render_runs WHERE status = 'COMPLETED' "
                                    "ORDER BY render_id LIMIT 1)"), {"v": DIGEST})
        self.assertEqual(self.scalar("SELECT count(*) FROM project_render_runs WHERE base_sha256 = :v", v=DIGEST), 1)

        command.downgrade(self.config, PREVIOUS)
        self.assertEqual(self.scalar("SELECT version_num FROM alembic_version"), PREVIOUS)
        self.assertFalse(set(COLUMNS) & set(self.columns()))
        self.assertEqual(self.counts(), before_counts)
        self.assertEqual(self.legacy_fingerprint(), before_rows)   # recorded digest is the only loss

        command.upgrade(self.config, TARGET)
        self.assertEqual(self.counts(), before_counts)
        self.assertEqual(self.legacy_fingerprint(), before_rows)
        self.assertEqual(self.scalar("SELECT count(*) FROM project_render_runs WHERE base_sha256 IS NOT NULL"), 0,
                         "downgrade destroys digest evidence; reupgrade must not invent it")
        self.assertEqual(self.scalar("SELECT count(*) FROM projects WHERE id = :p", p=project_id), 1)
