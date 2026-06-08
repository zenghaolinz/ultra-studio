import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_projects import project_path_for_request, run_open_folder_request, with_project_context
from schemas import ChatRequest


class ChatProjectsTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_path_for_request_prefers_explicit_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            req = ChatRequest(conversation_id="conversation", content="hi", project_path=temp_dir)

            self.assertEqual(await project_path_for_request(req), str(Path(temp_dir).resolve()))

    def test_with_project_context_adds_project_rules(self) -> None:
        response = with_project_context("read files", "E:/project")

        self.assertIn("read files", response)
        self.assertIn("E:/project", response)
        self.assertIn("当前项目文件夹", response)

    def test_run_open_folder_request_ignores_unrelated_requests(self) -> None:
        req = ChatRequest(conversation_id="conversation", content="hello")

        self.assertIsNone(run_open_folder_request(req))

    def test_run_open_folder_request_reports_missing_path(self) -> None:
        req = ChatRequest(conversation_id="conversation", content="打开这个文件夹")

        result = run_open_folder_request(req)

        self.assertFalse(result["ok"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
