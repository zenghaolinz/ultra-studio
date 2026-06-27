import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.models import ToolCall, ToolDefinition
from agent_runtime.tools import ToolArgumentError, ToolRegistry, UnknownToolError


def definition(name: str, capability: str = "files") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Run {name}",
        capability=capability,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


class AgentRuntimeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_filters_visible_tools_by_capability(self) -> None:
        registry = ToolRegistry()
        registry.register(definition("read_file", "files"), lambda _: "file", risk="read")
        registry.register(definition("web_search", "web"), lambda _: "web", risk="read")

        visible = registry.definitions({"files"})

        self.assertEqual([tool.name for tool in visible], ["read_file"])

    async def test_execute_rejects_unknown_tool(self) -> None:
        registry = ToolRegistry()

        with self.assertRaises(UnknownToolError):
            await registry.execute(ToolCall(id="1", name="missing", arguments={}))

    async def test_execute_rejects_missing_required_argument(self) -> None:
        registry = ToolRegistry()
        registry.register(definition("read_file"), lambda _: "file", risk="read")

        with self.assertRaises(ToolArgumentError):
            await registry.execute(ToolCall(id="1", name="read_file", arguments={}))

    async def test_execute_returns_sync_handler_result(self) -> None:
        registry = ToolRegistry()
        registry.register(definition("read_file"), lambda args: args["path"], risk="read")

        result = await registry.execute(
            ToolCall(id="1", name="read_file", arguments={"path": "notes.txt"})
        )

        self.assertEqual(result.content, "notes.txt")
        self.assertFalse(result.is_error)


if __name__ == "__main__":
    unittest.main()
