import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.responses import StreamingResponse

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from routes import chat
from schemas import ChatRequest


def runtime_response() -> StreamingResponse:
    async def events():
        yield "data: " + json.dumps({
            "type": "text.delta",
            "data": {"text": "hello"},
        }) + "\n\n"
        yield "data: " + json.dumps({
            "type": "run.finished",
            "data": {
                "status": "completed",
                "content": "hello",
                "messageId": "message-1",
                "createdAt": "now",
            },
        }) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


class ChatCompatibilityRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_stream_url_delegates_to_agent_runtime(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="hello")
        with patch.object(
            chat, "stream_agent_run", AsyncMock(return_value=runtime_response())
        ) as runtime:
            response = await chat.send_message_stream(req)

        self.assertEqual(response.media_type, "text/event-stream")
        runtime.assert_awaited_once_with(req)

    async def test_legacy_non_stream_url_collects_runtime_completion(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="hello")
        with patch.object(
            chat, "stream_agent_run", AsyncMock(return_value=runtime_response())
        ):
            message = await chat.send_message(req)

        self.assertEqual(message["id"], "message-1")
        self.assertEqual(message["content"], "hello")
        self.assertEqual(message["conversationId"], "conversation-1")


if __name__ == "__main__":
    unittest.main()
