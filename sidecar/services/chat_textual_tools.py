import json

from memory import manager as memory_mgr
from services.chat_response_formatters import format_textual_tool_direct_response
from services.textual_tool_parser import (
    SUPPORTED_TEXTUAL_TOOL_NAMES,
    extract_textual_tool_calls,
    parse_textual_bool,
    parse_textual_int,
    parse_textual_json,
    parse_textual_optional_int,
)


def run_textual_tool_calls(content: str) -> list[dict]:
    results = []
    for tool_name, args in extract_textual_tool_calls(content):
        if tool_name not in SUPPORTED_TEXTUAL_TOOL_NAMES:
            continue
        if tool_name == "edit_text_file":
            if not args.get("file_path") or not args.get("action"):
                continue
            result = memory_mgr.handle_edit_text_file(
                args.get("file_path", ""),
                args.get("action", "replace"),
                args.get("text", ""),
                args.get("find", ""),
                args.get("replace", ""),
                parse_textual_bool(args.get("use_regex")),
                parse_textual_bool(args.get("backup")),
            )
        elif tool_name == "web_search":
            result = memory_mgr.handle_web_search(
                args.get("query", ""),
                parse_textual_int(args.get("max_results"), 5),
                parse_textual_optional_int(args.get("recency_days")),
                parse_textual_json(args.get("domains"), []),
            )
        elif tool_name == "web_fetch":
            result = memory_mgr.handle_web_fetch(
                args.get("url", ""),
                parse_textual_int(args.get("max_chars"), 12000),
            )
        elif tool_name == "read_document":
            result = memory_mgr.handle_read_document(
                args.get("file_path", ""),
                parse_textual_int(args.get("max_chars"), 12000),
            )
        elif tool_name == "read_many_files":
            result = memory_mgr.handle_read_many_files(
                parse_textual_json(args.get("file_paths"), []),
                parse_textual_int(args.get("max_chars_per_file"), 8000),
                parse_textual_int(args.get("max_files"), 12),
            )
        elif tool_name == "list_directory":
            result = memory_mgr.handle_list_directory(
                args.get("directory_path", ""),
                parse_textual_bool(args.get("recursive")),
                parse_textual_int(args.get("max_items"), 120),
            )
        elif tool_name == "search_files":
            result = memory_mgr.handle_search_files(
                args.get("directory_path", ""),
                args.get("query", ""),
                args.get("file_glob", "*"),
                parse_textual_bool(args.get("recursive") or "true"),
                parse_textual_bool(args.get("search_content") or "true"),
                parse_textual_int(args.get("max_matches"), 80),
            )
        elif tool_name == "write_many_files":
            result = memory_mgr.handle_write_many_files(
                args.get("root_path", ""),
                parse_textual_json(args.get("files"), []),
                parse_textual_bool(args.get("overwrite")),
            )
        results.append({"tool": tool_name, "result": result})
    return results


def run_textual_tool_call(content: str) -> tuple[str, dict] | None:
    for item in run_textual_tool_calls(content):
        if item.get("tool") == "edit_text_file":
            return item["tool"], item["result"]
    return None


async def answer_from_textual_tool_results(client, model_name: str, messages: list, user_content: str, tool_results: list[dict]) -> str:
    direct_tools = {"edit_text_file", "write_many_files"}
    if any(item.get("tool") in direct_tools for item in tool_results):
        return format_textual_tool_direct_response(tool_results)
    tool_payload = json.dumps(tool_results, ensure_ascii=False)[:30000]
    response = await client.chat.completions.create(
        model=model_name,
        messages=messages
        + [
            {
                "role": "system",
                "content": (
                    "上一条 assistant 内容包含文本化 DSML 工具调用，系统已代为执行。"
                    "请基于下面工具结果直接回答用户原始问题。不要输出 DSML、XML、JSON 或工具调用语法；"
                    "如果结果来自网页，请用中文总结并保留关键来源名称或链接。"
                    f"\n\n用户原始问题：{user_content}\n\n工具结果：{tool_payload}"
                ),
            }
        ],
    )
    return (response.choices[0].message.content or "").strip() or format_textual_tool_direct_response(tool_results)
