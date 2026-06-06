import tempfile
import unittest
from pathlib import Path

from sidecar.tools import file_tools


class AgentFileToolsTests(unittest.TestCase):
    def test_read_many_files_and_search_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "a.txt"
            second = root / "nested" / "b.md"
            second.parent.mkdir()
            first.write_text("alpha\nneedle\n", encoding="utf-8")
            second.write_text("beta needle\n", encoding="utf-8")

            read_result = file_tools.read_many_files([str(first), str(second)], max_chars_per_file=20)
            self.assertTrue(read_result["ok"])
            self.assertEqual(read_result["count"], 2)
            self.assertIn("needle", read_result["files"][0]["content"])

            search_result = file_tools.search_files(str(root), "needle", file_glob="*.txt", recursive=True)
            self.assertTrue(search_result["ok"])
            self.assertEqual(search_result["count"], 1)
            self.assertEqual(search_result["matches"][0]["name"], "a.txt")

    def test_write_many_files_normalizes_paths_and_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = file_tools.write_many_files(
                temp_dir,
                [
                    {"path": "index.html", "content": "<main></main>"},
                    {"path": "../escape.exe", "content": "not executable"},
                ],
            )

            self.assertTrue(result["ok"])
            written_names = {Path(item["path"]).name for item in result["files"]}
            self.assertIn("index.html", written_names)
            self.assertIn("escape.txt", written_names)
            self.assertTrue((Path(temp_dir) / "escape.txt").exists())

    def test_run_command_requires_confirmation_and_rejects_dangerous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            needs_confirmation = file_tools.run_command("git status", temp_dir, confirmed=False)
            self.assertFalse(needs_confirmation["ok"])
            self.assertTrue(needs_confirmation["needs_confirmation"])
            self.assertIn("[CONFIRM_COMMAND_REQUIRED]", needs_confirmation["message"])

            dangerous = file_tools.run_command("Remove-Item C:\\temp -Recurse", temp_dir, confirmed=True)
            self.assertFalse(dangerous["ok"])
            self.assertIn("高风险", dangerous["error"])


if __name__ == "__main__":
    unittest.main()
