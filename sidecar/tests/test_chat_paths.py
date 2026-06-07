import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_paths import (
    candidate_local_paths,
    document_attachments,
    extract_directory_path,
    format_path_resolution_card,
    image_attachments,
)


class ChatPathsTests(unittest.TestCase):
    def test_splits_document_and_image_attachments(self) -> None:
        paths = ["a.png", "b.docx", "c.md", "d.glb"]

        self.assertEqual(image_attachments(paths), ["a.png"])
        self.assertEqual(document_attachments(paths), ["b.docx", "c.md"])

    def test_extracts_quoted_local_paths_once(self) -> None:
        self.assertEqual(
            candidate_local_paths("open `C:\\tmp\\a.txt` and `C:\\tmp\\a.txt`"),
            ["C:\\tmp\\a.txt"],
        )

    def test_extracts_existing_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(extract_directory_path(f"read `{temp_dir}`"), Path(temp_dir).resolve())

    def test_formats_path_resolution_card(self) -> None:
        response = format_path_resolution_card("missing", [{"type": "folder", "path": "C:\\tmp"}])

        self.assertIn("[PATH_RESOLUTION_REQUIRED]", response)
        self.assertIn("C:\\tmp", response)


if __name__ == "__main__":
    unittest.main()
