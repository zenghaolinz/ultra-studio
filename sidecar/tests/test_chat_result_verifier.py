import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_result_verifier import verify_routed_result, verify_tool_result


class ChatResultVerifierTests(unittest.TestCase):
    def test_accepts_written_files_that_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "note.txt"
            path.write_text("hello", encoding="utf-8")

            result = verify_tool_result("write_many_files", {"ok": True, "files": [{"path": str(path)}]})

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "accepted")

    def test_rejects_written_files_that_do_not_exist(self) -> None:
        result = verify_tool_result("write_many_files", {"ok": True, "files": [{"path": "C:/missing/nope.txt"}]})

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "failed")
        self.assertIn("missing", result.reason)

    def test_marks_text_edit_needs_read_as_retryable(self) -> None:
        result = verify_tool_result(
            "edit_text_file",
            {"ok": False, "needs_read": True, "path": "C:/tmp/a.txt", "error": "must read first"},
        )

        self.assertTrue(result.retryable)

    def test_accepts_queued_generation_task_as_pending(self) -> None:
        result = verify_tool_result("generate_image", {"status": "queued", "task_id": "task-1"})

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "pending")

    def test_rejects_success_media_without_output_path(self) -> None:
        result = verify_tool_result("generate_image", {"status": "success"})

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "failed")

    def test_verifies_routed_result_by_tool_payload(self) -> None:
        result = verify_routed_result({"tool": "generate_video", "result": {"status": "queued", "taskId": "video-1"}})

        self.assertEqual(result.status, "pending")


if __name__ == "__main__":
    unittest.main()
