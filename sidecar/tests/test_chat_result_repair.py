import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from schemas import ChatRequest
from services.chat_result_repair import repair_text_create_result, repair_text_edit_result


class ChatResultRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_repair_text_create_result_rewrites_missing_file(self) -> None:
        req = ChatRequest(conversation_id="conv", content="创建一个 README 文件")
        bad_result = {
            "ok": True,
            "files": [{"path": "C:/definitely/missing/ultra-studio-readme.md"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            repaired_path = Path(tmp) / "README.md"
            repaired_path.write_text("# Ultra\n", encoding="utf-8")
            repaired_payload = {"ok": True, "files": [{"path": str(repaired_path)}]}

            with patch(
                "services.chat_result_repair.run_direct_text_file_create",
                new=AsyncMock(return_value=repaired_payload),
            ) as repair:
                repaired, repair_record = await repair_text_create_result(
                    req,
                    object(),
                    "model",
                    ("p", "model"),
                    bad_result,
                    prompt_override="创建一个 README 文件",
                )

        repair.assert_awaited_once()
        self.assertEqual(repaired, repaired_payload)
        self.assertIsNotNone(repair_record)
        self.assertEqual(repair_record["repair_of"], bad_result)

    async def test_repair_text_create_result_skips_accepted_result(self) -> None:
        req = ChatRequest(conversation_id="conv", content="创建一个 README 文件")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "README.md"
            path.write_text("# Ultra\n", encoding="utf-8")
            good_result = {"ok": True, "files": [{"path": str(path)}]}

            with patch("services.chat_result_repair.run_direct_text_file_create", new=AsyncMock()) as repair:
                repaired, repair_record = await repair_text_create_result(
                    req,
                    object(),
                    "model",
                    ("p", "model"),
                    good_result,
                )

        repair.assert_not_awaited()
        self.assertEqual(repaired, good_result)
        self.assertIsNone(repair_record)

    async def test_repair_text_create_result_preserves_tool_wrapper(self) -> None:
        req = ChatRequest(conversation_id="conv", content="创建一个 README 文件")
        bad_result = {
            "tool": "create_text_file",
            "result": {"ok": True, "files": [{"path": "C:/definitely/missing/ultra-studio-readme.md"}]},
        }

        with tempfile.TemporaryDirectory() as tmp:
            repaired_path = Path(tmp) / "README.md"
            repaired_path.write_text("# Ultra\n", encoding="utf-8")
            repaired_payload = {"ok": True, "files": [{"path": str(repaired_path)}]}

            with patch(
                "services.chat_result_repair.run_direct_text_file_create",
                new=AsyncMock(return_value=repaired_payload),
            ):
                repaired, repair_record = await repair_text_create_result(
                    req,
                    object(),
                    "model",
                    ("p", "model"),
                    bad_result,
                )

        self.assertEqual(repaired, {"tool": "create_text_file", "result": repaired_payload})
        self.assertIsNotNone(repair_record)

    async def test_repair_text_edit_result_replaces_retryable_failure(self) -> None:
        req = ChatRequest(conversation_id="conv", content="给这个文件加入标题")
        edit_result = {
            "tool": "edit_text_file",
            "result": {"ok": False, "needs_read": True, "path": "C:/tmp/a.txt", "error": "must read first"},
        }
        repaired_payload = {"ok": True, "path": "C:/tmp/a.txt", "changed": True}

        with patch("services.chat_result_repair.run_direct_text_file_edit", new=AsyncMock(return_value=repaired_payload)) as repair:
            repaired, repair_record = await repair_text_edit_result(req, object(), "model", ("p", "model"), edit_result, None)

        repair.assert_awaited_once()
        self.assertEqual(repaired, {"tool": "edit_text_file", "result": repaired_payload})
        self.assertIsNotNone(repair_record)
        self.assertEqual(repair_record["repair_of"], edit_result["result"])

    async def test_repair_text_edit_result_skips_when_write_many_succeeded(self) -> None:
        req = ChatRequest(conversation_id="conv", content="给这个文件加入标题")
        edit_result = {
            "tool": "edit_text_file",
            "result": {"ok": False, "needs_read": True, "path": "C:/tmp/a.txt"},
        }
        write_many_result = {"tool": "write_many_files", "result": {"ok": True}}

        with patch("services.chat_result_repair.run_direct_text_file_edit", new=AsyncMock()) as repair:
            repaired, repair_record = await repair_text_edit_result(
                req,
                object(),
                "model",
                ("p", "model"),
                edit_result,
                write_many_result,
            )

        repair.assert_not_awaited()
        self.assertIsNone(repaired)
        self.assertIsNone(repair_record)

    async def test_repair_text_edit_result_keeps_failure_when_repair_fails(self) -> None:
        req = ChatRequest(conversation_id="conv", content="给这个文件加入标题")
        edit_result = {
            "tool": "edit_text_file",
            "result": {"ok": False, "error": "未找到要替换的内容", "path": "C:/tmp/a.txt"},
        }

        with patch("services.chat_result_repair.run_direct_text_file_edit", new=AsyncMock(return_value={"ok": False})) as repair:
            repaired, repair_record = await repair_text_edit_result(req, object(), "model", ("p", "model"), edit_result, None)

        repair.assert_awaited_once()
        self.assertEqual(repaired, edit_result)
        self.assertIsNotNone(repair_record)


if __name__ == "__main__":
    unittest.main()
