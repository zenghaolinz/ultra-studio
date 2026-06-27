import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.legacy_bridge import build_runtime_registry
from agent_runtime.models import ToolCall


EXPECTED_GENERATION_TOOLS = {
    "generate_image",
    "generate_video",
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_fusion",
    "modify_image_with_flux",
    "generate_multiview_images_from_image",
    "generate_3d_from_generated_multiview",
}


class AgentRuntimeGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_exposes_existing_generation_definitions(self) -> None:
        registry = build_runtime_registry(conversation_id="conversation-1")

        names = {tool.name for tool in registry.definitions({"generation"})}

        self.assertEqual(names, EXPECTED_GENERATION_TOOLS)

    async def test_generation_queues_through_existing_mcp_executor(self) -> None:
        registry = build_runtime_registry(conversation_id="conversation-1")
        queued = {"status": "queued", "task_id": "task-1"}
        with patch(
            "agent_runtime.legacy_bridge.call_mcp_tool",
            return_value=queued,
        ) as call_tool:
            result = await registry.execute(
                ToolCall(
                    id="call-1",
                    name="generate_image",
                    arguments={"prompt": "a glass fox"},
                )
            )

        call_tool.assert_called_once_with(
            "generate_image",
            {"prompt": "a glass fox", "conversation_id": "conversation-1"},
        )
        self.assertEqual(result.content, queued)
        self.assertEqual(registry.risk("generate_image"), "write")


if __name__ == "__main__":
    unittest.main()
