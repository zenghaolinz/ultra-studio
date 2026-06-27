import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.policy import PermissionPolicy


class AgentRuntimePolicyTests(unittest.TestCase):
    def test_standard_mode_allows_reads_and_asks_for_destructive_tools(self) -> None:
        policy = PermissionPolicy()

        self.assertEqual(policy.decide("read_file", "read", "standard"), "allow")
        self.assertEqual(policy.decide("delete_file", "destructive", "standard"), "ask")

    def test_explicit_rule_overrides_mode_default(self) -> None:
        policy = PermissionPolicy({"run_command": "deny"})

        self.assertEqual(policy.decide("run_command", "write", "autonomous"), "deny")

    def test_confirmed_destructive_call_is_allowed_in_standard_mode(self) -> None:
        policy = PermissionPolicy()

        self.assertEqual(
            policy.decide(
                "delete_file", "destructive", "standard", {"confirmed": True}
            ),
            "allow",
        )


if __name__ == "__main__":
    unittest.main()
