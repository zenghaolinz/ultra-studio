import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_provider_client import get_provider_client


class FakeDb:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def execute_fetchall(self, query, params=None):
        self.calls.append((query, params))
        return self.responses.pop(0)


class ChatProviderClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_provider_client_prefers_explicit_model(self) -> None:
        db = FakeDb([[("openai", "gpt-test", "sk-test", "https://api.example")]])

        with patch("services.chat_provider_client.AsyncOpenAI") as client_cls:
            client_cls.return_value = object()

            client, provider_config = await get_provider_client(db, "model-1")

        self.assertIs(client, client_cls.return_value)
        self.assertEqual(provider_config, ("openai", "gpt-test", "sk-test", "https://api.example"))
        self.assertEqual(db.calls[0][1], ("model-1",))
        client_cls.assert_called_once_with(api_key="sk-test", base_url="https://api.example")

    async def test_get_provider_client_falls_back_to_default_then_latest(self) -> None:
        db = FakeDb([[], [], [("local", "qwen", "", "http://localhost:1234/v1")]])

        with patch("services.chat_provider_client.AsyncOpenAI") as client_cls:
            client_cls.return_value = object()

            client, provider_config = await get_provider_client(db, "missing")

        self.assertIs(client, client_cls.return_value)
        self.assertEqual(provider_config[1], "qwen")
        self.assertEqual(len(db.calls), 3)
        client_cls.assert_called_once_with(api_key="sk-placeholder", base_url="http://localhost:1234/v1")

    async def test_get_provider_client_returns_empty_when_unconfigured(self) -> None:
        db = FakeDb([[], []])

        with patch("services.chat_provider_client.AsyncOpenAI") as client_cls:
            client, provider_config = await get_provider_client(db)

        self.assertIsNone(client)
        self.assertIsNone(provider_config)
        self.assertEqual(len(db.calls), 2)
        client_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
