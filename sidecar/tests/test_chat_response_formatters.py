import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_response_formatters import (
    format_3d_response,
    format_command_tool_response,
    format_delete_tool_response,
    format_folder_summary_response,
    format_image_response,
    format_project_check_response,
    format_text_edit_response,
    format_video_response,
    format_write_many_files_response,
)


class ChatResponseFormatterTests(unittest.TestCase):
    def test_format_image_queued_response_includes_task_id(self) -> None:
        response = format_image_response("generate_image", {"status": "queued", "task_id": "task-1"})

        self.assertIn("图片生成任务已加入队列。", response)
        self.assertIn("任务 ID: `task-1`", response)

    def test_format_multiview_success_response_lists_views(self) -> None:
        response = format_image_response(
            "generate_multiview_images_from_image",
            {
                "status": "success",
                "frontPath": "front.png",
                "leftPath": "left.png",
                "backPath": "back.png",
            },
        )

        self.assertIn("三视图已生成。", response)
        self.assertIn("正面: `front.png`", response)
        self.assertIn("背面: `back.png`", response)

    def test_format_video_success_response_lists_path(self) -> None:
        response = format_video_response({"status": "success", "videoPath": "clip.mp4"})

        self.assertEqual(response, "视频生成已完成。\n\n视频: `clip.mp4`")

    def test_format_video_error_response_includes_reason(self) -> None:
        response = format_video_response({"status": "error", "message": "ComfyUI offline"})

        self.assertIn("视频任务失败。", response)
        self.assertIn("原因: ComfyUI offline", response)

    def test_format_3d_success_response_lists_model_and_preview(self) -> None:
        response = format_3d_response(
            "generate_3d_from_text",
            {"status": "success", "modelPath": "model.glb", "image2D": "preview.png"},
        )

        self.assertIn("model.glb", response)
        self.assertIn("preview.png", response)

    def test_format_command_response_includes_output(self) -> None:
        response = format_command_tool_response(
            {
                "ok": True,
                "command": "npm run check",
                "cwd": "E:/ultra/ultra-studio",
                "returncode": 0,
                "stdout": "ok",
            }
        )

        self.assertIn("命令执行成功：`npm run check`", response)
        self.assertIn("stdout:", response)

    def test_format_delete_response_returns_confirmation_message(self) -> None:
        response = format_delete_tool_response({"needs_confirmation": True, "message": "confirm"})

        self.assertEqual(response, "confirm")

    def test_format_text_edit_response_reports_replacements(self) -> None:
        response = format_text_edit_response(
            {"ok": True, "path": "C:/tmp/a.txt", "action": "replace", "replacements": 2}
        )

        self.assertIn("已修改文件：`C:/tmp/a.txt`", response)
        self.assertIn("替换次数：2", response)

    def test_format_write_many_files_response_reports_partial_errors(self) -> None:
        response = format_write_many_files_response(
            {
                "ok": False,
                "files": [{"path": "C:/tmp/a.txt"}],
                "errors": [{"path": "C:/tmp/b.exe", "error": "blocked"}],
            }
        )

        self.assertIn("C:/tmp/a.txt", response)
        self.assertIn("blocked", response)

    def test_format_project_check_response_includes_nested_commands(self) -> None:
        response = format_project_check_response(
            {
                "ok": False,
                "path": "E:/project",
                "results": [{"ok": False, "command": "npm test", "returncode": 1, "stderr": "failed"}],
            }
        )

        self.assertIn("项目检查失败：`E:/project`", response)
        self.assertIn("命令执行失败：`npm test`", response)


    def test_format_folder_summary_response_reports_path_or_resolution(self) -> None:
        response = format_folder_summary_response({"ok": True, "document_count": 2, "path": "C:/tmp/report.docx"})
        self.assertIn("2", response)
        self.assertIn("C:/tmp/report.docx", response)

        needs_path = format_folder_summary_response({"needs_path": True})
        self.assertIn("[PATH_RESOLUTION_REQUIRED]", needs_path)


if __name__ == "__main__":
    unittest.main()
