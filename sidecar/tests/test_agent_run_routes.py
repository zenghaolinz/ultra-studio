import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.models import AgentRunRequest
from routes import agent_runs
from schemas import ChatRequest


class FakeLoop:
    async def stream(self, client, model_name, request, capabilities):
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "text.delta",
            "sequence": 1,
            "timestamp": "now",
            "data": {"text": "hello"},
        }
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "run.finished",
            "sequence": 2,
            "timestamp": "now",
            "data": {"status": "completed", "content": "hello", "metrics": {"applicationTtftMs": 10}},
        }


class ConfirmationLoop:
    async def stream(self, client, model_name, request, capabilities):
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "run.finished",
            "sequence": 1,
            "timestamp": "now",
            "data": {
                "status": "confirmation_required",
                "content": "",
                "toolCall": {
                    "id": "call-1",
                    "name": "delete_file",
                    "arguments": {"target_path": "C:/tmp/a.txt", "target_type": "file"},
                },
                "metrics": {},
            },
        }


class AgentRunRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_event_is_formatted_and_persisted_for_existing_ui(self) -> None:
        runtime_request = AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "delete it"}],
        )
        prepared = (ConfirmationLoop(), object(), "model", runtime_request, {"files"}, object())
        with patch.object(agent_runs, "_prepare_run", AsyncMock(return_value=prepared)), patch.object(
            agent_runs,
            "save_assistant_message",
            AsyncMock(return_value=("message-1", "created")),
        ) as save_message:
            response = await agent_runs.stream_agent_run(
                ChatRequest(conversation_id="conversation-1", content="delete it")
            )
            chunks = [chunk async for chunk in response.body_iterator]

        payload = json.loads(chunks[-1].removeprefix("data: ").strip())
        self.assertIn("[CONFIRM_DELETE_REQUIRED]", payload["data"]["content"])
        self.assertEqual(payload["data"]["messageId"], "message-1")
        save_message.assert_awaited_once()

    async def test_capabilities_include_generation_only_when_context_offers_it(self) -> None:
        generation_tool = {
            "type": "function",
            "function": {"name": "generate_video", "parameters": {"type": "object"}},
        }

        self.assertEqual(
            agent_runs._capabilities_for_tools([generation_tool]),
            {"generation"},
        )
        self.assertEqual(agent_runs._capabilities_for_tools([]), set())

        mutation_tool = {
            "type": "function",
            "function": {"name": "edit_text_file", "parameters": {"type": "object"}},
        }
        self.assertEqual(
            agent_runs._capabilities_for_tools([mutation_tool]),
            {"files"},
        )

    async def test_route_streams_runtime_events_and_persists_completed_text(self) -> None:
        runtime_request = AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "hi"}],
        )
        prepared = (FakeLoop(), object(), "model", runtime_request, {"files", "web"}, object())
        with patch.object(agent_runs, "_prepare_run", AsyncMock(return_value=prepared)), patch.object(
            agent_runs,
            "save_assistant_message",
            AsyncMock(return_value=("message-1", "created")),
        ) as save_message:
            response = await agent_runs.stream_agent_run(
                ChatRequest(conversation_id="conversation-1", content="hi")
            )
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertEqual(response.media_type, "text/event-stream")
        payloads = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]
        self.assertEqual(payloads[0]["type"], "text.delta")
        self.assertEqual(payloads[-1]["data"]["messageId"], "message-1")
        save_message.assert_awaited_once_with(prepared[-1], "conversation-1", "hello")


if __name__ == "__main__":
    unittest.main()
