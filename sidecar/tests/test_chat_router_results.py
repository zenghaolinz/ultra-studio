import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_router_results import format_router_result, inject_router_context


class ChatRouterResultsTests(unittest.IsolatedAsyncioTestCase):
    def test_format_router_result_returns_direct_text(self) -> None:
        self.assertIsNone(format_router_result(None))
        self.assertEqual(format_router_result("plain answer"), "plain answer")

    def test_format_router_result_dispatches_generation_tools(self) -> None:
        with (
            patch("services.chat_router_results.format_image_response") as image,
            patch("services.chat_router_results.format_video_response") as video,
            patch("services.chat_router_results.format_3d_response") as model,
        ):
            image.return_value = "image response"
            video.return_value = "video response"
            model.return_value = "3d response"

            self.assertEqual(
                format_router_result({"tool": "generate_image", "result": {"image_path": "out.png"}}),
                "image response",
            )
            self.assertEqual(
                format_router_result({"tool": "generate_video", "result": {"video_path": "out.mp4"}}),
                "video response",
            )
            self.assertEqual(
                format_router_result({"tool": "generate_3d_from_text", "result": {"model_path": "out.glb"}}),
                "3d response",
            )

        image.assert_called_once()
        video.assert_called_once()
        model.assert_called_once()

    def test_format_router_result_dispatches_file_and_summary_results(self) -> None:
        with (
            patch("services.chat_router_results.format_text_file_create_response") as text_file,
            patch("services.chat_router_results.format_docx_create_response") as docx,
            patch("services.chat_router_results.format_folder_summary_response") as folder_summary,
        ):
            text_file.return_value = "text file"
            docx.return_value = "docx"
            folder_summary.return_value = "summary"

            self.assertEqual(
                format_router_result({"tool": "create_text_file", "result": {"path": "a.txt"}}),
                "text file",
            )
            self.assertEqual(format_router_result({"ok": True, "path": "a.docx"}), "docx")
            self.assertEqual(format_router_result({"document_count": 2}), "summary")

    async def test_inject_router_context_dispatches_media_results(self) -> None:
        with (
            patch("services.chat_router_results.inject_artifacts_from_result", new_callable=AsyncMock) as artifacts,
            patch("services.chat_router_results.inject_image_context", new_callable=AsyncMock) as image,
            patch("services.chat_router_results.inject_3d_context", new_callable=AsyncMock) as model,
        ):
            await inject_router_context("conversation-1", {"tool": "generate_image", "result": {"image_path": "out.png"}})
            await inject_router_context(
                "conversation-1",
                {"tool": "generate_3d_from_text", "result": {"model_path": "out.glb"}},
            )
            await inject_router_context("conversation-1", "plain text")

        self.assertEqual(artifacts.await_count, 2)
        image.assert_awaited_once_with("conversation-1", {"image_path": "out.png"})
        model.assert_awaited_once_with("conversation-1", {"model_path": "out.glb"})


if __name__ == "__main__":
    unittest.main()
