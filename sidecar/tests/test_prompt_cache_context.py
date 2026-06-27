import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from memory import manager


class PromptCacheContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_memory_map_follows_stable_agent_instructions(self) -> None:
        db = AsyncMock()
        db.execute_fetchall.return_value = []

        with patch.object(manager, "get_db", AsyncMock(return_value=db)), patch.object(
            manager.stm, "get_recent_all_entries", AsyncMock(return_value=[])
        ), patch.object(
            manager, "load_map", side_effect=[{"branch": "one"}, {"branch": "two"}]
        ), patch.object(
            manager, "build_map_text", side_effect=["MAP ONE", "MAP TWO"]
        ):
            first_messages, first_tools = await manager.build_context(
                "conversation", "生成图片", tool_scope="3d"
            )
            second_messages, second_tools = await manager.build_context(
                "conversation", "生成图片", tool_scope="3d"
            )

        first_system = first_messages[0]["content"]
        second_system = second_messages[0]["content"]
        marker = "<记忆地图>"

        self.assertIn("## 本地文件与文档能力", first_system)
        self.assertGreater(first_system.index(marker), first_system.index("## 本地文件与文档能力"))
        self.assertEqual(first_system.split(marker, 1)[0], second_system.split(marker, 1)[0])
        self.assertNotEqual(first_system, second_system)
        self.assertEqual(first_tools, second_tools)

    async def test_web_tools_keep_cacheable_schema_stable_across_memory_maps(self) -> None:
        db = AsyncMock()
        db.execute_fetchall.return_value = []

        with patch.object(manager, "get_db", AsyncMock(return_value=db)), patch.object(
            manager.stm, "get_recent_all_entries", AsyncMock(return_value=[])
        ), patch.object(
            manager, "load_map", side_effect=[{"branch": "one"}, {"branch": "two"}]
        ), patch.object(
            manager, "build_map_text", side_effect=["MAP ONE", "MAP TWO"]
        ):
            first_messages, first_tools = await manager.build_context(
                "conversation", "search the latest OpenAI news", tool_scope="web"
            )
            second_messages, second_tools = await manager.build_context(
                "conversation", "search the latest OpenAI news", tool_scope="web"
            )

        first_system = first_messages[0]["content"]
        second_system = second_messages[0]["content"]
        marker = "MAP ONE"
        tool_names = [tool["function"]["name"] for tool in first_tools]

        self.assertIn("Web search capability", first_system)
        self.assertGreater(first_system.index(marker), first_system.index("Web search capability"))
        self.assertIn("web_search", tool_names)
        self.assertIn("web_fetch", tool_names)
        self.assertEqual(first_system.split("MAP ONE", 1)[0], second_system.split("MAP TWO", 1)[0])
        self.assertNotEqual(first_system, second_system)
        self.assertEqual(first_tools, second_tools)

    async def test_agent_file_tools_keep_schema_stable_across_memory_maps(self) -> None:
        db = AsyncMock()
        db.execute_fetchall.return_value = []

        with patch.object(manager, "get_db", AsyncMock(return_value=db)), patch.object(
            manager.stm, "get_recent_all_entries", AsyncMock(return_value=[])
        ), patch.object(
            manager, "load_map", side_effect=[{"branch": "one"}, {"branch": "two"}]
        ), patch.object(
            manager, "build_map_text", side_effect=["MAP ONE", "MAP TWO"]
        ):
            first_messages, first_tools = await manager.build_context(
                "conversation", "运行 npm run check", tool_scope="file"
            )
            second_messages, second_tools = await manager.build_context(
                "conversation", "运行 npm run check", tool_scope="file"
            )

        first_system = first_messages[0]["content"]
        second_system = second_messages[0]["content"]
        tool_names = [tool["function"]["name"] for tool in first_tools]

        self.assertGreater(first_system.index("MAP ONE"), first_system.index("## 本地文件与文档能力"))
        self.assertIn("read_many_files", tool_names)
        self.assertIn("search_files", tool_names)
        self.assertIn("write_many_files", tool_names)
        self.assertIn("run_command", tool_names)
        self.assertIn("run_project_check", tool_names)
        self.assertEqual(first_system.split("MAP ONE", 1)[0], second_system.split("MAP TWO", 1)[0])
        self.assertEqual(first_tools, second_tools)

    def test_latest_or_search_intent_uses_web_scope(self) -> None:
        self.assertEqual(manager.infer_tool_scope("帮我搜索一下最新价格"), "web")
        self.assertEqual(manager.infer_tool_scope("search today's news"), "web")

    def test_project_search_intent_prefers_file_scope(self) -> None:
        self.assertEqual(manager.infer_tool_scope("search project for create_text_file"), "file")
        self.assertEqual(manager.infer_tool_scope("find where used run_command in repo"), "file")

    def test_explicit_local_path_or_chinese_read_request_uses_file_scope(self) -> None:
        self.assertEqual(
            manager.infer_tool_scope(r"请读取 E:\projects\demo\agent.md 的第一行"),
            "file",
        )
        self.assertEqual(manager.infer_tool_scope("请读取这个文件并总结"), "file")

    def test_normal_chinese_requests_select_expected_runtime_capability(self) -> None:
        self.assertEqual(manager.infer_tool_scope("帮我搜索一下最新价格"), "web")
        self.assertEqual(manager.infer_tool_scope("生成一张玻璃狐狸图片"), "3d")
        self.assertEqual(manager.infer_tool_scope("删除这个文件"), "file")
        self.assertEqual(manager.infer_tool_scope("运行 npm test"), "file")

    def test_runtime_rejects_unknown_branch_after_schema_is_stabilized(self) -> None:
        map_data = {"个人": {"branches": {"喜好偏好": "用户偏好"}}}
        with patch.object(manager, "load_map", return_value=map_data):
            result = manager.handle_save_memory("test", "个人/不存在")

        self.assertFalse(result["ok"])
        self.assertIn("Unknown branch", result["error"])


if __name__ == "__main__":
    unittest.main()
