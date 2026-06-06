import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from memory import manager as memory_mgr
from routes import mcp
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


class McpAndVideoTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_lists_generate_video_tool(self) -> None:
        response = await mcp.mcp_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("generate_video", names)

    def test_generate_video_returns_queued_task_without_waiting_for_comfyui(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "tasks.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()

            with patch.object(generation_tasks, "DB_PATH", str(db_path)), patch.object(
                memory_mgr.threading,
                "Thread",
            ) as thread_cls, patch(
                "services.generation_runtime.gpu_memory_state",
                return_value={"available": False, "free_mb": None, "total_mb": None, "low_memory": False},
            ):
                thread_cls.return_value.start.return_value = None
                result = memory_mgr.handle_generate_video("orbiting product shot", conversation_id="conv-1")

            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["taskType"], "generate_video")
            self.assertTrue(result["task_id"])
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT status, task_type, conversation_id FROM generation_tasks").fetchone()
            self.assertEqual(row, ("queued", "generate_video", "conv-1"))

    def test_generate_image_returns_queued_task_without_waiting_for_comfyui(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "tasks.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()

            with patch.object(generation_tasks, "DB_PATH", str(db_path)), patch.object(
                memory_mgr.threading,
                "Thread",
            ) as thread_cls, patch(
                "services.generation_runtime.gpu_memory_state",
                return_value={"available": False, "free_mb": None, "total_mb": None, "low_memory": False},
            ):
                thread_cls.return_value.start.return_value = None
                result = memory_mgr.handle_generate_image("small brass robot", "fast", conversation_id="conv-2")

            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["taskType"], "generate_image")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT status, task_type, prompt, conversation_id FROM generation_tasks").fetchone()
            self.assertEqual(row, ("queued", "generate_image", "small brass robot", "conv-2"))

    def test_generate_3d_text_returns_queued_task_without_waiting_for_comfyui(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "tasks.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()

            with patch.object(generation_tasks, "DB_PATH", str(db_path)), patch.object(
                memory_mgr.threading,
                "Thread",
            ) as thread_cls, patch(
                "services.generation_runtime.gpu_memory_state",
                return_value={"available": False, "free_mb": None, "total_mb": None, "low_memory": False},
            ):
                thread_cls.return_value.start.return_value = None
                result = memory_mgr.handle_generate_3d_from_text("ceramic cup", "quality", conversation_id="conv-3")

            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["taskType"], "text_to_3d")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT status, task_type, quality_mode, conversation_id FROM generation_tasks").fetchone()
            self.assertEqual(row, ("queued", "text_to_3d", "quality", "conv-3"))


if __name__ == "__main__":
    unittest.main()
