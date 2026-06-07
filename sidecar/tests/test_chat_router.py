import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_router import (
    ROUTER_ACTIONS,
    build_agent_trace_payload,
    direct_agent_trace_decision,
    format_agent_trace_block,
    quality_mode_from_decision,
    router_safe_json,
)


class ChatRouterTests(unittest.TestCase):
    def test_router_actions_include_generation_and_file_routes(self) -> None:
        self.assertIn("generate_video", ROUTER_ACTIONS)
        self.assertIn("create_text_file", ROUTER_ACTIONS)
        self.assertIn("choose_implementation", ROUTER_ACTIONS)

    def test_router_safe_json_extracts_object_from_text(self) -> None:
        self.assertEqual(router_safe_json("prefix {\"action\":\"chat\"} suffix"), {"action": "chat"})
        self.assertEqual(router_safe_json("[1, 2]"), {})
        self.assertEqual(router_safe_json("not json"), {})

    def test_quality_mode_defaults_to_fast(self) -> None:
        self.assertEqual(quality_mode_from_decision({"quality_mode": "quality"}), "quality")
        self.assertEqual(quality_mode_from_decision({"quality_mode": "slow"}), "fast")
        self.assertEqual(quality_mode_from_decision(None), "fast")

    def test_build_agent_trace_payload_includes_context_and_outputs(self) -> None:
        req = type("Req", (), {"vision_enabled": True})()
        context = {
            "attached_images": ["input.png"],
            "project_file_candidates": [{"path": str(i)} for i in range(10)],
            "latest_active_image": "latest.png",
        }
        decision = direct_agent_trace_decision(
            "make it",
            "generate_image",
            "generate_image",
            source="attached_image",
        )
        trace = build_agent_trace_payload(
            req,
            ("provider", "model"),
            {"vision_reason": "enabled"},
            context,
            decision,
            {"tool": "generate_image", "result": {"image_path": "out.png"}},
        )

        self.assertEqual(trace["provider"], "provider")
        self.assertEqual(trace["model"], "model")
        self.assertEqual(trace["attached_images"], ["input.png"])
        self.assertEqual(len(trace["project_files"]), 8)
        self.assertEqual(trace["outputs"], ["out.png"])
        self.assertIn("[AGENT_TRACE]", format_agent_trace_block(trace))


if __name__ == "__main__":
    unittest.main()
