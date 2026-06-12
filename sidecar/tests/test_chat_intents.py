import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_intents import (
    is_3d_intent,
    is_folder_summary_to_docx_intent,
    is_image_3d_intent,
    is_image_edit_intent,
    is_image_generation_intent,
    is_memory_intent,
    is_modify_previous_3d_intent,
    is_open_folder_intent,
    is_previous_image_edit_intent,
    is_text_3d_intent,
    requests_multiview_followup,
)


class ChatIntentsTests(unittest.TestCase):
    def test_detects_folder_summary_to_docx_intent(self) -> None:
        self.assertTrue(is_folder_summary_to_docx_intent("读取这个 folder 并生成 docx 报告"))
        self.assertFalse(is_folder_summary_to_docx_intent("打开这个 folder"))

    def test_detects_open_folder_intent(self) -> None:
        self.assertTrue(is_open_folder_intent("open project folder"))
        self.assertTrue(is_open_folder_intent("定位这个目录"))
        self.assertFalse(is_open_folder_intent("总结这个目录"))

    def test_detects_memory_and_multiview_followup_intents(self) -> None:
        self.assertTrue(is_memory_intent("记住我喜欢 fast 模式"))
        self.assertTrue(is_memory_intent("remember this preference"))
        self.assertFalse(is_memory_intent("删除这条记忆"))

        self.assertTrue(requests_multiview_followup("继续生成三视图"))
        self.assertFalse(requests_multiview_followup("生成一个模型"))

    def test_detects_generation_intents(self) -> None:
        self.assertTrue(is_3d_intent("生成一个3d模型"))
        self.assertTrue(is_text_3d_intent("生成一个模型"))
        self.assertFalse(is_3d_intent("修改 llm 模型配置"))
        self.assertTrue(is_image_3d_intent("转成3d", ["source.png"]))
        self.assertFalse(is_image_3d_intent("转成3d", ["source.txt"]))

        self.assertTrue(is_image_generation_intent("生成一张狗的图片"))
        self.assertFalse(is_image_generation_intent("生成一个3d模型"))
        self.assertTrue(is_image_edit_intent("把图片改成白色", ["source.png"]))
        self.assertFalse(is_image_edit_intent("把图片改成白色", ["source.txt"]))

    def test_detects_previous_asset_edit_intents(self) -> None:
        self.assertTrue(is_previous_image_edit_intent("把上一张图补全"))
        self.assertFalse(is_previous_image_edit_intent("重新画一张图"))
        self.assertTrue(is_modify_previous_3d_intent("把刚才这个改成白色"))
        self.assertFalse(is_modify_previous_3d_intent("重新做一个新模型"))


if __name__ == "__main__":
    unittest.main()
