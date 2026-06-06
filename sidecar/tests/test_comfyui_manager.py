import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sidecar.tools import comfyui_manager


class ComfyUiLaunchInfoTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
