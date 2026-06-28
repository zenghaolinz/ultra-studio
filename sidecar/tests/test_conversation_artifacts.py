import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from db import sqlite as sqlite_db
from services.conversation_artifacts import list_artifacts, upsert_artifact


class ConversationArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_creates_artifact_table_with_conversation_cascade(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with patch.object(sqlite_db, "DB_PATH", str(db_path)):
                await sqlite_db._migrate()

            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute(
                    "PRAGMA table_info(conversation_artifacts)"
                )}
                foreign_keys = list(conn.execute(
                    "PRAGMA foreign_key_list(conversation_artifacts)"
                ))

            self.assertTrue({
                "id", "conversation_id", "message_id", "generation_task_id",
                "kind", "source", "path", "prompt", "status", "sequence",
            }.issubset(columns))
            self.assertTrue(any(row[2] == "conversations" and row[6] == "CASCADE" for row in foreign_keys))

    async def test_upsert_is_idempotent_and_preserves_source_order(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with patch.object(sqlite_db, "DB_PATH", str(db_path)):
                await sqlite_db._migrate()
            db = await aiosqlite.connect(db_path)
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(
                "INSERT INTO conversations(id, title) VALUES (?, ?)",
                ("conversation-1", "test"),
            )
            await db.commit()
            try:
                first = await upsert_artifact(
                    "conversation-1", kind="image", source="uploaded",
                    path="C:/images/upload.png", message_id="message-1", db=db,
                )
                duplicate = await upsert_artifact(
                    "conversation-1", kind="image", source="uploaded",
                    path="C:/images/upload.png", message_id="message-1", db=db,
                )
                generated = await upsert_artifact(
                    "conversation-1", kind="image", source="generated",
                    path="C:/images/generated.png", generation_task_id="task-1", db=db,
                )
                artifacts = await list_artifacts("conversation-1", db=db)
            finally:
                await db.close()

            self.assertEqual(first["id"], duplicate["id"])
            self.assertEqual([item["sequence"] for item in artifacts], [1, 2])
            self.assertEqual([item["source"] for item in artifacts], ["uploaded", "generated"])
            self.assertEqual(generated["generationTaskId"], "task-1")

    async def test_deleting_conversation_cascades_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with patch.object(sqlite_db, "DB_PATH", str(db_path)):
                await sqlite_db._migrate()
            db = await aiosqlite.connect(db_path)
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("INSERT INTO conversations(id, title) VALUES ('c1', 'test')")
            await db.commit()
            try:
                await upsert_artifact(
                    "c1", kind="image", source="uploaded", path="C:/a.png", db=db
                )
                await db.execute("DELETE FROM conversations WHERE id = 'c1'")
                await db.commit()
                rows = await db.execute_fetchall("SELECT id FROM conversation_artifacts")
            finally:
                await db.close()

            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
