import json
import re

from services.chat_tool_results import result_output_paths


ROUTER_ACTIONS = {
    "chat",
    "general_tools",
    "generate_image",
    "generate_video",
    "edit_image",
    "generate_3d_text",
    "generate_3d_image",
    "generate_3d_fusion",
    "generate_multiview_images",
    "generate_3d_multiview",
    "project_document_image",
    "project_document_3d",
    "attachment_document_image",
    "attachment_document_3d",
    "read_document",
    "create_docx",
    "edit_docx",
    "folder_summary_docx",
    "create_text_file",
    "choose_implementation",
}


def router_safe_json(text: str) -> dict:
    try:
        payload = json.loads(text or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}


def build_agent_trace_payload(
    req,
    provider_config,
    capabilities: dict,
    context: dict,
    decision: dict | None,
    routed_result: dict | str | None,
) -> dict:
    return {
        "model": provider_config[1] if provider_config else "",
        "provider": provider_config[0] if provider_config else "",
        "vision": bool(req.vision_enabled),
        "vision_reason": capabilities.get("vision_reason", ""),
        "action": (decision or {}).get("action", "chat"),
        "tool": routed_result.get("tool") if isinstance(routed_result, dict) else "",
        "source": (decision or {}).get("source", ""),
        "reason": (decision or {}).get("reason", ""),
        "prompt": (decision or {}).get("prompt", ""),
        "source_files": (decision or {}).get("source_files") or [],
        "attached_images": context.get("attached_images", []),
        "attached_documents": context.get("attached_documents", []),
        "project_documents": context.get("project_document_candidates", []),
        "project_images": context.get("project_image_candidates", []),
        "project_files": context.get("project_file_candidates", [])[:8],
        "latest_active_image": context.get("latest_active_image", ""),
        "outputs": result_output_paths(routed_result),
    }


def format_agent_trace_block(trace: dict) -> str:
    return "\n\n[AGENT_TRACE]" + json.dumps(trace, ensure_ascii=False) + "[/AGENT_TRACE]"


def direct_agent_trace_decision(
    content: str,
    action: str,
    tool: str,
    reason: str = "",
    source: str = "direct",
    source_files: list[str] | None = None,
) -> dict:
    return {
        "action": action,
        "tool": tool,
        "source": source,
        "source_files": source_files or [],
        "reason": reason or "matched direct tool path",
        "prompt": content,
    }
