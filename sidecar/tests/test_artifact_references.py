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


if __name__ == "__main__":
    unittest.main()
