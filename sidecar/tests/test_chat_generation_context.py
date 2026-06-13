import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services import chat_generation_context as generation_context


class ChatGenerationContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_inject_image_context_records_image_and_multiview_paths(self) -> None:
        with patch.object(generation_context.memory_stm, "inject_system_context", new=AsyncMock()) as inject:
            await generation_context.inject_image_context(
                "conversation",
                {"status": "success", "image_path": "C:\\tmp\\image.png"},
            )
            await generation_context.inject_image_context(
                "conversation",
                {"status": "success", "frontPath": "front.png", "leftPath": "left.png", "backPath": "back.png"},
            )

        self.assertEqual(inject.await_count, 2)
        self.assertIn("活跃图像路径", inject.await_args_list[0].args[1])
        self.assertIn("活跃三视图正面", inject.await_args_list[1].args[1])

    async def test_inject_3d_context_preserves_source_and_model_paths(self) -> None:
        with patch.object(generation_context.memory_stm, "inject_system_context", new=AsyncMock()) as inject:
            await generation_context.inject_3d_context(
                "conversation",
                {
                    "image2D": "preview.png",
                    "modelPath": "model.glb",
                    "image1Path": "a.png",
                    "image2Path": "b.png",
                },
            )

        payload = inject.await_args.args[1]
        self.assertIn("preview.png", payload)
        self.assertIn("model.glb", payload)
        self.assertIn("活跃融合源图1", payload)

    async def test_find_latest_edit_source_image_reads_existing_path_from_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "image.png"
            image_path.write_text("x", encoding="utf-8")
            db = AsyncMock()
            db.execute_fetchall.return_value = [(f'[System Context: 活跃图像路径="{image_path}"]',)]

            with patch.object(generation_context, "get_db", new=AsyncMock(return_value=db)):
                self.assertEqual(
                    await generation_context.find_latest_edit_source_image("conversation"),
                    str(image_path),
                )

    async def test_resolve_referenced_image_asset_by_ordinal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "yellow-dog.png"
            second = Path(temp_dir) / "white-cat.png"
            first.write_text("x", encoding="utf-8")
            second.write_text("x", encoding="utf-8")
            db = AsyncMock()
            db.execute_fetchall.return_value = [
                (f'[Image Asset: path="{first}" prompt="yellow dog in grass"]',),
                (f'[Image Asset: path="{second}" prompt="white cat on sofa"]',),
            ]

            with patch.object(generation_context, "get_db", new=AsyncMock(return_value=db)):
                self.assertEqual(
                    await generation_context.resolve_referenced_image_asset("conversation", "把第二张图变白色"),
                    str(second),
                )

    async def test_resolve_referenced_image_asset_by_color_and_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            yellow_dog = Path(temp_dir) / "yellow-dog.png"
            white_cat = Path(temp_dir) / "white-cat.png"
            yellow_dog.write_text("x", encoding="utf-8")
            white_cat.write_text("x", encoding="utf-8")
            db = AsyncMock()
            db.execute_fetchall.return_value = [
                (f'[Image Asset: path="{yellow_dog}" prompt="yellow dog in grass"]',),
                (f'[Image Asset: path="{white_cat}" prompt="white cat on sofa"]',),
            ]

            with patch.object(generation_context, "get_db", new=AsyncMock(return_value=db)):
                self.assertEqual(
                    await generation_context.resolve_referenced_image_asset("conversation", "使用黄色狗的图片"),
                    str(yellow_dog),
                )


if __name__ == "__main__":
    unittest.main()
