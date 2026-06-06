import unittest
from unittest.mock import patch

from sidecar.services import generation_runtime


class GenerationRuntimeTests(unittest.TestCase):
    def test_external_profile_requires_manual_start(self) -> None:
        status = {
            "running": False,
            "ready": False,
            "launch_mode": "external",
            "configured_path": "E:/ComfyUI Desktop",
        }
        with patch.object(generation_runtime, "get_status", return_value=status), patch.object(
            generation_runtime,
            "start_comfyui",
            side_effect=AssertionError("Desktop/external mode must not auto-start"),
        ):
            result = generation_runtime.ensure_comfyui_ready()

        self.assertFalse(result["ok"])
        self.assertTrue(result["manual_start_required"])
        self.assertIn("Desktop", result["message"])

    def test_missing_path_requires_configuration(self) -> None:
        status = {
            "running": False,
            "ready": False,
            "launch_mode": "portable",
            "configured_path": "",
        }
        with patch.object(generation_runtime, "get_status", return_value=status):
            result = generation_runtime.ensure_comfyui_ready()

        self.assertFalse(result["ok"])
        self.assertTrue(result["manual_start_required"])
        self.assertIn("尚未配置", result["message"])

    def test_portable_profile_attempts_start(self) -> None:
        stopped = {
            "running": False,
            "ready": False,
            "launch_mode": "portable",
            "configured_path": "E:/ComfyUI_windows_portable",
        }
        running = {**stopped, "running": True, "ready": True}
        with patch.object(generation_runtime, "is_valid_comfyui_path", return_value=True), patch.object(
            generation_runtime,
            "get_status",
            side_effect=[stopped, running],
        ), patch.object(generation_runtime, "start_comfyui", return_value=True) as start:
            result = generation_runtime.ensure_comfyui_ready(wait_seconds=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["started"])
        start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
