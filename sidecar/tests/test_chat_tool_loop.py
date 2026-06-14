import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_tool_loop import RESULT_VERIFICATION_PROMPT, run_tool_calls


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
        self.assertTrue(any(message.get("role") == "tool" and "remembered" in message.get("content", "") for message in messages))
        self.assertEqual(messages[-1], {"role": "system", "content": RESULT_VERIFICATION_PROMPT})

    async def test_run_tool_calls_adds_verification_step_before_repair_call(self) -> None:
        edit_call = SimpleNamespace(
            id="call-edit",
            function=SimpleNamespace(
                name="edit_text_file",
                arguments='{"file_path":"C:/tmp/example.txt","action":"replace","find":"old","replace":"new"}',
            ),
        )
        read_call = SimpleNamespace(
            id="call-read",
            function=SimpleNamespace(
                name="read_document",
                arguments='{"file_path":"C:/tmp/example.txt","max_chars":12000}',
            ),
        )
        first = SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=[edit_call]))])
        second = SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=[read_call]))])
        third = SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=None))])
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=[first, second, third]))
            )
        )

        with patch("services.chat_tool_loop.memory_mgr.handle_read_document") as read_document:
            read_document.return_value = {"ok": True, "path": "C:/tmp/example.txt", "content": "old"}

            messages, tool_results, _ = await run_tool_calls(client, "model", [{"role": "user", "content": "fix file"}], [])

        self.assertEqual([item["tool"] for item in tool_results], ["edit_text_file", "read_document"])
        self.assertTrue(tool_results[0]["result"]["needs_read"])
        self.assertEqual(client.chat.completions.create.await_count, 3)
        second_call_messages = client.chat.completions.create.await_args_list[1].kwargs["messages"]
        self.assertTrue(any(message.get("content") == RESULT_VERIFICATION_PROMPT for message in second_call_messages))
        self.assertEqual(messages[-1], {"role": "system", "content": RESULT_VERIFICATION_PROMPT})


if __name__ == "__main__":
    unittest.main()
