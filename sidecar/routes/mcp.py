from fastapi import APIRouter

from memory.memory_map import build_3d_tools_definition
from memory import manager as memory_mgr

router = APIRouter()


def _jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _mcp_tool_from_openai_tool(tool: dict) -> dict:
    function = tool.get("function") or {}
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "inputSchema": function.get("parameters") or {"type": "object", "properties": {}},
    }


@router.post("")
async def mcp_jsonrpc(body: dict):
    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "ultra-studio-sidecar", "version": "0.6.10"},
                "capabilities": {"tools": {}},
            },
        )

    if method == "tools/list":
        tools = [_mcp_tool_from_openai_tool(tool) for tool in build_3d_tools_definition()]
        return _jsonrpc_result(request_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "generate_video":
            result = memory_mgr.handle_generate_video(
                arguments.get("prompt", ""),
                arguments.get("image_path") or None,
                arguments.get("quality_mode", "quality"),
                int(arguments.get("duration_seconds", 4)),
                int(arguments.get("width", 1024)),
                int(arguments.get("height", 576)),
                arguments.get("conversation_id") or None,
            )
            return _jsonrpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": result.get("message", "Video generation queued")}],
                    "structuredContent": result,
                    "isError": result.get("status") == "error",
                },
            )
        return _jsonrpc_error(request_id, -32601, f"Tool not supported yet: {name}")

    return _jsonrpc_error(request_id, -32601, f"Unsupported MCP method: {method}")
