import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
from fastapi import HTTPException


SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from routes import asset_3d, chat
from schemas import ConversationCreate


class ProjectRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = await aiosqlite.connect(Path(self.temp_dir.name) / "routes.db")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
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
        self.get_db_patch = patch.object(chat, "get_db", AsyncMock(return_value=self.db))
        self.get_db_patch.start()

    async def asyncTearDown(self) -> None:
        self.get_db_patch.stop()
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_delete_project_removes_legacy_conversations_and_messages(self) -> None:
        await self.db.execute("INSERT INTO projects (id) VALUES ('project-1')")
        await self.db.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'Chat', 'project-1', '', '')"
        )
        await self.db.execute(
            "INSERT INTO stm_entries VALUES ('message-1', 'conversation-1', 'user', 'hello', '')"
        )
        await self.db.commit()

        await chat.delete_project("project-1")

        conversations = await self.db.execute_fetchall("SELECT id FROM conversations")
        messages = await self.db.execute_fetchall("SELECT id FROM stm_entries")
        self.assertEqual(conversations, [])
        self.assertEqual(messages, [])

    async def test_create_conversation_rejects_deleted_project(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await chat.create_conversation(
                ConversationCreate(title="Orphan", project_id="missing-project")
            )

        self.assertEqual(ctx.exception.status_code, 404)


class GenerationCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_marks_task_when_comfyui_interrupt_is_unavailable(self) -> None:
        with patch.object(
            asset_3d,
            "_cancel_running_tasks",
            AsyncMock(),
        ) as cancel_tasks, patch("urllib.request.urlopen", side_effect=OSError("offline")):
            response = await asset_3d.cancel_generation()

        cancel_tasks.assert_awaited_once()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"interruptError", response.body)


if __name__ == "__main__":
    unittest.main()
