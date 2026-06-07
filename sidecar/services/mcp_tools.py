from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from memory import manager as memory_mgr
from memory.memory_map import build_3d_tools_definition


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class McpTool:
    name: str
    metadata: dict[str, Any]
    handler: ToolHandler


class McpValidationError(ValueError):
    pass


def _text_arg(arguments: dict[str, Any], name: str, default: str = "") -> str:
    value = arguments.get(name, default)
    return "" if value is None else str(value)


def _optional_text_arg(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    text = str(value)
    return text or None


def _int_arg(arguments: dict[str, Any], name: str, default: int) -> int:
    try:
        return int(arguments.get(name, default))
    except (TypeError, ValueError):
        return default


def _float_arg(arguments: dict[str, Any], name: str, default: float) -> float:
    try:
        return float(arguments.get(name, default))
    except (TypeError, ValueError):
        return default


def _conversation_id(arguments: dict[str, Any]) -> str | None:
    return _optional_text_arg(arguments, "conversation_id")


def _build_handlers() -> dict[str, ToolHandler]:
    return {
        "generate_image": lambda args: memory_mgr.handle_generate_image(
            _text_arg(args, "prompt"),
            _text_arg(args, "quality_mode", "fast"),
            _conversation_id(args),
        ),
        "generate_video": lambda args: memory_mgr.handle_generate_video(
            _text_arg(args, "prompt"),
            _optional_text_arg(args, "image_path"),
            _text_arg(args, "quality_mode", "quality"),
            _int_arg(args, "duration_seconds", 4),
            _int_arg(args, "width", 1024),
            _int_arg(args, "height", 576),
            _conversation_id(args),
        ),
        "generate_3d_from_text": lambda args: memory_mgr.handle_generate_3d_from_text(
            _text_arg(args, "prompt"),
            _text_arg(args, "quality_mode", "fast"),
            _conversation_id(args),
        ),
        "generate_3d_from_image": lambda args: memory_mgr.handle_generate_3d_from_image(
            _text_arg(args, "image_path"),
            _conversation_id(args),
        ),
        "generate_3d_fusion": lambda args: memory_mgr.handle_generate_3d_fusion(
            _text_arg(args, "image1_path"),
            _text_arg(args, "image2_path"),
            _text_arg(args, "prompt"),
            _conversation_id(args),
        ),
        "modify_image_with_flux": lambda args: memory_mgr.handle_modify_image(
            _text_arg(args, "source_path"),
            _text_arg(args, "modification_prompt"),
            _float_arg(args, "denoise_strength", 0.5),
            _conversation_id(args),
        ),
        "generate_multiview_images_from_image": lambda args: memory_mgr.handle_generate_multiview_images_from_image(
            _text_arg(args, "image_path"),
            _text_arg(args, "quality_mode", "fast"),
            _conversation_id(args),
        ),
        "generate_3d_from_generated_multiview": lambda args: memory_mgr.handle_generate_3d_from_generated_multiview(
            _text_arg(args, "front_path"),
            _text_arg(args, "left_path"),
            _text_arg(args, "back_path"),
            _text_arg(args, "quality_mode", "fast"),
            _conversation_id(args),
        ),
    }


def _mcp_tool_from_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or {}
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "inputSchema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def build_mcp_tool_registry() -> dict[str, McpTool]:
    handlers = _build_handlers()
    registry: dict[str, McpTool] = {}
    for tool in build_3d_tools_definition():
        metadata = _mcp_tool_from_openai_tool(tool)
        name = metadata["name"]
        handler = handlers.get(name)
        if handler:
            registry[name] = McpTool(name=name, metadata=metadata, handler=handler)
    return registry


MCP_TOOL_REGISTRY = build_mcp_tool_registry()


def list_mcp_tools() -> list[dict[str, Any]]:
    return [tool.metadata for tool in MCP_TOOL_REGISTRY.values()]


def _argument_matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return True


def validate_mcp_tool_arguments(tool: McpTool, arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise McpValidationError("Tool arguments must be an object")

    input_schema = tool.metadata.get("inputSchema") or {}
    properties = input_schema.get("properties") or {}
    for field in input_schema.get("required") or []:
        if field not in arguments or arguments.get(field) in (None, ""):
            raise McpValidationError(f"Missing required argument: {field}")

    for field, value in arguments.items():
        field_schema = properties.get(field)
        if not isinstance(field_schema, dict):
            continue
        enum_values = field_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise McpValidationError(f"Invalid value for {field}: expected one of {enum_values}")
        schema_type = field_schema.get("type")
        if isinstance(schema_type, str) and not _argument_matches_type(value, schema_type):
            raise McpValidationError(f"Invalid type for {field}: expected {schema_type}")
        minimum = field_schema.get("minimum")
        if minimum is not None and isinstance(value, (int, float)) and value < minimum:
            raise McpValidationError(f"Invalid value for {field}: must be >= {minimum}")
        maximum = field_schema.get("maximum")
        if maximum is not None and isinstance(value, (int, float)) and value > maximum:
            raise McpValidationError(f"Invalid value for {field}: must be <= {maximum}")


def call_mcp_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    tool = MCP_TOOL_REGISTRY.get(name)
    if not tool:
        raise KeyError(name)
    safe_arguments = arguments or {}
    validate_mcp_tool_arguments(tool, safe_arguments)
    return tool.handler(safe_arguments)
