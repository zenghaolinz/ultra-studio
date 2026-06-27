import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.legacy_bridge import build_runtime_registry
from agent_runtime.loop import AgentLoop
from agent_runtime.models import AgentRunRequest, ToolCall
from agent_runtime.policy import PermissionPolicy
from agent_runtime.providers import ProviderEvent


class ReplayProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def stream_turn(self, client, model_name, messages, tools):
        self.calls.append(list(messages))
        for event in self.turns.pop(0):
            yield event


def request(permission_mode: str = "standard") -> AgentRunRequest:
    return AgentRunRequest(
        run_id="replay-1",
        conversation_id="conversation-1",
        messages=[{"role": "user", "content": "replay"}],
        permission_mode=permission_mode,
    )


class AgentRuntimeReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_chat_replay_has_one_turn_and_visible_delta(self) -> None:
        provider = ReplayProvider([[
            ProviderEvent(type="text_delta", text="hello"),
            ProviderEvent(type="finished", finish_reason="stop"),
        ]])
        loop = AgentLoop(provider, build_runtime_registry(), PermissionPolicy())

        events = [event async for event in loop.stream(None, "model", request(), set())]

        self.assertEqual(len(provider.calls), 1)
        self.assertIn("text.delta", [event["type"] for event in events])

    async def test_generation_replays_return_queued_task_without_waiting(self) -> None:
        cases = {
            "generate_image": {"prompt": "fox"},
            "generate_video": {"prompt": "fox running"},
            "generate_3d_from_text": {"prompt": "fox statue"},
        }
        for tool_name, arguments in cases.items():
            with self.subTest(tool_name=tool_name), patch(
                "agent_runtime.legacy_bridge.call_mcp_tool",
                return_value={"status": "queued", "task_id": f"task-{tool_name}"},
            ):
                provider = ReplayProvider([
                    [
                        ProviderEvent(type="tool_call", tool_call=ToolCall(
                            id="call-1", name=tool_name, arguments=arguments
                        )),
                        ProviderEvent(type="finished", finish_reason="tool_calls"),
                    ],
                    [
                        ProviderEvent(type="text_delta", text="queued"),
                        ProviderEvent(type="finished", finish_reason="stop"),
                    ],
                ])
                loop = AgentLoop(
                    provider,
                    build_runtime_registry("conversation-1"),
                    PermissionPolicy(),
                )

                events = [event async for event in loop.stream(
                    None, "model", request(), {"generation"}
                )]

                self.assertEqual(len(provider.calls), 2)
                self.assertIn(f"task-{tool_name}", provider.calls[1][-1]["content"])
                self.assertEqual(events[-1]["data"]["status"], "completed")

    async def test_destructive_replay_stops_until_confirmed(self) -> None:
        provider = ReplayProvider([[
            ProviderEvent(type="tool_call", tool_call=ToolCall(
                id="call-1",
                name="delete_file",
                arguments={"target_path": "a.txt", "target_type": "file"},
            )),
            ProviderEvent(type="finished", finish_reason="tool_calls"),
        ]])
        loop = AgentLoop(provider, build_runtime_registry(), PermissionPolicy())

        events = [event async for event in loop.stream(
            None, "model", request(), {"files"}
        )]

        self.assertEqual(events[-1]["data"]["status"], "confirmation_required")


if __name__ == "__main__":
    unittest.main()
