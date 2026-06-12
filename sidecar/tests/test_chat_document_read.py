import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_document_read import run_project_document_read


class ChatDocumentReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_project_document_read_returns_none_without_documents(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="summarize", project_path="project")
        with (
            patch("services.chat_document_read.document_attachments", return_value=[]),
            patch("services.chat_document_read.project_document_paths", return_value=[]),
        ):
            result = await run_project_document_read(req, object(), "model")

        self.assertIsNone(result)

    async def test_run_project_document_read_uses_project_documents(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="summarize", project_path="project")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="summary"))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )
        )
        with (
            patch("services.chat_document_read.document_attachments", return_value=[]),
            patch("services.chat_document_read.project_document_paths", return_value=["project/readme.md"]),
            patch("services.chat_document_read.read_document_attachments", return_value=["content"]),
        ):
            result = await run_project_document_read(req, client, "model")

        self.assertEqual(result, "summary")
        client.chat.completions.create.assert_awaited_once()
        kwargs = client.chat.completions.create.await_args.kwargs
        self.assertEqual(kwargs["model"], "model")
        self.assertIn("project/readme.md", kwargs["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
