import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.models import ToolDefinition
from agent_runtime.providers import NativeToolProvider


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        self.iterator = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.chunks)


def chunk(*, text=None, tool_calls=None, finish_reason=None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def tool_delta(index, *, call_id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


class NativeToolProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_delta_is_emitted_immediately_without_buffering(self) -> None:
        completions = FakeCompletions([chunk(text="你"), chunk(text="好"), chunk(finish_reason="stop")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        provider = NativeToolProvider()

        stream = provider.stream_turn(client, "model", [{"role": "user", "content": "hi"}], [])
        first = await anext(stream)

        self.assertEqual(first.type, "text_delta")
        self.assertEqual(first.text, "你")
        self.assertTrue(completions.kwargs["stream"])

    async def test_fragmented_native_tool_call_is_assembled(self) -> None:
        completions = FakeCompletions([
            chunk(tool_calls=[tool_delta(0, call_id="call-1", name="read_file", arguments='{"pa')]),
            chunk(tool_calls=[tool_delta(0, arguments='th":"a.txt"}')]),
            chunk(finish_reason="tool_calls"),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        provider = NativeToolProvider()
        tools = [ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )]

        events = [event async for event in provider.stream_turn(client, "model", [], tools)]

        self.assertEqual(events[0].type, "tool_call")
        self.assertEqual(events[0].tool_call.name, "read_file")
        self.assertEqual(events[0].tool_call.arguments, {"path": "a.txt"})
        self.assertEqual(events[-1].finish_reason, "tool_calls")
        self.assertEqual(completions.kwargs["tools"][0]["function"]["name"], "read_file")


if __name__ == "__main__":
    unittest.main()
