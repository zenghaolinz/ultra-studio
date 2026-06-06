import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sidecar.tools import comfyui_manager


class ComfyUiLaunchInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(
            comfyui_manager,
            "CONFIG_PATH",
            str(Path(self.temp_dir.name) / "config.ini"),
        )
        self.logs_patch = patch.object(comfyui_manager, "LOGS_DIR", str(Path(self.temp_dir.name) / "logs"))
        self.config_patch.start()
        self.logs_patch.start()
        comfyui_manager._process = None
        comfyui_manager._ready = False
        comfyui_manager._log_lines = []

    def tearDown(self) -> None:
        self.config_patch.stop()
        self.logs_patch.stop()
        self.temp_dir.cleanup()
        comfyui_manager._process = None
        comfyui_manager._ready = False
        comfyui_manager._log_lines = []

    @patch.object(comfyui_manager.sys, "platform", "win32")
    def test_embedded_python_arguments_preserve_paths_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="Ultra Studio ") as temp_dir:
            root = Path(temp_dir)
            main_file = root / "main.py"
            python_file = root / "python_embeded" / "python.exe"
            python_file.parent.mkdir()
            main_file.write_text("", encoding="utf-8")
            python_file.write_bytes(b"")

            command, work_dir, launch_type = comfyui_manager.get_comfyui_launch_info(str(root))

            self.assertIsInstance(command, list)
            self.assertEqual(command[0], os.path.normpath(str(python_file)))
            self.assertEqual(command[2], os.path.normpath(str(main_file)))
            self.assertEqual(work_dir, os.path.normpath(str(root)))
            self.assertEqual(launch_type, "python_embeded")

    def test_external_profile_does_not_attempt_to_launch_when_port_is_closed(self) -> None:
        comfyui_manager.save_comfyui_profile(
            "Desktop",
            str(Path(self.temp_dir.name) / "ComfyUI Desktop"),
            launch_mode="external",
        )

        with patch.object(comfyui_manager, "verify_comfyui_running", return_value=False), patch.object(
            comfyui_manager,
            "get_comfyui_launch_info",
            side_effect=AssertionError("external profiles must not launch"),
        ):
            self.assertFalse(comfyui_manager.start_comfyui())

    def test_unmanaged_running_comfyui_is_reused_not_restarted(self) -> None:
        with patch.object(comfyui_manager, "verify_comfyui_running", return_value=True), patch.object(
            comfyui_manager,
            "stop_comfyui",
            side_effect=AssertionError("unmanaged ComfyUI must not be stopped"),
        ):
            self.assertTrue(comfyui_manager.start_comfyui())
            self.assertTrue(comfyui_manager._ready)

    def test_stop_leaves_unmanaged_comfyui_untouched(self) -> None:
        with patch.object(comfyui_manager, "verify_comfyui_running", return_value=True), patch.object(
            comfyui_manager,
            "_find_pid_on_port",
            side_effect=AssertionError("unmanaged ComfyUI must not be found by port"),
        ):
            comfyui_manager.stop_comfyui()
            self.assertTrue(comfyui_manager._ready)


if __name__ == "__main__":
    unittest.main()
