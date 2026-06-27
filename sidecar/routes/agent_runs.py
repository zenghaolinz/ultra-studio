import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent_runtime.legacy_bridge import build_read_only_registry
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
from services.model_context import fit_messages_to_context

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])


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


async def _prepare_run(req: ChatRequest):
    db = await get_db()
    await remove_internal_source_message(db, req)
    await save_visible_user_message(db, req)
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

    legacy_names = {
        str((tool.get("function") or {}).get("name") or "")
        for tool in legacy_tools
    }
    capabilities: set[str] = set()
    if legacy_names & {"read_document", "read_many_files", "list_directory", "search_files"}:
        capabilities.add("files")
    if legacy_names & {"web_search", "web_fetch"}:
        capabilities.add("web")

    registry = build_read_only_registry()
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
                if data.get("status") == "completed" and data.get("content"):
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
