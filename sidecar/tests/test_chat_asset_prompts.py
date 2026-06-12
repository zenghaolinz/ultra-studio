import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_asset_prompts import (
    contains_any,
    deterministic_asset_prompt,
    document_requirement_text,
)


class ChatAssetPromptsTests(unittest.TestCase):
    def test_document_requirement_text_strips_requirement_labels(self) -> None:
        text = document_requirement_text(["[a.txt]\n要求：白色可爱小狗"])

        self.assertEqual(text, "白色可爱小狗")

    def test_deterministic_asset_prompt_preserves_pet_requirements(self) -> None:
        prompt = deterministic_asset_prompt("白色可爱小狗", "image")

        self.assertIn("white", prompt)
        self.assertIn("cute adorable", prompt)
        self.assertIn("puppy dog", prompt)
        self.assertIn("no humans", prompt)

    def test_contains_any_is_case_insensitive(self) -> None:
        self.assertTrue(contains_any("Cute Dog", ["cute"]))
        self.assertFalse(contains_any("Cute Dog", ["cat"]))


if __name__ == "__main__":
    unittest.main()
