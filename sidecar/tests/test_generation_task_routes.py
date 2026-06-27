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

from routes import generation_tasks as generation_routes
from services import generation_tasks


SCHEMA = """
CREATE TABLE generation_tasks (
    id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'success', 'error', 'cancelled')),
    conversation_id TEXT, queue_position INTEGER, prompt TEXT DEFAULT '', quality_mode TEXT DEFAULT '',
    input_paths TEXT DEFAULT '[]', output_paths TEXT DEFAULT '{}', error TEXT DEFAULT '',
    error_code TEXT DEFAULT '', request_payload TEXT DEFAULT '{}', retry_of_task_id TEXT,
    created_at TEXT, updated_at TEXT, completed_at TEXT
);
"""


class GenerationTaskRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = await aiosqlite.connect(Path(self.temp_dir.name) / "routes.db")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        self.get_db_patch = patch.object(
            generation_tasks, "get_db", AsyncMock(return_value=self.db)
        )
        self.get_db_patch.start()

    async def asyncTearDown(self) -> None:
        self.get_db_patch.stop()
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_cancel_missing_task_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await generation_routes.cancel_task("missing")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_retry_creates_linked_queued_task(self) -> None:
        original_id = await generation_tasks.create_generation_task(
            "generate_image",
            "robot",
            request_payload={"prompt": "robot"},
        )
        await generation_tasks.update_generation_task(original_id, "error", error="offline")

        with patch.object(generation_routes, "schedule_generation_task") as schedule:
            retried = await generation_routes.retry_task(original_id)

        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["retryOfTaskId"], original_id)
        self.assertEqual(retried["requestPayload"], {"prompt": "robot"})
        schedule.assert_called_once_with(retried)

    async def test_retry_without_payload_returns_422(self) -> None:
        task_id = await generation_tasks.create_generation_task("legacy")
        await generation_tasks.update_generation_task(task_id, "error", error="failed")

        with self.assertRaises(HTTPException) as ctx:
            await generation_routes.retry_task(task_id)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "retry_payload_missing")

    async def test_event_stream_uses_sse_media_type(self) -> None:
        response = await generation_routes.generation_task_events()
        self.assertEqual(response.media_type, "text/event-stream")


if __name__ == "__main__":
    unittest.main()
