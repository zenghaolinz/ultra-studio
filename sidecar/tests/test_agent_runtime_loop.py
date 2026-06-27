import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.events import RunEventEmitter
from agent_runtime.loop import AgentLoop
from agent_runtime.models import AgentRunRequest, ToolCall, ToolDefinition
from agent_runtime.policy import PermissionPolicy
from agent_runtime.providers import ProviderEvent
from agent_runtime.tools import ToolRegistry


class FakeProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def stream_turn(self, client, model_name, messages, tools):
        self.calls.append(list(messages))
        for event in self.turns.pop(0):
            yield event


def tool_definition(name="read_file"):
    return ToolDefinition(
        name=name,
        description="Read a file",
        capability="files",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


class AgentRuntimeLoopTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        return AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "hello"}],
        )

    async def test_ordinary_chat_uses_one_model_turn_and_streams_text(self) -> None:
        provider = FakeProvider([[
            ProviderEvent(type="text_delta", text="你"),
            ProviderEvent(type="text_delta", text="好"),
            ProviderEvent(type="finished", finish_reason="stop"),
        ]])
        loop = AgentLoop(provider, ToolRegistry(), PermissionPolicy())

        events = [event async for event in loop.stream(None, "model", self.request(), {"files"})]

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            [event["data"].get("text") for event in events if event["type"] == "text.delta"],
            ["你", "好"],
        )
        finished = next(event for event in events if event["type"] == "run.finished")
        self.assertEqual(finished["data"]["status"], "completed")
        self.assertEqual(finished["data"]["metrics"]["modelTurns"], 1)

    async def test_tool_call_executes_then_returns_to_model(self) -> None:
        provider = FakeProvider([
            [
                ProviderEvent(type="tool_call", tool_call=ToolCall(
                    id="call-1", name="read_file", arguments={"path": "a.txt"}
                )),
                ProviderEvent(type="finished", finish_reason="tool_calls"),
            ],
            [
                ProviderEvent(type="text_delta", text="内容"),
                ProviderEvent(type="finished", finish_reason="stop"),
            ],
        ])
        registry = ToolRegistry()
        registry.register(tool_definition(), lambda args: f"read:{args['path']}", risk="read")
        loop = AgentLoop(provider, registry, PermissionPolicy())

        events = [event async for event in loop.stream(None, "model", self.request(), {"files"})]

        self.assertEqual(len(provider.calls), 2)
        self.assertIn("tool.started", [event["type"] for event in events])
        self.assertIn("tool.finished", [event["type"] for event in events])
        self.assertEqual(provider.calls[1][-1]["role"], "tool")
        self.assertEqual(provider.calls[1][-1]["content"], "read:a.txt")

    async def test_confirmation_policy_stops_before_execution(self) -> None:
        executed = False

        def delete(_):
            nonlocal executed
            executed = True

        provider = FakeProvider([[
            ProviderEvent(type="tool_call", tool_call=ToolCall(
                id="call-1", name="delete_file", arguments={"path": "a.txt"}
            )),
            ProviderEvent(type="finished", finish_reason="tool_calls"),
        ]])
        registry = ToolRegistry()
        registry.register(tool_definition("delete_file"), delete, risk="destructive")
        loop = AgentLoop(provider, registry, PermissionPolicy())

        events = [event async for event in loop.stream(None, "model", self.request(), {"files"})]

        self.assertFalse(executed)
        finished = next(event for event in events if event["type"] == "run.finished")
        self.assertEqual(finished["data"]["status"], "confirmation_required")
        self.assertEqual(finished["data"]["toolCall"]["name"], "delete_file")


if __name__ == "__main__":
    unittest.main()
