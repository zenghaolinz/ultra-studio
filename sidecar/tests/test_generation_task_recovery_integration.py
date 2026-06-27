import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from db import sqlite as sqlite_db
from services import generation_tasks


class GenerationTaskRecoveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await sqlite_db.close_db()

    async def test_init_db_schema_supports_interrupted_task_recovery(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            with patch.object(sqlite_db, "DB_PATH", str(db_path)):
                await sqlite_db.init_db()
                running_id = await generation_tasks.create_running_generation_task("generate_video")
                queued_id = await generation_tasks.create_generation_task("generate_image")

                count = await generation_tasks.mark_interrupted_generation_tasks("restart")
                records = await generation_tasks.list_generation_tasks(10)

            by_id = {record["id"]: record for record in records}
            self.assertEqual(count, 2)
            self.assertEqual(by_id[running_id]["status"], "error")
            self.assertEqual(by_id[running_id]["error"], "restart")
            self.assertTrue(by_id[running_id]["completedAt"])
            self.assertEqual(by_id[queued_id]["status"], "error")
            self.assertEqual(by_id[queued_id]["errorCode"], "sidecar_restarted_before_start")


if __name__ == "__main__":
    unittest.main()
