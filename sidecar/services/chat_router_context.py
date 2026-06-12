from schemas import ChatRequest
from services.chat_generation_context import (
    find_latest_edit_source_image,
    find_latest_multiview_paths,
)
from services.chat_paths import document_attachments, image_attachments
from services.chat_project_files import (
    project_document_paths,
    project_file_candidates,
    project_image_paths,
)
from services.chat_router import (
    build_agent_trace_payload,
    direct_agent_trace_decision,
    format_agent_trace_block,
    model_capabilities,
)


async def build_router_context(req: ChatRequest, capabilities: dict | None = None) -> dict:
    latest_image = await find_latest_edit_source_image(req.conversation_id)
    latest_multiview = await find_latest_multiview_paths(req.conversation_id)
    image_paths = image_attachments(req.image_paths)
    document_paths = document_attachments(req.image_paths)
    project_documents = []
    project_images = []
    project_files = []
    if req.project_path:
        project_documents = project_document_paths(req.project_path, req.content)[:5]
        project_images = project_image_paths(req.project_path, req.content)[:5]
        project_files = project_file_candidates(req.project_path, req.content)[:20]
    return {
        "permission_mode": req.permission_mode,
        "project_path": req.project_path or "",
        "model_capabilities": capabilities or {},
        "attached_images": image_paths,
        "attached_documents": document_paths,
        "project_document_candidates": project_documents,
        "project_image_candidates": project_images,
        "project_file_candidates": project_files,
        "latest_active_image": latest_image or "",
        "has_latest_active_image": bool(latest_image),
        "latest_multiview": latest_multiview or {},
        "has_latest_multiview": bool(latest_multiview),
    }


async def agent_trace_block(
    req: ChatRequest,
    provider_config,
    decision: dict | None,
    routed_result: dict | str | None,
) -> str:
    capabilities = model_capabilities(provider_config, req.vision_enabled)
    context = await build_router_context(req, capabilities)
    trace = build_agent_trace_payload(req, provider_config, capabilities, context, decision, routed_result)
    return format_agent_trace_block(trace)


async def direct_agent_trace_block(
    req: ChatRequest,
    provider_config,
    action: str,
    tool: str,
    result: dict | None = None,
    reason: str = "",
    source: str = "direct",
    source_files: list[str] | None = None,
) -> str:
    decision = direct_agent_trace_decision(req.content, action, tool, reason, source, source_files)
    routed_result = {"tool": tool, "result": result or {}}
    return await agent_trace_block(req, provider_config, decision, routed_result)
