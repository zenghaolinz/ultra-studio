from routes.direct_files import (
    format_docx_create_response,
    format_implementation_choice_card,
    format_text_file_create_response,
)
from services.chat_generation_context import inject_3d_context, inject_image_context
from services.chat_response_formatters import (
    format_3d_response,
    format_folder_summary_response,
    format_image_response,
    format_video_response,
)
from services.chat_tool_results import THREE_D_TOOL_NAMES


def format_router_result(routed_result: dict | str | None) -> str | None:
    if routed_result is None:
        return None
    if isinstance(routed_result, str):
        return routed_result
    if "tool" in routed_result:
        tool = routed_result["tool"]
        result = routed_result.get("result") or {}
        if tool in {"generate_image", "edit_image", "generate_multiview_images_from_image"}:
            return format_image_response(tool, result)
        if tool == "generate_video":
            return format_video_response(result)
        if tool in THREE_D_TOOL_NAMES:
            return format_3d_response(tool, result)
        if tool == "implementation_choice":
            return result.get("message") or format_implementation_choice_card("")
        if tool == "create_text_file":
            return format_text_file_create_response(result or {})
    if routed_result.get("path") and routed_result.get("ok") is not None:
        if str(routed_result.get("path", "")).lower().endswith(".docx"):
            return format_docx_create_response(routed_result)
    if routed_result.get("document_count") is not None or routed_result.get("needs_path"):
        return format_folder_summary_response(routed_result)
    return None


async def inject_router_context(conversation_id: str, routed_result: dict | str | None):
    if not isinstance(routed_result, dict) or "tool" not in routed_result:
        return
    result = routed_result.get("result") or {}
    if routed_result["tool"] in {"generate_image", "edit_image", "generate_multiview_images_from_image"}:
        await inject_image_context(conversation_id, result)
    elif routed_result["tool"] in THREE_D_TOOL_NAMES:
        await inject_3d_context(conversation_id, result)
