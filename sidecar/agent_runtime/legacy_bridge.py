from typing import Any

from memory import manager as memory_mgr
from memory.memory_map import build_file_tools_definition, build_web_tools_definition

from agent_runtime.models import ToolDefinition
from agent_runtime.tools import ToolRegistry

READ_ONLY_FILE_TOOLS = {
    "read_document",
    "read_many_files",
    "list_directory",
    "search_files",
}


def _definitions(tools: list[dict[str, Any]], capability: str):
    for tool in tools:
        function = tool.get("function") or {}
        name = str(function.get("name") or "")
        if capability == "files" and name not in READ_ONLY_FILE_TOOLS:
            continue
        yield ToolDefinition(
            name=name,
            description=str(function.get("description") or name),
            parameters=function.get("parameters") or {"type": "object", "properties": {}},
            capability=capability,
        )


def build_read_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    handlers = {
        "read_document": lambda args: memory_mgr.handle_read_document(
            str(args["file_path"]), int(args.get("max_chars", 12000))
        ),
        "read_many_files": lambda args: memory_mgr.handle_read_many_files(
            list(args["file_paths"]),
            int(args.get("max_chars_per_file", 8000)),
            int(args.get("max_files", 12)),
        ),
        "list_directory": lambda args: memory_mgr.handle_list_directory(
            str(args["directory_path"]),
            bool(args.get("recursive", False)),
            int(args.get("max_items", 120)),
        ),
        "search_files": lambda args: memory_mgr.handle_search_files(
            str(args["directory_path"]),
            str(args["query"]),
            str(args.get("file_glob", "*")),
            bool(args.get("recursive", True)),
            bool(args.get("search_content", True)),
            int(args.get("max_matches", 80)),
        ),
        "web_search": lambda args: memory_mgr.handle_web_search(
            str(args["query"]),
            int(args.get("max_results", 5)),
            args.get("recency_days"),
            list(args.get("domains") or []),
        ),
        "web_fetch": lambda args: memory_mgr.handle_web_fetch(
            str(args["url"]), int(args.get("max_chars", 12000))
        ),
    }
    definitions = [
        *_definitions(build_file_tools_definition(), "files"),
        *_definitions(build_web_tools_definition(), "web"),
    ]
    for definition in definitions:
        registry.register(definition, handlers[definition.name], risk="read")
    return registry
