import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_delete_flow import run_confirmed_delete_request


class ChatDeleteFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_confirmed_delete_request_returns_none_without_confirmation(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="delete maybe")

        result = await run_confirmed_delete_request(req, object(), "model")

        self.assertIsNone(result)

    async def test_run_confirmed_delete_request_deletes_then_creates_for_continuation(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="确认删除 `C:\\tmp\\old.html`\n\n后续任务：再写一个新的",
            permission_mode="standard",
        )

        with (
            patch("services.chat_delete_flow.memory_mgr.handle_delete_path") as delete_path,
            patch("services.chat_delete_flow.run_direct_text_file_create", new_callable=AsyncMock) as create_file,
        ):
            delete_path.return_value = {"ok": True, "path": "C:\\tmp\\old.html"}
            create_file.return_value = {"ok": True, "path": "C:\\tmp\\new.html"}

            delete_result, create_result = await run_confirmed_delete_request(req, object(), "model")

        self.assertEqual(delete_result["path"], "C:\\tmp\\old.html")
        self.assertEqual(create_result["path"], "C:\\tmp\\new.html")
        delete_path.assert_called_once_with("C:\\tmp\\old.html", "auto", False, True, "standard")
        create_file.assert_awaited_once()
        self.assertIn("C:\\tmp", create_file.await_args.kwargs["prompt_override"])


if __name__ == "__main__":
    unittest.main()
