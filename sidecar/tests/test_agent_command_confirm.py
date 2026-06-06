import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from routes.chat import (
    _delete_then_create_prompt,
    _extract_confirmed_command,
    _extract_confirmed_delete,
    _extract_confirmed_project_check,
    _extract_delete_continuation,
    _extract_textual_tool_call,
    _extract_textual_tool_calls,
    _format_text_file_create_response,
    _format_delete_then_create_response,
    _format_write_many_files_response,
    _best_tool_result,
    _edit_text_result_can_fallback,
    _is_text_file_edit_followup_intent,
    _remove_internal_source_message,
    _run_direct_text_file_edit,
    _run_textual_tool_call,
    _run_textual_tool_calls,
    _with_delete_continuation,
)
from schemas import ChatRequest
from tools import file_tools


class AgentCommandConfirmTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_confirmed_command_and_cwd(self) -> None:
        self.assertEqual(
            _extract_confirmed_command("确认执行命令：`npm run check`，工作目录：`E:\\ultra\\ultra-studio`"),
            ("npm run check", "E:\\ultra\\ultra-studio"),
        )

    def test_extracts_confirmed_command_without_cwd(self) -> None:
        self.assertEqual(
            _extract_confirmed_command("Confirm running command: `git status`"),
            ("git status", ""),
        )

    def test_extracts_delete_confirmation_with_continuation(self) -> None:
        self.assertEqual(
            _extract_confirmed_delete("确认删除 `C:\\tmp\\snake_game.html`\n\n后续任务：再写一个UI好看一点点的"),
            ("C:\\tmp\\snake_game.html", "再写一个UI好看一点点的"),
        )

    def test_carries_delete_continuation_in_confirmation_card(self) -> None:
        card = "[CONFIRM_DELETE_REQUIRED]\n目标: `C:\\tmp\\a.html`\n[/CONFIRM_DELETE_REQUIRED]"
        updated = _with_delete_continuation(card, "再写一个 UI 更好看的")
        self.assertIn("后续任务: `再写一个 UI 更好看的`", updated)

    def test_delete_then_create_prompt_keeps_original_folder(self) -> None:
        prompt = _delete_then_create_prompt("C:\\tmp\\snake_game.html", "再写一个UI好看一点点的")
        self.assertIn("目标文件名：snake_game.html", prompt)
        self.assertIn("目标文件夹：C:\\tmp", prompt)
        self.assertIn("完整可直接打开运行的单文件 HTML", prompt)

    def test_delete_then_create_response_leads_with_new_file(self) -> None:
        response = _format_delete_then_create_response(
            {"ok": True, "message": "已删除：`C:\\tmp\\old.html`"},
            {
                "ok": True,
                "path": "C:\\tmp\\snake.html",
                "name": "snake.html",
                "files": [{"path": "C:\\tmp\\snake.html"}],
            },
        )

        self.assertTrue(response.startswith("已创建文件：`C:\\tmp\\snake.html`"))
        self.assertIn("旧文件已删除。", response)
        self.assertNotIn("old.html`", response)

    def test_text_file_edit_followup_detects_incremental_game_change(self) -> None:
        self.assertTrue(_is_text_file_edit_followup_intent("加入一个对手"))
        self.assertTrue(_is_text_file_edit_followup_intent("把游戏里的蛇换成白色"))
        self.assertFalse(_is_text_file_edit_followup_intent("重新写一个贪吃蛇小游戏"))
        self.assertFalse(_is_text_file_edit_followup_intent("删除旧的再创建一个新的"))

    def test_edit_text_failure_can_fallback(self) -> None:
        self.assertTrue(_edit_text_result_can_fallback({"ok": False, "error": "未找到要替换的内容"}))
        self.assertTrue(_edit_text_result_can_fallback({"ok": False, "needs_read": True}))
        self.assertFalse(_edit_text_result_can_fallback({"ok": True}))

    async def test_direct_text_file_edit_rewrites_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "snake.html"
            target.write_text("<html><body>snake</body></html>", encoding="utf-8")
            client = AsyncMock()
            client.chat.completions.create.return_value.choices = [
                type(
                    "Choice",
                    (),
                    {
                        "message": type(
                            "Message",
                            (),
                            {"content": '{"content":"<html><body>snake + opponent</body></html>"}'},
                        )()
                    },
                )()
            ]
            req = ChatRequest(conversation_id="conversation", content=f"给 `{target}` 加入一个对手")

            result = await _run_direct_text_file_edit(req, client, "model")

            self.assertTrue(result["ok"])
            self.assertEqual(result["path"], str(target.resolve()))
            self.assertIn("opponent", target.read_text(encoding="utf-8"))
            self.assertEqual(list(Path(temp_dir).glob("*.html")), [target])

    def test_executes_textual_edit_tool_call_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "snake.html"
            target.write_text("if (head.x < 0) head.x = COLS - 1;\n", encoding="utf-8")
            content = (
                '<| | DSML | | tool_calls>\n'
                '<| | DSML | | invoke name="edit_text_file">\n'
                f'<| | DSML | | parameter name="file_path" string="true">{target}</| | DSML | | parameter>\n'
                '<| | DSML | | parameter name="action" string="true">replace</| | DSML | | parameter>\n'
                '<| | DSML | | parameter name="find" string="true">if (head.x < 0) head.x = COLS - 1;</| | DSML | | parameter>\n'
                '<| | DSML | | parameter name="replace" string="true">if (head.x < 0 || head.x >= COLS) endGame();</| | DSML | | parameter>\n'
            )

            parsed = _extract_textual_tool_call(content)
            self.assertIsNotNone(parsed)
            result = _run_textual_tool_call(content)

            self.assertIsNotNone(result)
            self.assertTrue(result[1]["ok"])
            self.assertIn("endGame", target.read_text(encoding="utf-8"))

    def test_extracts_multiple_textual_web_fetch_calls_with_prefix(self) -> None:
        content = (
            "学术网站封锁较严，让我转向科学新闻和开放获取渠道。\n\n"
            '<| | DSML | | tool_calls>\n'
            '<| | DSML | | invoke name="web_fetch">\n'
            '<| | DSML | | parameter name="url" string="true">https://example.com/a</| | DSML | | parameter>\n'
            '</| | DSML | | invoke>\n'
            '<| | DSML | | invoke name="web_fetch">\n'
            '<| | DSML | | parameter name="url" string="true">https://example.com/b</| | DSML | | parameter>\n'
            '</| | DSML | | invoke>\n'
            '</| | DSML | | tool_calls>'
        )

        calls = _extract_textual_tool_calls(content)

        self.assertEqual([tool for tool, _ in calls], ["web_fetch", "web_fetch"])
        self.assertEqual(calls[0][1]["url"], "https://example.com/a")
        self.assertEqual(calls[1][1]["url"], "https://example.com/b")

    def test_extracts_spaced_dsml_tool_syntax_from_model_output(self) -> None:
        content = (
            '< | | DSML | | tool_calls>\n'
            '< | | DSML | | invoke name="web_fetch">\n'
            '< | | DSML | | parameter name="max_chars" string="false">10000</ | | DSML | | parameter>\n'
            '< | | DSML | | parameter name="url" string="true">https://arxiv.org/abs/2501.00663</ | | DSML | | parameter>\n'
            '</ | | DSML | | invoke>\n'
            '< | | DSML | | invoke name="web_search">\n'
            '< | | DSML | | parameter name="max_results" string="false">10</ | | DSML | | parameter>\n'
            '< | | DSML | | parameter name="query" string="true">Titans learning memorize test time arxiv 2025</ | | DSML | | parameter>\n'
            '</ | | DSML | | invoke>\n'
            '</ | | DSML | | tool_calls>'
        )

        calls = _extract_textual_tool_calls(content)

        self.assertEqual([tool for tool, _ in calls], ["web_fetch", "web_search"])
        self.assertEqual(calls[0][1]["url"], "https://arxiv.org/abs/2501.00663")
        self.assertEqual(calls[1][1]["query"], "Titans learning memorize test time arxiv 2025")

    def test_runs_textual_web_fetch_without_leaking_dsml(self) -> None:
        content = (
            '<| | DSML | | tool_calls>\n'
            '<| | DSML | | invoke name="web_fetch">\n'
            '<| | DSML | | parameter name="url" string="true">https://example.com/a</| | DSML | | parameter>\n'
            '<| | DSML | | parameter name="max_chars" string="false">15000</| | DSML | | parameter>\n'
            '</| | DSML | | invoke>\n'
            '</| | DSML | | tool_calls>'
        )
        with patch("routes.chat.memory_mgr.handle_web_fetch") as fetch:
            fetch.return_value = {"ok": True, "url": "https://example.com/a", "text": "ok"}

            results = _run_textual_tool_calls(content)

        fetch.assert_called_once_with("https://example.com/a", 15000)
        self.assertEqual(results[0]["tool"], "web_fetch")

    def test_best_tool_result_prefers_later_success(self) -> None:
        results = [
            {"tool": "edit_text_file", "result": {"ok": False, "error": "未找到要替换的内容"}},
            {"tool": "edit_text_file", "result": {"ok": True, "path": "C:\\tmp\\snake.html"}},
        ]

        self.assertTrue(_best_tool_result(results, "edit_text_file")["result"]["ok"])

    def test_textual_tool_call_ignores_markdown_examples(self) -> None:
        content = (
            "Example only:\n"
            "```text\n"
            '<| | DSML | | invoke name="edit_text_file">\n'
            "```"
        )
        self.assertIsNone(_extract_textual_tool_call(content))
        self.assertIsNone(_run_textual_tool_call(content))

    def test_project_check_confirmation_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text("{}", encoding="utf-8")
            result = file_tools.run_project_check(str(root), "auto", confirmed=False)

            self.assertFalse(result["ok"])
            self.assertTrue(result["needs_confirmation"])
            self.assertIn("[CONFIRM_PROJECT_CHECK_REQUIRED]", result["message"])
            self.assertEqual(
                _extract_confirmed_project_check(f"确认项目检查：`{root}`，类型：`auto`"),
                (str(root), "auto"),
            )

    def test_partial_file_create_response_reports_written_and_errors(self) -> None:
        response = _format_text_file_create_response(
            {
                "ok": False,
                "files": [{"path": "C:\\tmp\\index.html"}],
                "error_count": 1,
                "errors": [{"path": "bad.exe", "error": "blocked"}],
            }
        )
        self.assertIn("C:\\tmp\\index.html", response)
        self.assertIn("blocked", response)

    def test_write_many_files_response_reports_partial_errors(self) -> None:
        response = _format_write_many_files_response(
            {
                "ok": False,
                "files": [{"path": "C:\\tmp\\index.html"}],
                "error_count": 1,
                "errors": [{"path": "C:\\tmp\\bad.exe", "error": "blocked extension"}],
            }
        )

        self.assertIn("C:\\tmp\\index.html", response)
        self.assertIn("blocked extension", response)

    async def test_hidden_internal_action_removes_source_assistant_message(self) -> None:
        db = AsyncMock()
        req = ChatRequest(
            conversation_id="conversation",
            content="internal",
            hidden_user_message=True,
            remove_message_id="assistant-message",
        )

        await _remove_internal_source_message(db, req)

        db.execute.assert_awaited_once()
        args = db.execute.await_args.args
        self.assertIn("DELETE FROM stm_entries", args[0])
        self.assertEqual(args[1], ("assistant-message", "conversation"))
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
