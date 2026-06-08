import sys
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.chat_textual_tools import answer_from_textual_tool_results, run_textual_tool_calls


class ChatTextualToolsTests(unittest.IsolatedAsyncioTestCase):
    def test_run_textual_tool_calls_dispatches_web_search(self) -> None:
        content = (
            '<| | DSML | | tool_calls>\n'
            '<| | DSML | | invoke name="web_search">\n'
            '<| | DSML | | parameter name="query" string="true">cats</| | DSML | | parameter>\n'
            '<| | DSML | | parameter name="max_results" string="false">2</| | DSML | | parameter>\n'
            '</| | DSML | | invoke>\n'
            '</| | DSML | | tool_calls>'
        )
        with patch("services.chat_textual_tools.memory_mgr.handle_web_search") as search:
            search.return_value = {"ok": True, "results": []}

            results = run_textual_tool_calls(content)

        search.assert_called_once_with("cats", 2, None, [])
        self.assertEqual(results[0]["tool"], "web_search")

    async def test_answer_from_textual_tool_results_returns_direct_file_response(self) -> None:
        client = AsyncMock()

        response = await answer_from_textual_tool_results(
            client,
            "model",
            [],
            "write file",
            [{"tool": "write_many_files", "result": {"ok": True, "files": [{"path": "a.txt"}]}}],
        )

        self.assertIn("a.txt", response)
        client.chat.completions.create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
