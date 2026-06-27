from typing import Any

from memory import manager as memory_mgr
from memory.memory_map import (
    build_3d_tools_definition,
    build_file_tools_definition,
    build_web_tools_definition,
)
from services.mcp_tools import call_mcp_tool

from agent_runtime.models import ToolDefinition
from agent_runtime.tools import ToolRegistry

READ_ONLY_FILE_TOOLS = {
    "read_document",
    "read_many_files",
    "list_directory",
    "search_files",
}
MUTATING_FILE_TOOLS = {
    "organize_files",
    "write_many_files",
    "run_command",
    "run_project_check",
    "delete_file",
    "edit_text_file",
    "create_docx_document",
    "edit_docx_document",
}
DESTRUCTIVE_FILE_TOOLS = {"run_command", "run_project_check", "delete_file"}


def _definitions(
    tools: list[dict[str, Any]],
    capability: str,
    allowed_names: set[str] | None = None,
):
    for tool in tools:
        function = tool.get("function") or {}
        name = str(function.get("name") or "")
        if allowed_names is not None and name not in allowed_names:
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
        *_definitions(build_file_tools_definition(), "files", READ_ONLY_FILE_TOOLS),
        *_definitions(build_web_tools_definition(), "web"),
    ]
    for definition in definitions:
        registry.register(definition, handlers[definition.name], risk="read")
    return registry


def build_runtime_registry(
    conversation_id: str | None = None,
    permission_mode: str = "standard",
) -> ToolRegistry:
    registry = build_read_only_registry()
    mutation_handlers = {
        "organize_files": lambda args: memory_mgr.handle_organize_files(
            str(args["directory_path"]),
            str(args.get("strategy", "by_type")),
            bool(args.get("apply_changes", False)),
            bool(args.get("recursive", False)),
        ),
        "write_many_files": lambda args: memory_mgr.handle_write_many_files(
            str(args["root_path"]), list(args["files"]), bool(args.get("overwrite", False))
        ),
        "run_command": lambda args: memory_mgr.handle_run_command(
            str(args["command"]), str(args.get("cwd", "")),
            str(args.get("shell", "powershell")), int(args.get("timeout_seconds", 60)),
            bool(args.get("confirmed", False)), permission_mode,
        ),
        "run_project_check": lambda args: memory_mgr.handle_run_project_check(
            str(args["project_path"]), str(args.get("check_type", "auto")),
            int(args.get("timeout_seconds", 180)), bool(args.get("confirmed", False)),
            permission_mode,
        ),
        "delete_file": lambda args: memory_mgr.handle_delete_path(
            str(args["target_path"]), str(args.get("target_type", "auto")),
            bool(args.get("recursive", False)), bool(args.get("confirmed", False)),
            permission_mode,
        ),
        "edit_text_file": lambda args: memory_mgr.handle_edit_text_file(
            str(args["file_path"]), str(args["action"]), str(args.get("text", "")),
            str(args.get("find", "")), str(args.get("replace", "")),
            bool(args.get("use_regex", False)), bool(args.get("backup", False)),
        ),
        "create_docx_document": lambda args: memory_mgr.handle_create_docx_document(
            str(args["file_path"]), str(args.get("title", "")),
            list(args.get("paragraphs") or []), bool(args.get("overwrite", False)),
        ),
        "edit_docx_document": lambda args: memory_mgr.handle_edit_docx_document(
            str(args["file_path"]), str(args["action"]), str(args.get("text", "")),
            str(args.get("find", "")), str(args.get("replace", "")),
            bool(args.get("backup", False)),
        ),
    }
    for definition in _definitions(
        build_file_tools_definition(), "files", MUTATING_FILE_TOOLS
    ):
        risk = "destructive" if definition.name in DESTRUCTIVE_FILE_TOOLS else "write"
        registry.register(definition, mutation_handlers[definition.name], risk=risk)
    for definition in _definitions(build_3d_tools_definition(), "generation"):
        def execute(arguments: dict[str, Any], *, tool_name: str = definition.name):
            contextual_arguments = dict(arguments)
            if conversation_id and "conversation_id" not in contextual_arguments:
                contextual_arguments["conversation_id"] = conversation_id
            return call_mcp_tool(tool_name, contextual_arguments)

        registry.register(definition, execute, risk="write")
    return registry
