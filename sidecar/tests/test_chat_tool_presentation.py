import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_tool_presentation import build_tool_result_presentation


class ChatToolPresentationTests(unittest.TestCase):
    def test_prefers_3d_result_over_image_result(self) -> None:
        presentation = build_tool_result_presentation(
            "生成 3D",
            three_d_result={"tool": "generate_3d_from_text", "result": {"status": "success", "model_path": "x.glb"}},
            multiview_image_result=None,
            generated_image_result={"tool": "generate_image", "result": {"status": "queued", "task_id": "img"}},
            generated_video_result=None,
            delete_result=None,
            project_check_result=None,
            command_result=None,
            edit_text_result=None,
            write_many_result=None,
        )

        self.assertIsNotNone(presentation)
        self.assertEqual(presentation.trace_group, "generate_3d_image")
        self.assertEqual(presentation.trace_tool, "generate_3d_from_text")
        self.assertTrue(presentation.include_image_attachments)

    def test_delete_confirmation_appends_continuation(self) -> None:
        delete_result = {
            "tool": "delete_file",
            "result": {
                "needs_confirmation": True,
                "message": "[CONFIRM_DELETE_REQUIRED]Confirm deletion?[/CONFIRM_DELETE_REQUIRED]",
            },
        }

        presentation = build_tool_result_presentation(
            "delete a.txt then: create b.txt",
            three_d_result=None,
            multiview_image_result=None,
            generated_image_result=None,
            generated_video_result=None,
            delete_result=delete_result,
            project_check_result=None,
            command_result=None,
            edit_text_result=None,
            write_many_result=None,
        )

        self.assertIsNotNone(presentation)
        self.assertEqual(presentation.trace_group, "general_tools")
        self.assertIn("create b.txt", delete_result["result"]["message"])

    def test_delete_request_without_target_returns_message_without_trace(self) -> None:
        presentation = build_tool_result_presentation(
            "删除这个文件",
            three_d_result=None,
            multiview_image_result=None,
            generated_image_result=None,
            generated_video_result=None,
            delete_result=None,
            project_check_result=None,
            command_result=None,
            edit_text_result=None,
            write_many_result=None,
        )

        self.assertIsNotNone(presentation)
        self.assertIn("没有定位到可删除目标", presentation.text)
        self.assertIsNone(presentation.trace_group)


if __name__ == "__main__":
    unittest.main()
