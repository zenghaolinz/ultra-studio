import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_router_actions import run_router_action


class ChatRouterActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_router_action_returns_implementation_choice(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="做一个小游戏")

        result = await run_router_action({"action": "choose_implementation"}, req, object(), "model")

        self.assertEqual(result["tool"], "implementation_choice")
        self.assertTrue(result["result"]["ok"])

    async def test_run_router_action_generates_image(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="make image")
        with patch("services.chat_router_actions.memory_mgr.handle_generate_image") as generate:
            generate.return_value = {"status": "success", "image_path": "out.png"}

            result = await run_router_action(
                {"action": "generate_image", "prompt": "a cat", "quality_mode": "quality"},
                req,
                object(),
                "model",
            )

        self.assertEqual(result["tool"], "generate_image")
        self.assertEqual(result["result"]["source_prompt"], "a cat")
        self.assertEqual(result["result"]["quality_mode"], "quality")
        generate.assert_called_once_with("a cat", "quality", "conversation-1")

    async def test_run_router_action_read_document_falls_back_to_project_read(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="read docs", project_path="project")
        with (
            patch("services.chat_router_actions.run_direct_document_read", new=AsyncMock(return_value=None)) as direct,
            patch("services.chat_router_actions.run_project_document_read", new=AsyncMock(return_value="summary")) as project,
        ):
            result = await run_router_action({"action": "read_document"}, req, object(), "model")

        self.assertEqual(result, "summary")
        direct.assert_awaited_once()
        project.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
