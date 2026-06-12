import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_visual_prompts import build_visual_edit_prompt, image_url_part


class ChatVisualPromptsTests(unittest.IsolatedAsyncioTestCase):
    def test_image_url_part_encodes_supported_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.png"
            path.write_bytes(b"png")

            part = image_url_part(str(path))

        self.assertEqual(part["type"], "image_url")
        self.assertTrue(part["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_build_visual_edit_prompt_falls_back_without_vision(self) -> None:
        client = AsyncMock()

        prompt = await build_visual_edit_prompt(client, "model", "missing.png", "make it red", {"supports_vision": False})

        self.assertEqual(prompt, "make it red")
        client.chat.completions.create.assert_not_awaited()

    async def test_build_visual_edit_prompt_uses_vision_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.png"
            path.write_bytes(b"png")
            client = AsyncMock()
            client.chat.completions.create.return_value.choices = [
                type("Choice", (), {"message": type("Message", (), {"content": "edited prompt"})()})()
            ]

            prompt = await build_visual_edit_prompt(
                client,
                "vision-model",
                str(path),
                "make it red",
                {"supports_vision": True},
            )

        self.assertEqual(prompt, "edited prompt")
        client.chat.completions.create.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
