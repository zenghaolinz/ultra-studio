import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_router_context import build_router_context, direct_agent_trace_block


class ChatRouterContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_router_context_collects_request_and_project_state(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="make asset",
            image_paths=["input.png", "requirements.pdf"],
            project_path="project",
            permission_mode="auto",
        )
        with (
            patch("services.chat_router_context.find_latest_edit_source_image") as latest_image,
            patch("services.chat_router_context.find_latest_multiview_paths") as latest_multiview,
            patch("services.chat_router_context.project_document_paths") as project_docs,
            patch("services.chat_router_context.project_image_paths") as project_images,
            patch("services.chat_router_context.project_file_candidates") as project_files,
        ):
            latest_image.return_value = "latest.png"
            latest_multiview.return_value = {"front": "front.png"}
            project_docs.return_value = [f"doc-{i}.pdf" for i in range(8)]
            project_images.return_value = [f"image-{i}.png" for i in range(8)]
            project_files.return_value = [{"path": f"file-{i}.txt"} for i in range(25)]

            context = await build_router_context(req, {"supports_vision": True})

        self.assertEqual(context["attached_images"], ["input.png"])
        self.assertEqual(context["attached_documents"], ["requirements.pdf"])
        self.assertEqual(context["project_document_candidates"], [f"doc-{i}.pdf" for i in range(5)])
        self.assertEqual(context["project_image_candidates"], [f"image-{i}.png" for i in range(5)])
        self.assertEqual(len(context["project_file_candidates"]), 20)
        self.assertTrue(context["has_latest_active_image"])
        self.assertTrue(context["has_latest_multiview"])

    async def test_direct_agent_trace_block_formats_trace(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="make asset",
            image_paths=[],
            vision_enabled=True,
        )
        with (
            patch("services.chat_router_context.find_latest_edit_source_image") as latest_image,
            patch("services.chat_router_context.find_latest_multiview_paths") as latest_multiview,
        ):
            latest_image.return_value = None
            latest_multiview.return_value = {}

            trace = await direct_agent_trace_block(
                req,
                ("openai", "gpt-4o"),
                "generate_image",
                "generate_image",
                {"image_path": "out.png"},
                reason="direct intent",
            )

        self.assertIn("[AGENT_TRACE]", trace)
        self.assertIn("generate_image", trace)
        self.assertIn("out.png", trace)


if __name__ == "__main__":
    unittest.main()
