import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_documents import folder_documents, read_document_attachments


class ChatDocumentsTests(unittest.TestCase):
    def test_folder_documents_filters_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "notes.md"
            image = root / "image.png"
            doc.write_text("doc", encoding="utf-8")
            image.write_text("image", encoding="utf-8")

            self.assertEqual(folder_documents(root), [doc])

    def test_read_document_attachments_formats_success_and_failure(self) -> None:
        def fake_read(path, max_chars):
            if path == "bad.txt":
                return {"ok": False, "error": "blocked"}
            return {"ok": True, "name": path, "content": f"read {max_chars}"}

        with patch("services.chat_documents.memory_mgr.handle_read_document", side_effect=fake_read):
            sections = read_document_attachments(["good.txt", "bad.txt"], 123)

        self.assertIn("read 123", sections[0])
        self.assertIn("blocked", sections[1])


if __name__ == "__main__":
    unittest.main()
