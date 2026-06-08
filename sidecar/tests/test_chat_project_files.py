import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_project_files import (
    project_document_paths,
    project_file_candidates,
    project_image_paths,
)


class ChatProjectFilesTests(unittest.TestCase):
    def test_project_document_paths_prefers_named_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "新建要求.txt"
            target.write_text("requirements", encoding="utf-8")
            (root / "other.md").write_text("other", encoding="utf-8")

            self.assertEqual(project_document_paths(temp_dir, "读取新建要求文本文档"), [str(target)])

    def test_project_image_paths_returns_matching_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "hero-product.png"
            image.write_text("image", encoding="utf-8")
            (root / "notes.txt").write_text("notes", encoding="utf-8")

            self.assertEqual(project_image_paths(temp_dir, "项目图片 hero", limit=1), [str(image)])

    def test_project_file_candidates_classifies_documents_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "hero.png"
            doc = root / "requirements.md"
            image.write_text("image", encoding="utf-8")
            doc.write_text("doc", encoding="utf-8")

            candidates = project_file_candidates(temp_dir, "图片和文档", limit=5)
            by_name = {item["name"]: item for item in candidates}

            self.assertEqual(by_name[image.name]["kind"], "image")
            self.assertEqual(by_name[doc.name]["kind"], "document")


if __name__ == "__main__":
    unittest.main()
