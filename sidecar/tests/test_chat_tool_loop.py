import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_tool_loop import run_tool_calls


class FakeMessage:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls

    def model_dump(self):
        return {"role": "assistant", "tool_calls": []}


class ChatToolLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_tool_calls_returns_when_model_has_no_tool_calls(self) -> None:
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=FakeMessage(tool_calls=None))]
                        )
                    )
                )
            )
        )
        messages = [{"role": "user", "content": "hello"}]

        returned_messages, tool_results, saved_memories = await run_tool_calls(
            client,
            "model",
            messages,
            [],
        )

        self.assertIs(returned_messages, messages)
        self.assertEqual(tool_results, [])
        self.assertEqual(saved_memories, [])

    async def test_run_tool_calls_dispatches_recall_memory(self) -> None:
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="recall_memory", arguments='{"branch_path":"main"}'),
        )
        first = SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=[tool_call]))])
        second = SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=None))])
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=[first, second]))
            )
        )

        with patch("services.chat_tool_loop.memory_mgr.handle_recall_memory") as recall:
            recall.return_value = [{"text": "remembered"}]

            messages, tool_results, _ = await run_tool_calls(client, "model", [], [])

        recall.assert_called_once_with("main")
        self.assertEqual(tool_results, [{"tool": "recall_memory", "result": [{"text": "remembered"}]}])
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertIn("remembered", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
