import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.legacy_bridge import build_runtime_registry
from agent_runtime.models import ToolCall


class AgentRuntimeMutationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mutations_are_grouped_by_policy_risk(self) -> None:
        registry = build_runtime_registry(permission_mode="standard")
        names = {tool.name for tool in registry.definitions({"files"})}

        self.assertIn("edit_text_file", names)
        self.assertIn("run_command", names)
        self.assertIn("delete_file", names)
        self.assertEqual(registry.risk("edit_text_file"), "write")
        self.assertEqual(registry.risk("run_command"), "destructive")
        self.assertEqual(registry.risk("delete_file"), "destructive")

    async def test_command_adapter_injects_runtime_permission_mode(self) -> None:
        registry = build_runtime_registry(permission_mode="autonomous")
        with patch(
            "agent_runtime.legacy_bridge.memory_mgr.handle_run_command",
            return_value={"ok": True},
        ) as handler:
            await registry.execute(ToolCall(
                id="call-1",
                name="run_command",
                arguments={"command": "git status"},
            ))

        handler.assert_called_once_with(
            "git status", "", "powershell", 60, False, "autonomous"
        )


if __name__ == "__main__":
    unittest.main()
