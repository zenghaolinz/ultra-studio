import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_titles import NEW_CONVERSATION_TITLE, maybe_generate_title


class FakeDb:
    def __init__(self, title):
        self.title = title
        self.executed = []
        self.committed = False

    async def execute_fetchall(self, query, params=None):
        return [(self.title,)]

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def commit(self):
        self.committed = True


class ChatTitlesTests(unittest.IsolatedAsyncioTestCase):
    async def test_maybe_generate_title_skips_existing_title(self) -> None:
        db = FakeDb("Existing title")

        with patch("services.chat_titles.get_provider_client") as get_client:
            await maybe_generate_title(db, "conversation-1", "hello")

        get_client.assert_not_called()
        self.assertEqual(db.executed, [])
        self.assertFalse(db.committed)

    async def test_maybe_generate_title_updates_new_conversation_title(self) -> None:
        db = FakeDb(NEW_CONVERSATION_TITLE)
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='"Project Plan"')
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )
        )

        with (
            patch("services.chat_titles.get_provider_client", new=AsyncMock(return_value=(client, ("openai", "gpt-test")))),
            patch("services.chat_titles.utc_iso", return_value="2026-06-08T00:00:00+00:00"),
        ):
            await maybe_generate_title(db, "conversation-1", "hello" * 80)

        client.chat.completions.create.assert_awaited_once()
        self.assertEqual(db.executed[0][1], ("Project Plan", "2026-06-08T00:00:00+00:00", "conversation-1"))
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()
