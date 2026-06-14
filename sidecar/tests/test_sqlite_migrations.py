import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from db import sqlite as sqlite_db


class SqliteMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_context_window_migration_adds_column(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        project_id TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE stm_entries (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT,
                        visible INTEGER DEFAULT 1
                    );
                    CREATE TABLE model_configs (
                        id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        api_key TEXT DEFAULT '',
                        base_url TEXT DEFAULT '',
                        is_default INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                conn.commit()

            with patch.object(sqlite_db, "DB_PATH", str(db_path)):
                await sqlite_db._migrate()

            with sqlite3.connect(db_path) as conn:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(model_configs)")]
            self.assertIn("context_window", columns)

    async def test_failed_schema_migration_rolls_back_prior_steps(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        project_id TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE stm_entries (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT
                    );
                    """
                )
                conn.commit()

            failing_visible_migration = [
                "ALTER TABLE stm_entries ADD COLUMN visible INTEGER DEFAULT 1",
                "ALTER TABLE missing_table ADD COLUMN impossible TEXT",
            ]
            with patch.object(sqlite_db, "DB_PATH", str(db_path)), patch.object(
                sqlite_db,
                "MIGRATIONS_VISIBLE",
                failing_visible_migration,
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    await sqlite_db._migrate()

            with sqlite3.connect(db_path) as conn:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(stm_entries)")]
            self.assertNotIn("visible", columns)


if __name__ == "__main__":
    unittest.main()
