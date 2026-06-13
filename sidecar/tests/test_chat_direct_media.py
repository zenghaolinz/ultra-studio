import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_direct_media import (
    run_direct_3d_request,
    run_direct_image_request,
    run_previous_3d_modification,
)


class ChatDirectMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_direct_image_request_generates_image(self) -> None:
        with patch("services.chat_direct_media.memory_mgr.handle_generate_image") as generate:
            generate.return_value = {"status": "success", "image_path": "out.png"}

            result = await run_direct_image_request("\u751f\u6210\u4e00\u5f20\u72d7\u7684\u56fe\u7247", None)

        self.assertEqual(result, {"tool": "generate_image", "result": generate.return_value})
        generate.assert_called_once_with("\u751f\u6210\u4e00\u5f20\u72d7\u7684\u56fe\u7247", "fast")

    async def test_run_direct_image_request_treats_correction_as_previous_edit(self) -> None:
        with (
            patch("services.chat_direct_media.find_latest_edit_source_image") as latest,
            patch("services.chat_direct_media.memory_mgr.handle_modify_image") as modify,
            patch("services.chat_direct_media.memory_mgr.handle_generate_image") as generate,
        ):
            latest.return_value = "source.png"
            modify.return_value = {"status": "success", "improved_image_path": "out.png"}

            result = await run_direct_image_request(
                "\u6211\u60f3\u8981\u7684\u662f\u4e00\u53ea\u767d\u8272\u7684\u72d7",
                None,
                "conversation-1",
            )

        self.assertEqual(result, {"tool": "edit_image", "result": modify.return_value})
        modify.assert_called_once_with("source.png", "\u6211\u60f3\u8981\u7684\u662f\u4e00\u53ea\u767d\u8272\u7684\u72d7")
        generate.assert_not_called()

    async def test_run_direct_image_request_edits_first_referenced_image(self) -> None:
        with (
            patch("services.chat_direct_media.find_latest_edit_source_image") as latest,
            patch("services.chat_direct_media.memory_mgr.handle_modify_image") as modify,
        ):
            latest.return_value = "source.png"
            modify.return_value = {"status": "success", "improved_image_path": "out.png"}

            result = await run_direct_image_request(
                "\u6211\u662f\u8981\u7b2c\u4e00\u53ea\u72d7\u53d8\u767d\u8272",
                None,
                "conversation-1",
            )

        self.assertEqual(result["tool"], "edit_image")
        modify.assert_called_once()

    async def test_run_direct_image_request_does_not_project_fallback_for_correction_without_active_image(self) -> None:
        with (
            patch("services.chat_direct_media.find_latest_edit_source_image") as latest,
            patch("services.chat_direct_media.project_image_paths") as project_images,
            patch("services.chat_direct_media.memory_mgr.handle_modify_image") as modify,
        ):
            latest.return_value = None
            project_images.return_value = ["project.png"]

            result = await run_direct_image_request(
                "\u6211\u60f3\u8981\u7684\u662f\u4e00\u53ea\u767d\u8272\u7684\u72d7",
                None,
                "conversation-1",
                "project",
            )

        self.assertIsNone(result)
        project_images.assert_not_called()
        modify.assert_not_called()

    async def test_run_direct_image_request_allows_project_fallback_for_explicit_reference(self) -> None:
        with (
            patch("services.chat_direct_media.find_latest_edit_source_image") as latest,
            patch("services.chat_direct_media.project_image_paths") as project_images,
            patch("services.chat_direct_media.memory_mgr.handle_modify_image") as modify,
        ):
            latest.return_value = None
            project_images.return_value = ["project.png"]
            modify.return_value = {"status": "success", "improved_image_path": "out.png"}

            result = await run_direct_image_request(
                "\u6211\u662f\u8981\u7b2c\u4e00\u53ea\u72d7\u53d8\u767d\u8272",
                None,
                "conversation-1",
                "project",
            )

        self.assertEqual(result["tool"], "edit_image")
        project_images.assert_called_once()
        modify.assert_called_once_with("project.png", "\u6211\u662f\u8981\u7b2c\u4e00\u53ea\u72d7\u53d8\u767d\u8272")

    async def test_run_direct_3d_request_generates_from_text(self) -> None:
        with patch("services.chat_direct_media.memory_mgr.handle_generate_3d_from_text") as generate:
            generate.return_value = {"status": "success", "model_path": "out.glb"}

            result = await run_direct_3d_request("\u751f\u6210\u4e00\u4e2a3d\u6a21\u578b", None)

        self.assertEqual(result, {"tool": "generate_3d_from_text", "result": generate.return_value})
        generate.assert_called_once_with("\u751f\u6210\u4e00\u4e2a3d\u6a21\u578b", "fast")

    async def test_previous_3d_modification_reports_missing_source(self) -> None:
        with patch("services.chat_direct_media.find_latest_edit_source_image") as latest:
            latest.return_value = None

            result = await run_previous_3d_modification(
                "conversation-1",
                "\u628a\u521a\u624d\u8fd9\u4e2a\u6539\u6210\u767d\u8272",
                None,
            )

        self.assertEqual(result["tool"], "modify_previous_3d")
        self.assertEqual(result["result"]["status"], "error")
        self.assertIn("No previous Flux source image", result["result"]["message"])

    async def test_previous_3d_modification_modifies_source_then_regenerates(self) -> None:
        with (
            patch("services.chat_direct_media.find_latest_edit_source_image") as latest,
            patch("services.chat_direct_media.memory_mgr.handle_modify_image") as modify,
            patch("services.chat_direct_media.memory_mgr.handle_generate_3d_from_image") as generate,
        ):
            latest.return_value = "source.png"
            modify.return_value = {"status": "success", "improved_image_path": "improved.png"}
            generate.return_value = {"status": "success", "model_path": "model.glb"}

            result = await run_previous_3d_modification(
                "conversation-1",
                "\u628a\u521a\u624d\u8fd9\u4e2a\u6539\u6210\u767d\u8272",
                None,
            )

        modify.assert_called_once_with("source.png", "\u628a\u521a\u624d\u8fd9\u4e2a\u6539\u6210\u767d\u8272", 0.5)
        generate.assert_called_once_with("improved.png")
        self.assertEqual(result["tool"], "modify_previous_3d")
        self.assertEqual(result["result"]["model_path"], "model.glb")
        self.assertEqual(result["result"]["image_2d"], "improved.png")
        self.assertEqual(result["result"]["source_image"], "source.png")


if __name__ == "__main__":
    unittest.main()
