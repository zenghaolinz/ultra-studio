import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services import generation_tasks


SCHEMA = """
CREATE TABLE generation_tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'success', 'error', 'cancelled')),
    conversation_id TEXT DEFAULT NULL,
    queue_position INTEGER DEFAULT NULL,
    prompt TEXT DEFAULT '',
    quality_mode TEXT DEFAULT '',
    input_paths TEXT DEFAULT '[]',
    output_paths TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT
);
"""


class GenerationTasksServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = await aiosqlite.connect(Path(self.temp_dir.name) / "tasks.db")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        self.get_db_patch = patch.object(generation_tasks, "get_db", AsyncMock(return_value=self.db))
        self.get_db_patch.start()

    async def asyncTearDown(self) -> None:
        self.get_db_patch.stop()
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_create_running_task_and_list_records(self) -> None:
        task_id = await generation_tasks.create_running_generation_task(
            "generate_image",
            "brass robot",
            "fast",
            ["input.png"],
            conversation_id="conv-1",
            queue_position=2,
        )

        records = await generation_tasks.list_generation_tasks(500)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], task_id)
        self.assertEqual(records[0]["status"], "running")
        self.assertEqual(records[0]["taskType"], "generate_image")
        self.assertEqual(records[0]["conversationId"], "conv-1")
        self.assertEqual(records[0]["queuePosition"], 2)
        self.assertEqual(records[0]["inputPaths"], ["input.png"])

    async def test_cancel_running_tasks_leaves_queued_tasks_alone(self) -> None:
        running_id = await generation_tasks.create_running_generation_task("generate_video")
        queued_id = await generation_tasks.create_generation_task("generate_image")

        await generation_tasks.cancel_running_generation_tasks()

        rows = await self.db.execute_fetchall("SELECT id, status FROM generation_tasks ORDER BY id")
        statuses = {row["id"]: row["status"] for row in rows}
        self.assertEqual(statuses[running_id], "cancelled")
        self.assertEqual(statuses[queued_id], "queued")

    async def test_mark_interrupted_generation_tasks_marks_running_as_error(self) -> None:
        running_id = await generation_tasks.create_running_generation_task("generate_video")
        queued_id = await generation_tasks.create_generation_task("generate_image")

        count = await generation_tasks.mark_interrupted_generation_tasks("restart")

        rows = await self.db.execute_fetchall(
            "SELECT id, status, error, completed_at FROM generation_tasks ORDER BY id"
        )
        tasks = {row["id"]: row for row in rows}
        self.assertEqual(count, 1)
        self.assertEqual(tasks[running_id]["status"], "error")
        self.assertEqual(tasks[running_id]["error"], "restart")
        self.assertTrue(tasks[running_id]["completed_at"])
        self.assertEqual(tasks[queued_id]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
