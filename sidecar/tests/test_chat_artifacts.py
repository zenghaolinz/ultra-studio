import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services import chat_artifacts
from services.chat_artifacts import Artifact


class ChatArtifactsTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_artifacts_supports_generic_and_legacy_image_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html = Path(temp_dir) / "page.html"
            image = Path(temp_dir) / "dog.png"
            html.write_text("<h1>Hello</h1>", encoding="utf-8")
            image.write_text("x", encoding="utf-8")

            artifacts = chat_artifacts.extract_artifacts_from_content(
                f'[Artifact: kind="code" path="{html}" label="page"]\n'
                f'[Image Asset: path="{image}" prompt="yellow dog"]'
            )

        self.assertEqual([artifact.kind for artifact in artifacts], ["code", "image"])
        self.assertEqual(artifacts[0].label, "page")
        self.assertEqual(artifacts[1].prompt, "yellow dog")

    async def test_resolve_referenced_artifact_by_ordinal_and_specific_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "first.png"
            first_html = Path(temp_dir) / "first.html"
            second_html = Path(temp_dir) / "second.html"
            for path in [image, first_html, second_html]:
                path.write_text("x", encoding="utf-8")
            db = AsyncMock()
            db.execute_fetchall.return_value = [
                (f'[Artifact: kind="image" path="{image}" prompt="yellow dog"]',),
                (f'[Artifact: kind="code" path="{first_html}" label="first html"]',),
                (f'[Artifact: kind="code" path="{second_html}" label="second html"]',),
            ]

            with patch.object(chat_artifacts, "get_db", new=AsyncMock(return_value=db)):
                artifact = await chat_artifacts.resolve_referenced_artifact("conversation", "修改第二个 html 文件")

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.path, str(second_html))

    async def test_resolve_referenced_artifact_by_semantic_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            yellow_dog = Path(temp_dir) / "yellow-dog.png"
            white_cat = Path(temp_dir) / "white-cat.png"
            yellow_dog.write_text("x", encoding="utf-8")
            white_cat.write_text("x", encoding="utf-8")
            db = AsyncMock()
            db.execute_fetchall.return_value = [
                (f'[Artifact: kind="image" path="{yellow_dog}" prompt="yellow dog in grass"]',),
                (f'[Artifact: kind="image" path="{white_cat}" prompt="white cat on sofa"]',),
            ]

            with patch.object(chat_artifacts, "get_db", new=AsyncMock(return_value=db)):
                artifact = await chat_artifacts.resolve_referenced_artifact("conversation", "使用黄色狗的图片")

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.path, str(yellow_dog))

    async def test_inject_artifacts_context_writes_standard_marker(self) -> None:
        with patch.object(chat_artifacts.memory_stm, "inject_system_context", new=AsyncMock()) as inject:
            await chat_artifacts.inject_artifacts_context(
                "conversation",
                [Artifact(kind="text", path="C:\\tmp\\note.txt", label="note")],
            )

        payload = inject.await_args.args[1]
        self.assertIn('[Artifact: kind="text"', payload)
        self.assertIn('label="note"', payload)


if __name__ == "__main__":
    unittest.main()
