import sys
import tempfile
import unittest
from pathlib import Path

import aiosqlite

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from db import sqlite as sqlite_db
from services.agent_context import build_agent_context, infer_agent_capabilities


class AgentContextTests(unittest.IsolatedAsyncioTestCase):
    def test_capabilities_follow_request_and_artifact_kinds(self) -> None:
        self.assertEqual(infer_agent_capabilities("hello"), set())
        self.assertEqual(
            infer_agent_capabilities("read this", attachment_kinds={"document"}),
            {"files"},
        )
        self.assertEqual(
            infer_agent_capabilities("\u4fee\u6539\u4e0a\u9762\u7684\u56fe", resolved_kinds={"image"}),
            {"generation"},
        )
        self.assertEqual(infer_agent_capabilities("search the web"), {"web"})
        self.assertEqual(infer_agent_capabilities("create a Python project"), {"files"})

    async def test_context_is_conversation_scoped_and_excludes_global_memory(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            original_path = sqlite_db.DB_PATH
            sqlite_db.DB_PATH = str(db_path)
            try:
                await sqlite_db._migrate()
            finally:
                sqlite_db.DB_PATH = original_path
            db = await aiosqlite.connect(db_path)
            db.row_factory = aiosqlite.Row
            await db.executemany(
                "INSERT INTO conversations(id, title) VALUES (?, ?)",
                [("current", "current"), ("other", "other")],
            )
            await db.execute(
                "INSERT INTO persona(id, content) VALUES (1, 'GLOBAL PERSONA MUST NOT LEAK')"
            )
            await db.executemany(
                """
                INSERT INTO stm_entries(id, conversation_id, role, content, visible)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("old", "current", "assistant", "current conversation fact", 1),
                    ("hidden", "current", "system", "hidden memory payload", 0),
                    ("other", "other", "assistant", "other conversation secret", 1),
                    ("now", "current", "user", "current request", 1),
                ],
            )
            await db.commit()
            try:
                messages = await build_agent_context(
                    db,
                    conversation_id="current",
                    user_input="current request",
                    current_message_id="now",
                )
            finally:
                await db.close()

        rendered = "\n".join(str(message["content"]) for message in messages)
        self.assertIn("current conversation fact", rendered)
        self.assertNotIn("GLOBAL PERSONA MUST NOT LEAK", rendered)
        self.assertNotIn("hidden memory payload", rendered)
        self.assertNotIn("other conversation secret", rendered)
        self.assertEqual(
            [message for message in messages if message.get("content") == "current request"],
            [{"role": "user", "content": "current request"}],
        )

    async def test_context_renders_existing_attachment_paths_without_reading_contents(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            attachment = Path(temp_dir) / "requirements.pdf"
            attachment.write_bytes(b"secret document bytes")
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.execute(
                "CREATE TABLE stm_entries(id TEXT, conversation_id TEXT, role TEXT, content TEXT, visible INTEGER, created_at TEXT)"
            )
            try:
                messages = await build_agent_context(
                    db,
                    conversation_id="current",
                    user_input="read this file",
                    attachment_paths=[str(attachment)],
                )
            finally:
                await db.close()

        rendered = "\n".join(str(message["content"]) for message in messages)
        self.assertIn(str(attachment), rendered)
        self.assertNotIn("secret document bytes", rendered)


if __name__ == "__main__":
    unittest.main()
