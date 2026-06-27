from fastapi import APIRouter

from services.mcp_tools import McpValidationError, call_mcp_tool, list_mcp_tools

router = APIRouter()


def _jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


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
                "serverInfo": {"name": "ultra-studio-sidecar", "version": "0.7.0"},
                "capabilities": {"tools": {}},
            },
        )

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": list_mcp_tools()})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = call_mcp_tool(name, arguments)
        except KeyError:
            return _jsonrpc_error(request_id, -32601, f"Tool not supported yet: {name}")
        except McpValidationError as e:
            return _jsonrpc_error(request_id, -32602, str(e))
        return _jsonrpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": result.get("message", f"{name} completed")}],
                "structuredContent": result,
                "isError": result.get("status") == "error",
            },
        )

    return _jsonrpc_error(request_id, -32601, f"Unsupported MCP method: {method}")
