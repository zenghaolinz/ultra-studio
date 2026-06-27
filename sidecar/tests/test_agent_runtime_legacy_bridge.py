import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.legacy_bridge import build_read_only_registry
from agent_runtime.models import ToolCall


class AgentRuntimeLegacyBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_reuses_existing_read_and_web_metadata(self) -> None:
        registry = build_read_only_registry()

        file_names = {tool.name for tool in registry.definitions({"files"})}
        web_names = {tool.name for tool in registry.definitions({"web"})}

        self.assertEqual(
            file_names,
            {"read_document", "read_many_files", "list_directory", "search_files"},
        )
        self.assertEqual(web_names, {"web_search", "web_fetch"})

    async def test_read_document_calls_existing_domain_handler(self) -> None:
        registry = build_read_only_registry()
        with patch(
            "agent_runtime.legacy_bridge.memory_mgr.handle_read_document",
            return_value={"ok": True, "content": "hello"},
        ) as handler:
            result = await registry.execute(ToolCall(
                id="call-1",
                name="read_document",
                arguments={"file_path": "notes.txt", "max_chars": 2000},
            ))

        handler.assert_called_once_with("notes.txt", 2000)
        self.assertEqual(result.content["content"], "hello")


if __name__ == "__main__":
    unittest.main()
