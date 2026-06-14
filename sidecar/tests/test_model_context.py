import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.model_context import (
    context_spec_from_provider_config,
    estimate_messages_tokens,
    fit_messages_to_context,
    infer_context_window,
)


class ModelContextTests(unittest.TestCase):
    def test_configured_context_window_overrides_inference(self) -> None:
        spec = context_spec_from_provider_config(("local", "unknown-model", "", "", 12_288))

        self.assertEqual(spec.context_window, 12_288)
        self.assertEqual(spec.source, "configured")

    def test_infers_common_context_windows(self) -> None:
        self.assertEqual(infer_context_window("openai", "gpt-4o"), 128_000)
        self.assertEqual(infer_context_window("deepseek", "deepseek-r1"), 64_000)
        self.assertEqual(infer_context_window("ollama", "llama3.1:8k"), 8_192)

    def test_fit_messages_compresses_old_history_under_budget(self) -> None:
        messages = [{"role": "system", "content": "system rules"}]
        for index in range(20):
            messages.append({"role": "user", "content": f"old message {index} " + ("x" * 1200)})
            messages.append({"role": "assistant", "content": f"old answer {index} " + ("y" * 1200)})
        messages.append({"role": "user", "content": "latest request"})

        fitted = fit_messages_to_context(messages, ("local", "tiny", "", "", 4096), response_reserve_tokens=512)

        self.assertLessEqual(estimate_messages_tokens(fitted), 4096 - 512)
        self.assertEqual(fitted[0]["role"], "system")
        self.assertEqual(fitted[-1]["content"], "latest request")
        self.assertTrue(any("Compressed conversation context" in item.get("content", "") for item in fitted))

    def test_fit_messages_logs_compression_stats(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "x" * 30_000},
            {"role": "user", "content": "latest"},
        ]

        with patch("services.model_context.print") as print_mock:
            fit_messages_to_context(messages, ("local", "tiny", "", "", 4096), response_reserve_tokens=512)

        printed = " ".join(str(arg) for call in print_mock.call_args_list for arg in call.args)
        self.assertIn("[context] compressed", printed)
        self.assertIn("window=4096", printed)


if __name__ == "__main__":
    unittest.main()
