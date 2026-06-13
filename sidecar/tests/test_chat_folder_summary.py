import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_folder_summary import summarize_folder_documents


class ChatFolderSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_folder_documents_requests_path_when_missing(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="总结这个文件夹并生成docx")
        with (
            patch("services.chat_folder_summary.is_folder_summary_to_docx_intent", return_value=True),
            patch("services.chat_folder_summary.format_path_resolution_card", return_value="need path"),
            patch("services.chat_folder_summary.nearby_path_suggestions", return_value=[]),
        ):
            result = await summarize_folder_documents(req, object(), "model")

        self.assertTrue(result["needs_path"])
        self.assertEqual(result["message"], "need path")

    async def test_summarize_folder_documents_creates_docx_from_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            doc = folder / "a.txt"
            doc.write_text("hello", encoding="utf-8")
            req = ChatRequest(
                conversation_id="conversation-1",
                content="总结这个文件夹并生成docx",
                project_path=str(folder),
            )
            response = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"title":"Summary","paragraphs":["One","Two"]}')
                    )
                ]
            )
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=AsyncMock(return_value=response))
                )
            )

            with (
                patch("services.chat_folder_summary.is_folder_summary_to_docx_intent", return_value=True),
                patch("services.chat_folder_summary.folder_documents", return_value=[doc]),
                patch("services.chat_folder_summary.memory_mgr.handle_read_document") as read_doc,
                patch("services.chat_folder_summary.memory_mgr.handle_create_docx_document") as create_docx,
            ):
                read_doc.return_value = {"ok": True, "name": "a.txt", "path": str(doc), "content": "hello"}
                create_docx.return_value = {"ok": True, "path": str(folder / "资料整理报告.docx")}

                result = await summarize_folder_documents(req, client, "model")

        client.chat.completions.create.assert_awaited_once()
        create_docx.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["documents"], [str(doc)])
        self.assertEqual(result["source_folder"], str(folder))


if __name__ == "__main__":
    unittest.main()
