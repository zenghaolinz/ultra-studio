from dataclasses import dataclass

from services.chat_confirmations import (
    extract_delete_continuation,
    is_delete_request_text,
    with_delete_continuation,
)
from services.chat_response_formatters import (
    format_3d_response,
    format_command_tool_response,
    format_delete_tool_response,
    format_image_response,
    format_project_check_response,
    format_text_edit_response,
    format_video_response,
    format_write_many_files_response,
)


@dataclass(frozen=True)
class ToolResultPresentation:
    text: str
    trace_group: str | None = None
    trace_tool: str | None = None
    trace_result: dict | None = None
    trace_reason: str = ""
    include_image_attachments: bool = False


def build_tool_result_presentation(
    req_content: str,
    *,
    three_d_result: dict | None,
    multiview_image_result: dict | None,
    generated_image_result: dict | None,
    generated_video_result: dict | None,
    delete_result: dict | None,
    project_check_result: dict | None,
    command_result: dict | None,
    edit_text_result: dict | None,
    write_many_result: dict | None,
) -> ToolResultPresentation | None:
    if three_d_result:
        return ToolResultPresentation(
            text=format_3d_response(three_d_result["tool"], three_d_result["result"]),
            trace_group="generate_3d_image",
            trace_tool=three_d_result["tool"],
            trace_result=three_d_result["result"],
            trace_reason="LLM tool call produced 3D result",
            include_image_attachments=True,
        )
    if multiview_image_result:
        return ToolResultPresentation(
            text=format_image_response(multiview_image_result["tool"], multiview_image_result["result"]),
            trace_group="generate_multiview_images",
            trace_tool=multiview_image_result["tool"],
            trace_result=multiview_image_result["result"],
            trace_reason="LLM tool call produced multiview images",
            include_image_attachments=True,
        )
    if generated_image_result:
        return ToolResultPresentation(
            text=format_image_response(generated_image_result["tool"], generated_image_result["result"]),
            trace_group="generate_image",
            trace_tool=generated_image_result["tool"],
            trace_result=generated_image_result["result"],
            trace_reason="LLM tool call produced image result",
            include_image_attachments=True,
        )
    if generated_video_result:
        return ToolResultPresentation(
            text=format_video_response(generated_video_result["result"]),
            trace_group="generate_video",
            trace_tool=generated_video_result["tool"],
            trace_result=generated_video_result["result"],
            trace_reason="LLM tool call queued video generation",
            include_image_attachments=True,
        )
    if delete_result:
        continuation = extract_delete_continuation(req_content)
        if delete_result["result"].get("needs_confirmation") and continuation:
            delete_result["result"]["message"] = with_delete_continuation(
                delete_result["result"].get("message", ""),
                continuation,
            )
        return ToolResultPresentation(
            text=format_delete_tool_response(delete_result["result"]),
            trace_group="general_tools",
            trace_tool="delete_file",
            trace_result=delete_result["result"],
            trace_reason="LLM tool call produced delete result",
        )
    if project_check_result:
        return ToolResultPresentation(
            text=format_project_check_response(project_check_result["result"]),
            trace_group="general_tools",
            trace_tool="run_project_check",
            trace_result=project_check_result["result"],
            trace_reason="LLM tool call produced project check result",
        )
    if command_result:
        return ToolResultPresentation(
            text=format_command_tool_response(command_result["result"]),
            trace_group="general_tools",
            trace_tool="run_command",
            trace_result=command_result["result"],
            trace_reason="LLM tool call produced command result",
        )
    if edit_text_result:
        return ToolResultPresentation(
            text=format_text_edit_response(edit_text_result["result"]),
            trace_group="general_tools",
            trace_tool="edit_text_file",
            trace_result=edit_text_result["result"],
            trace_reason="LLM tool call produced text edit result",
        )
    if write_many_result:
        return ToolResultPresentation(
            text=format_write_many_files_response(write_many_result["result"]),
            trace_group="general_tools",
            trace_tool="write_many_files",
            trace_result=write_many_result["result"],
            trace_reason="LLM tool call produced multi-file write result",
        )
    if is_delete_request_text(req_content):
        return ToolResultPresentation(
            text="没有定位到可删除目标。请提供更明确的文件名或完整路径，我会在标准模式下先弹出确认卡片。"
        )
    return None
