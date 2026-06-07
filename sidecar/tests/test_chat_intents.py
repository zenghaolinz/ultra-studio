import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_intents import is_folder_summary_to_docx_intent, is_open_folder_intent


class ChatIntentsTests(unittest.TestCase):
    def test_detects_folder_summary_to_docx_intent(self) -> None:
        self.assertTrue(is_folder_summary_to_docx_intent("读取这个 folder 并生成 docx 报告"))
        self.assertFalse(is_folder_summary_to_docx_intent("打开这个 folder"))

    def test_detects_open_folder_intent(self) -> None:
        self.assertTrue(is_open_folder_intent("open project folder"))
        self.assertTrue(is_open_folder_intent("定位这个目录"))
        self.assertFalse(is_open_folder_intent("总结这个目录"))


if __name__ == "__main__":
    unittest.main()
