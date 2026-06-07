import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from routes.asset_3d import GenerateVideoRequest
from schemas import ChatRequest, EmbeddingConfigCreate, MemoryRememberRequest


class SchemaValidationTests(unittest.TestCase):
    def test_chat_request_rejects_empty_content(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(conversation_id="conv-1", content="")

    def test_embedding_dimensions_have_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            EmbeddingConfigCreate(provider="openai", model_name="text-embedding", dimensions=0)

        with self.assertRaises(ValidationError):
            EmbeddingConfigCreate(provider="openai", model_name="text-embedding", dimensions=8192)

    def test_memory_tags_do_not_share_mutable_defaults(self) -> None:
        first = MemoryRememberRequest(content="first")
        second = MemoryRememberRequest(content="second")

        first.tags.append("private")

        self.assertEqual(second.tags, [])

    def test_generate_video_request_rejects_out_of_bounds_values(self) -> None:
        with self.assertRaises(ValidationError):
            GenerateVideoRequest(prompt="orbit", duration_seconds=8)

        with self.assertRaises(ValidationError):
            GenerateVideoRequest(prompt="orbit", width=2048)

        with self.assertRaises(ValidationError):
            GenerateVideoRequest(prompt="orbit", quality_mode="draft")


if __name__ == "__main__":
    unittest.main()

