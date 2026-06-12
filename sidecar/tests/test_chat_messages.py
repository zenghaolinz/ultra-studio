import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_messages import save_assistant_message, save_visible_user_message
from schemas import ChatRequest


class ChatMessagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_assistant_message_inserts_and_updates_conversation(self) -> None:
        db = AsyncMock()

        assistant_id, timestamp = await save_assistant_message(db, "conversation", "hello")

        self.assertTrue(assistant_id)
        self.assertTrue(timestamp)
        self.assertEqual(db.execute.await_count, 2)
        self.assertIn("INSERT INTO stm_entries", db.execute.await_args_list[0].args[0])
        self.assertIn("UPDATE conversations", db.execute.await_args_list[1].args[0])
        db.commit.assert_awaited_once()

    async def test_save_visible_user_message_skips_hidden_messages(self) -> None:
        db = AsyncMock()
        req = ChatRequest(conversation_id="conversation", content="hidden", hidden_user_message=True)

        self.assertIsNone(await save_visible_user_message(db, req))
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
