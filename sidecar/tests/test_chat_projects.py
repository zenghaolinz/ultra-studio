import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_projects import project_path_for_request, with_project_context
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


if __name__ == "__main__":
    unittest.main()
