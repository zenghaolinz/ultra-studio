import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.events import RunEventEmitter, RunMetrics


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class AgentRuntimeEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.metrics = RunMetrics(clock=self.clock)
        self.emitter = RunEventEmitter(
            run_id="run-1",
            conversation_id="conversation-1",
            metrics=self.metrics,
            wall_clock=lambda: "2026-06-27T12:00:00Z",
        )

    def test_events_have_stable_identity_and_increasing_sequence(self) -> None:
        started = self.emitter.emit("run.started", {"mode": "native"})
        self.clock.advance(0.2)
        model = self.emitter.emit("model.started", {"turn": 1})

        self.assertEqual(started["runId"], "run-1")
        self.assertEqual(started["conversationId"], "conversation-1")
        self.assertEqual(started["sequence"], 1)
        self.assertEqual(model["sequence"], 2)
        self.assertEqual(model["timestamp"], "2026-06-27T12:00:00Z")

    def test_metrics_distinguish_provider_and_visible_ttft(self) -> None:
        self.clock.advance(0.1)
        self.metrics.mark_model_started()
        self.clock.advance(0.35)
        self.metrics.mark_provider_signal()
        self.clock.advance(0.05)
        self.metrics.mark_visible_token()
        self.clock.advance(0.5)

        snapshot = self.metrics.finish(model_turns=1, tool_calls=0)

        self.assertAlmostEqual(snapshot["modelStartMs"], 100.0)
        self.assertAlmostEqual(snapshot["providerTtftMs"], 350.0)
        self.assertAlmostEqual(snapshot["applicationTtftMs"], 500.0)
        self.assertAlmostEqual(snapshot["totalMs"], 1000.0)
        self.assertEqual(snapshot["modelTurns"], 1)

    def test_metric_log_contains_no_message_or_secret_fields(self) -> None:
        snapshot = self.metrics.finish(model_turns=1, tool_calls=0)

        self.assertEqual(
            set(snapshot),
            {
                "modelStartMs",
                "providerTtftMs",
                "applicationTtftMs",
                "totalMs",
                "modelTurns",
                "toolCalls",
            },
        )


if __name__ == "__main__":
    unittest.main()
