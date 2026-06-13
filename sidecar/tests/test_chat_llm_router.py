import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_llm_router import llm_route_request


class ChatLlmRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_route_request_short_circuits_delete_requests(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="确认删除 `a.txt`")

        result = await llm_route_request(object(), "model", req)

        self.assertEqual(result["action"], "general_tools")
        self.assertIn("delete", result["reason"])

    async def test_llm_route_request_short_circuits_web_scope(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="search the web")
        with patch("services.chat_llm_router.memory_mgr.infer_tool_scope", return_value="web"):
            result = await llm_route_request(object(), "model", req)

        self.assertEqual(result["action"], "general_tools")
        self.assertIn("web", result["reason"])

    async def test_llm_route_request_returns_valid_json_decision(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="make an image", vision_enabled=True)
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"action":"generate_image","prompt":"a cat","quality_mode":"slow","source":"none"}'
                    )
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )
        )

        with (
            patch("services.chat_llm_router.memory_mgr.infer_tool_scope", return_value=None),
            patch("services.chat_llm_router.build_router_context", new=AsyncMock(return_value={"attached_images": []})),
        ):
            decision = await llm_route_request(client, "model", req, ("openai", "gpt-4o"))

        self.assertEqual(decision["action"], "generate_image")
        self.assertEqual(decision["prompt"], "a cat")
        self.assertEqual(decision["quality_mode"], "fast")
        client.chat.completions.create.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
