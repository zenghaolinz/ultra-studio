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
from services.generation_events import generation_event_broker


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
    error_code TEXT DEFAULT '',
    request_payload TEXT DEFAULT '{}',
    retry_of_task_id TEXT DEFAULT NULL,
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

    async def test_create_task_persists_retry_request_and_parent_link(self) -> None:
        task_id = await generation_tasks.create_generation_task(
            "generate_image",
            "brass robot",
            request_payload={"prompt": "brass robot", "quality": "fast"},
            retry_of_task_id="original-task",
        )

        records = await generation_tasks.list_generation_tasks()

        self.assertEqual(records[0]["id"], task_id)
        self.assertEqual(
            records[0]["requestPayload"],
            {"prompt": "brass robot", "quality": "fast"},
        )
        self.assertEqual(records[0]["retryOfTaskId"], "original-task")
        self.assertEqual(records[0]["errorCode"], "")

    async def test_committed_task_creation_publishes_snapshot(self) -> None:
        listener_id, queue = generation_event_broker.subscribe()
        self.addCleanup(generation_event_broker.unsubscribe, listener_id)

        task_id = await generation_tasks.create_generation_task("generate_image")

        event = await queue.get()
        self.assertEqual(event["type"], "task_updated")
        self.assertEqual(event["task"]["id"], task_id)
        self.assertEqual(event["task"]["status"], "queued")

    async def test_cancel_running_tasks_leaves_queued_tasks_alone(self) -> None:
        running_id = await generation_tasks.create_running_generation_task("generate_video")
        queued_id = await generation_tasks.create_generation_task("generate_image")

        await generation_tasks.cancel_running_generation_tasks()

        rows = await self.db.execute_fetchall("SELECT id, status FROM generation_tasks ORDER BY id")
        statuses = {row["id"]: row["status"] for row in rows}
        self.assertEqual(statuses[running_id], "cancelled")
        self.assertEqual(statuses[queued_id], "queued")

    async def test_cancel_generation_task_only_cancels_requested_task(self) -> None:
        first_id = await generation_tasks.create_running_generation_task("generate_video")
        second_id = await generation_tasks.create_running_generation_task("generate_image")

        cancelled = await generation_tasks.cancel_generation_task(first_id)

        self.assertEqual(cancelled["status"], "cancelled")
        untouched = await generation_tasks.get_generation_task(second_id)
        self.assertEqual(untouched["status"], "running")

    async def test_late_worker_result_cannot_overwrite_cancelled_task(self) -> None:
        task_id = await generation_tasks.create_running_generation_task("generate_video")
        await generation_tasks.cancel_generation_task(task_id)

        changed = await generation_tasks.update_generation_task(
            task_id,
            "success",
            {"videoPath": "late.mp4"},
        )

        self.assertFalse(changed)
        task = await generation_tasks.get_generation_task(task_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["outputPaths"], {})

    async def test_claimed_retry_reuses_queued_task_id(self) -> None:
        task_id = await generation_tasks.create_generation_task(
            "generate_image", request_payload={"prompt": "robot"}
        )

        with generation_tasks.claim_generation_task(task_id):
            claimed_id = await generation_tasks.create_running_generation_task(
                "generate_image", "robot"
            )

        self.assertEqual(claimed_id, task_id)
        task = await generation_tasks.get_generation_task(task_id)
        self.assertEqual(task["status"], "running")
        records = await generation_tasks.list_generation_tasks()
        self.assertEqual(len(records), 1)

    async def test_mark_interrupted_generation_tasks_marks_running_as_error(self) -> None:
        running_id = await generation_tasks.create_running_generation_task("generate_video")
        queued_id = await generation_tasks.create_generation_task("generate_image")

        count = await generation_tasks.mark_interrupted_generation_tasks("restart")

        rows = await self.db.execute_fetchall(
            "SELECT id, status, error, completed_at FROM generation_tasks ORDER BY id"
        )
        tasks = {row["id"]: row for row in rows}
        self.assertEqual(count, 2)
        self.assertEqual(tasks[running_id]["status"], "error")
        self.assertEqual(tasks[running_id]["error"], "restart")
        recovered = await generation_tasks.get_generation_task(running_id)
        self.assertEqual(recovered["errorCode"], "sidecar_restarted")
        self.assertTrue(tasks[running_id]["completed_at"])
        self.assertEqual(tasks[queued_id]["status"], "error")
        queued = await generation_tasks.get_generation_task(queued_id)
        self.assertEqual(queued["errorCode"], "sidecar_restarted_before_start")


if __name__ == "__main__":
    unittest.main()
