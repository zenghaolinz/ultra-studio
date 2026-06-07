import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_tool_results import (
    any_requires_manual_comfy_start,
    best_tool_result,
    first_3d_result,
    first_tool_result,
    result_output_paths,
)


class ChatToolResultsTests(unittest.TestCase):
    def test_selects_first_and_best_results(self) -> None:
        results = [
            {"tool": "edit_text_file", "result": {"ok": False}},
            {"tool": "generate_3d_from_text", "result": {"model_path": "C:\\tmp\\model.glb"}},
            {"tool": "edit_text_file", "result": {"ok": True, "path": "C:\\tmp\\a.html"}},
        ]

        self.assertEqual(first_tool_result(results, "edit_text_file"), results[0])
        self.assertEqual(first_3d_result(results), results[1])
        self.assertEqual(best_tool_result(results, "edit_text_file"), results[2])

    def test_detects_manual_start_and_dedupes_output_paths(self) -> None:
        self.assertTrue(any_requires_manual_comfy_start([{"result": {"manual_start_required": True}}]))
        self.assertEqual(
            result_output_paths(
                {
                    "result": {
                        "image_path": "C:\\tmp\\A.png",
                        "path": "c:\\tmp\\a.png",
                        "files": [{"path": "C:\\tmp\\b.html"}],
                    }
                }
            ),
            ["C:\\tmp\\A.png", "C:\\tmp\\b.html"],
        )


if __name__ == "__main__":
    unittest.main()
