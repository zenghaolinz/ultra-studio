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
from schemas import ChatRequest
from services.chat_messages import (
    remove_internal_source_message,
    save_assistant_message,
    save_visible_user_message,
)
from services.chat_provider_client import get_provider_client
from services.artifact_references import build_artifact_context, resolve_artifact_references
from services.conversation_artifacts import (
    artifact_kind_for_path,
    backfill_generation_artifacts,
    list_artifacts,
    record_uploaded_artifacts,
    record_tool_outputs,
)
from services.agent_context import build_agent_context, infer_agent_capabilities
from services.chat_router import model_capabilities
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


def _capabilities_for_tools(
    tools: list[dict],
    *,
    has_resolved_images: bool = False,
) -> set[str]:
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
    if has_resolved_images:
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
    if not req.all_attachment_paths:
        return
    await record_uploaded_artifacts(
        req.conversation_id,
        req.all_attachment_paths,
        message_id=message_id,
        db=db,
    )


async def _artifact_context_for_request(req: ChatRequest, db):
    await backfill_generation_artifacts(req.conversation_id, db=db)
    artifacts = await list_artifacts(
        req.conversation_id,
        db=db,
    )
    resolved = resolve_artifact_references(req.content, artifacts)
    return build_artifact_context(resolved, artifacts), resolved


def _append_system_context(messages: list[dict], context: str) -> list[dict]:
    if not context:
        return messages
    updated = [dict(message) for message in messages]
    for message in updated:
        if message.get("role") == "system" and isinstance(message.get("content"), str):
            message["content"] = message["content"] + "\n\n" + context
            return updated
    return [{"role": "system", "content": context}, *updated]


def _adapt_messages_for_model(messages: list[dict], *, supports_vision: bool) -> list[dict]:
    if supports_vision:
        return messages
    adapted = []
    for message in messages:
        updated = dict(message)
        content = updated.get("content")
        if isinstance(content, list):
            text_parts = [
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            updated["content"] = "\n".join(part for part in text_parts if part)
        adapted.append(updated)
    return adapted


async def _project_tool_artifacts(event: dict, conversation_id: str, db) -> None:
    if event.get("type") != "tool.finished":
        return
    data = event.get("data") or {}
    if data.get("isError"):
        return
    await record_tool_outputs(
        conversation_id,
        tool_call_id=str(data.get("toolCallId") or ""),
        tool_name=str(data.get("name") or ""),
        result=data.get("result"),
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
    supports_vision = model_capabilities(
        provider_config,
        req.vision_enabled,
    )["supports_vision"]
    context_messages = await build_agent_context(
        db,
        conversation_id=req.conversation_id,
        user_input=req.content,
        current_message_id=user_message_id,
        attachment_paths=req.all_attachment_paths,
        include_image_content=supports_vision,
    )

    artifact_context, resolved_artifacts = await _artifact_context_for_request(req, db)
    context_messages = _append_system_context(context_messages, artifact_context)
    context_messages = _adapt_messages_for_model(
        context_messages,
        supports_vision=supports_vision,
    )
    capabilities = infer_agent_capabilities(
        req.content,
        attachment_kinds={artifact_kind_for_path(path) for path in req.all_attachment_paths},
        resolved_kinds={str(artifact.get("kind") or "") for artifact in resolved_artifacts},
    )
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
            await _project_tool_artifacts(event, req.conversation_id, db)
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
