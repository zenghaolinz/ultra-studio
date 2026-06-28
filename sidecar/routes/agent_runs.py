import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent_runtime.legacy_bridge import build_runtime_registry
from agent_runtime.loop import AgentLoop
from agent_runtime.models import AgentRunRequest
from agent_runtime.policy import PermissionPolicy
from agent_runtime.providers import NativeToolProvider
from db.sqlite import get_db
from memory import manager as memory_mgr
from schemas import ChatRequest
from services.chat_messages import (
    remove_internal_source_message,
    save_assistant_message,
    save_visible_user_message,
)
from services.chat_provider_client import get_provider_client
from services.conversation_artifacts import record_uploaded_images
from services.model_context import fit_messages_to_context

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])

FILE_TOOL_NAMES = {
    "read_document", "read_many_files", "list_directory", "search_files",
    "organize_files", "write_many_files", "run_command", "run_project_check",
    "delete_file", "edit_text_file", "create_docx_document", "edit_docx_document",
}
WEB_TOOL_NAMES = {"web_search", "web_fetch"}
GENERATION_TOOL_NAMES = {
    "generate_image",
    "generate_video",
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_fusion",
    "modify_image_with_flux",
    "generate_multiview_images_from_image",
    "generate_3d_from_generated_multiview",
}


def _openai_tools(definitions) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            },
        }
        for definition in definitions
    ]


def _capabilities_for_tools(tools: list[dict]) -> set[str]:
    names = {
        str((tool.get("function") or {}).get("name") or "")
        for tool in tools
    }
    capabilities: set[str] = set()
    if names & FILE_TOOL_NAMES:
        capabilities.add("files")
    if names & WEB_TOOL_NAMES:
        capabilities.add("web")
    if names & GENERATION_TOOL_NAMES:
        capabilities.add("generation")
    return capabilities


def _confirmation_content(tool_call: dict) -> str:
    name = str(tool_call.get("name") or "")
    arguments = tool_call.get("arguments") or {}
    if name == "delete_file":
        return (
            "[CONFIRM_DELETE_REQUIRED]\n"
            f"目标: `{arguments.get('target_path', '')}`\n"
            f"类型: {arguments.get('target_type', 'auto')}\n"
            "提示: 此操作需要确认。\n"
            "[/CONFIRM_DELETE_REQUIRED]"
        )
    if name == "run_command":
        return (
            "[CONFIRM_COMMAND_REQUIRED]\n"
            f"命令: `{arguments.get('command', '')}`\n"
            f"目录: `{arguments.get('cwd', '')}`\n"
            "提示: 此操作需要确认。\n"
            "[/CONFIRM_COMMAND_REQUIRED]"
        )
    if name == "run_project_check":
        return (
            "[CONFIRM_PROJECT_CHECK_REQUIRED]\n"
            f"项目: `{arguments.get('project_path', '')}`\n"
            f"类型: {arguments.get('check_type', 'auto')}\n"
            "提示: 此操作需要确认。\n"
            "[/CONFIRM_PROJECT_CHECK_REQUIRED]"
        )
    return "This action requires confirmation."


async def _register_request_uploads(req: ChatRequest, message_id: str | None, db) -> None:
    if not req.image_paths:
        return
    await record_uploaded_images(
        req.conversation_id,
        req.image_paths,
        message_id=message_id,
        db=db,
    )


async def _prepare_run(req: ChatRequest):
    db = await get_db()
    await remove_internal_source_message(db, req)
    user_message_id = await save_visible_user_message(db, req)
    await _register_request_uploads(req, user_message_id, db)
    client, provider_config = await get_provider_client(db, req.model_id)
    if not client:
        raise HTTPException(status_code=400, detail="No default model configured")
    try:
        context_messages, legacy_tools = await memory_mgr.build_context(
            conversation_id=req.conversation_id,
            user_input=req.content,
            image_paths=req.image_paths,
        )
    except Exception:
        context_messages = [
            {"role": "system", "content": "你是 Ultra Studio 的个人创作助手。"},
            {"role": "user", "content": req.content},
        ]
        legacy_tools = []

    capabilities = _capabilities_for_tools(legacy_tools)
    registry = build_runtime_registry(req.conversation_id, req.permission_mode)
    definitions = registry.definitions(capabilities)
    messages = fit_messages_to_context(
        context_messages,
        provider_config,
        _openai_tools(definitions),
    )
    runtime_request = AgentRunRequest(
        run_id=uuid.uuid4().hex,
        conversation_id=req.conversation_id,
        messages=messages,
        permission_mode=req.permission_mode,
    )
    loop = AgentLoop(NativeToolProvider(), registry, PermissionPolicy())
    return loop, client, provider_config[1], runtime_request, capabilities, db


@router.post("/stream")
async def stream_agent_run(req: ChatRequest):
    loop, client, model_name, runtime_request, capabilities, db = await _prepare_run(req)

    async def event_stream():
        async for event in loop.stream(
            client,
            model_name,
            runtime_request,
            capabilities,
        ):
            if event["type"] == "run.finished":
                data = event["data"]
                if data.get("status") == "confirmation_required":
                    data["content"] = _confirmation_content(data.get("toolCall") or {})
                if data.get("status") in {"completed", "confirmation_required"} and data.get("content"):
                    message_id, created_at = await save_assistant_message(
                        db,
                        req.conversation_id,
                        data["content"],
                    )
                    data["messageId"] = message_id
                    data["createdAt"] = created_at
                print(
                    "[agent-runtime] "
                    + json.dumps(
                        {
                            "runId": event["runId"],
                            "status": data.get("status"),
                            "metrics": data.get("metrics", {}),
                        },
                        ensure_ascii=False,
                    )
                )
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
