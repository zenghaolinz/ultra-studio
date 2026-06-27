import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.models import AgentCompletion, AgentRunRequest, ToolCall, ToolDefinition


class AgentRuntimeModelTests(unittest.TestCase):
    def test_run_identity_is_immutable(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "hello"}],
        )

        with self.assertRaises(ValidationError):
            request.run_id = "run-2"

    def test_tool_definition_requires_object_parameter_schema(self) -> None:
        with self.assertRaises(ValidationError):
            ToolDefinition(
                name="read_file",
                description="Read a local file",
                parameters={"type": "array"},
            )

    def test_tool_call_parses_structured_arguments(self) -> None:
        call = ToolCall(id="call-1", name="read_file", arguments={"path": "a.txt"})

        self.assertEqual(call.arguments["path"], "a.txt")

    def test_completion_rejects_unknown_terminal_status(self) -> None:
        with self.assertRaises(ValidationError):
            AgentCompletion(status="maybe", content="")


if __name__ == "__main__":
    unittest.main()
