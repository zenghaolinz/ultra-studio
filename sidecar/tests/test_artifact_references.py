import sys
import tempfile
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.artifact_references import (
    build_artifact_context,
    resolve_artifact_references,
)


class ArtifactReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp_dir.name)
        self.upload_1 = root / "upload-one.png"
        self.upload_2 = root / "upload-two.png"
        self.generated_1 = root / "generated-one.png"
        self.generated_2 = root / "generated-two.png"
        for path in (self.upload_1, self.upload_2, self.generated_1, self.generated_2):
            path.write_bytes(b"image")
        self.artifacts = [
            self.artifact("u1", "uploaded", self.upload_1, 1),
            self.artifact("g1", "generated", self.generated_1, 2),
            self.artifact("u2", "uploaded", self.upload_2, 3),
            self.artifact("g2", "generated", self.generated_2, 4),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def artifact(artifact_id: str, source: str, path: Path, sequence: int) -> dict:
        return {
            "id": artifact_id,
            "kind": "image",
            "source": source,
            "path": str(path),
            "status": "available",
            "sequence": sequence,
            "prompt": artifact_id,
        }

    def test_above_image_resolves_latest_available_image(self) -> None:
        resolved = resolve_artifact_references("把上面这张图改成红色", self.artifacts)

        self.assertEqual([item["id"] for item in resolved], ["g2"])

    def test_source_phrases_resolve_latest_upload_and_generation(self) -> None:
        uploaded = resolve_artifact_references("修改我上传的图片", self.artifacts)
        generated = resolve_artifact_references("修改之前生成的图片", self.artifacts)

        self.assertEqual([item["id"] for item in uploaded], ["u2"])
        self.assertEqual([item["id"] for item in generated], ["g2"])

    def test_mixed_source_request_returns_one_from_each_source(self) -> None:
        resolved = resolve_artifact_references(
            "把我上传的图片和之前生成的图片融合", self.artifacts
        )

        self.assertEqual([item["id"] for item in resolved], ["u2", "g2"])

    def test_ordinal_applies_within_requested_source(self) -> None:
        resolved = resolve_artifact_references("使用第二张上传图片", self.artifacts)

        self.assertEqual([item["id"] for item in resolved], ["u2"])

    def test_two_images_resolves_latest_two_in_sequence_order(self) -> None:
        resolved = resolve_artifact_references("把这两张图融合", self.artifacts)

        self.assertEqual([item["id"] for item in resolved], ["u2", "g2"])

    def test_missing_files_are_never_resolved(self) -> None:
        self.generated_2.unlink()

        resolved = resolve_artifact_references("把上面这张图改一下", self.artifacts)

        self.assertEqual([item["id"] for item in resolved], ["u2"])

    def test_context_exposes_provenance_and_canonical_paths(self) -> None:
        resolved = resolve_artifact_references(
            "把上传图和生成图融合", self.artifacts
        )

        context = build_artifact_context(resolved, self.artifacts)

        self.assertIn('[Resolved Artifact id="u2" source="uploaded"', context)
        self.assertIn(str(self.upload_2), context)
        self.assertIn('[Resolved Artifact id="g2" source="generated"', context)
        self.assertIn("Do not invent or swap paths", context)

    def test_new_generation_request_does_not_resolve_old_image(self) -> None:
        resolved = resolve_artifact_references(
            "生成图片：一只新的蓝色狐狸", self.artifacts
        )

        self.assertEqual(resolved, [])

    def test_uploaded_pdf_resolves_latest_uploaded_document(self) -> None:
        first = Path(self.temp_dir.name) / "first.pdf"
        latest = Path(self.temp_dir.name) / "latest.docx"
        first.write_bytes(b"pdf")
        latest.write_bytes(b"docx")
        artifacts = self.artifacts + [
            {**self.artifact("d1", "uploaded", first, 5), "kind": "document"},
            {**self.artifact("d2", "uploaded", latest, 6), "kind": "document"},
        ]

        resolved = resolve_artifact_references(
            "\u8bf7\u8bfb\u53d6\u6211\u4e0a\u4f20\u7684 PDF \u6587\u6863", artifacts
        )

        self.assertEqual([item["id"] for item in resolved], ["d2"])

    def test_previous_generated_code_resolves_code_artifact(self) -> None:
        code = Path(self.temp_dir.name) / "generated.py"
        code.write_text("print('ok')", encoding="utf-8")
        artifacts = self.artifacts + [
            {**self.artifact("c1", "generated", code, 5), "kind": "code"},
        ]

        resolved = resolve_artifact_references(
            "\u4fee\u6539\u4e4b\u524d\u751f\u6210\u7684\u4ee3\u7801\u6587\u4ef6", artifacts
        )

        self.assertEqual([item["id"] for item in resolved], ["c1"])

    def test_ordinal_generic_file_uses_conversation_sequence(self) -> None:
        document = Path(self.temp_dir.name) / "notes.pdf"
        code = Path(self.temp_dir.name) / "main.py"
        document.write_bytes(b"pdf")
        code.write_text("pass", encoding="utf-8")
        artifacts = [
            {**self.artifact("d1", "uploaded", document, 1), "kind": "document"},
            {**self.artifact("c1", "uploaded", code, 2), "kind": "code"},
        ]

        resolved = resolve_artifact_references("\u6253\u5f00\u7b2c\u4e8c\u4e2a\u6587\u4ef6", artifacts)

        self.assertEqual([item["id"] for item in resolved], ["c1"])

    def test_mixed_document_and_code_returns_latest_of_each_kind(self) -> None:
        document = Path(self.temp_dir.name) / "notes.pdf"
        code = Path(self.temp_dir.name) / "main.py"
        document.write_bytes(b"pdf")
        code.write_text("pass", encoding="utf-8")
        artifacts = [
            {**self.artifact("d1", "uploaded", document, 1), "kind": "document"},
            {**self.artifact("c1", "uploaded", code, 2), "kind": "code"},
        ]

        resolved = resolve_artifact_references(
            "\u5bf9\u7167\u4e0a\u4f20\u7684 PDF \u548c\u4ee3\u7801\u6587\u4ef6", artifacts
        )

        self.assertEqual([item["id"] for item in resolved], ["d1", "c1"])


if __name__ == "__main__":
    unittest.main()
