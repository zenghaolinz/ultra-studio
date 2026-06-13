import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_document_assets import (
    build_asset_prompt_from_documents,
    is_attachment_asset_intent,
    is_project_document_asset_intent,
    run_attachment_asset_request,
    run_project_document_asset_request,
)


class ChatDocumentAssetsTests(unittest.IsolatedAsyncioTestCase):
    def test_detects_attachment_asset_intent(self) -> None:
        with patch("services.chat_document_assets.document_attachments", return_value=["requirements.pdf"]):
            self.assertEqual(is_attachment_asset_intent("根据附件生成一张图片", ["requirements.pdf"]), "image")
            self.assertEqual(is_attachment_asset_intent("生成一个3d模型", ["requirements.pdf"]), "3d")

    def test_detects_project_document_asset_intent(self) -> None:
        self.assertEqual(is_project_document_asset_intent("根据文档生成一张图片", "project"), "image")
        self.assertEqual(is_project_document_asset_intent("根据文档生成一个3d模型", "project"), "3d")
        self.assertIsNone(is_project_document_asset_intent("生成一张图片", None))

    async def test_build_asset_prompt_rejects_unrequested_human_prompt(self) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="portrait of a person"))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )
        )

        prompt = await build_asset_prompt_from_documents(
            "make image",
            ["[requirements]\nwhite cute dog with detailed product style " * 20],
            client,
            "model",
            "image",
        )

        self.assertIn("no humans", prompt)
        self.assertNotIn("portrait of a person", prompt)

    async def test_run_attachment_asset_request_generates_image_from_document_prompt(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="根据附件生成一张图片",
            image_paths=["requirements.pdf"],
        )
        with (
            patch("services.chat_document_assets.document_attachments", return_value=["requirements.pdf"]),
            patch("services.chat_document_assets.read_document_attachments", return_value=["[requirements]\nwhite cute dog"]),
            patch("services.chat_document_assets.memory_mgr.handle_generate_image") as generate,
        ):
            generate.return_value = {"status": "success", "image_path": "out.png"}

            result = await run_attachment_asset_request(req, object(), "model")

        self.assertEqual(result["tool"], "generate_image")
        self.assertEqual(result["result"]["image_path"], "out.png")
        self.assertIn("source_prompt", result["result"])

    async def test_run_project_document_asset_request_reports_missing_documents(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="根据文档生成一张图片",
            project_path="project",
        )
        with patch("services.chat_document_assets.project_document_paths", return_value=[]):
            result = await run_project_document_asset_request(req, object(), "model")

        self.assertEqual(result["tool"], "generate_image")
        self.assertEqual(result["result"]["status"], "error")
        self.assertIn("project", result["result"]["message"])


if __name__ == "__main__":
    unittest.main()
