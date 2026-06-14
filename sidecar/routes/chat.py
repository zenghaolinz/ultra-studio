import traceback
import json
import asyncio
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from db.sqlite import get_db
from memory import manager as memory_mgr
from schemas import ChatRequest
from routes.direct_files import (
    edit_text_result_can_fallback as _edit_text_result_can_fallback,
    extract_explicit_text_file_path as _extract_explicit_text_file_path,
    find_latest_text_file_path as _find_latest_text_file_path,
    format_delete_then_create_response as _format_delete_then_create_response,
    format_docx_create_response as _format_docx_create_response,
    format_docx_edit_response as _format_docx_edit_response,
    format_implementation_choice_card as _format_implementation_choice_card,
    format_text_file_create_response as _format_text_file_create_response,
    is_text_file_edit_followup_intent as _is_text_file_edit_followup_intent,
    needs_implementation_choice as _needs_implementation_choice,
    run_direct_document_read as _run_direct_document_read,
    run_direct_docx_create as _run_direct_docx_create,
    run_direct_docx_edit as _run_direct_docx_edit,
    run_direct_text_file_create as _run_direct_text_file_create,
    run_direct_text_file_edit as _run_direct_text_file_edit,
)
from services.chat_result_repair import (
    repair_text_create_result as _repair_text_create_result,
    repair_text_edit_result as _repair_text_edit_result,
)
from services.chat_response_formatters import (
    format_3d_response as _format_3d_response,
    format_attachment_asset_start as _format_attachment_asset_start,
    format_command_tool_response as _format_command_tool_response,
    format_delete_tool_response as _format_delete_tool_response,
    format_folder_summary_response as _format_folder_summary_response,
    format_image_response as _format_image_response,
    format_project_check_response as _format_project_check_response,
    format_text_edit_response as _format_text_edit_response,
    format_textual_tool_direct_response as _format_textual_tool_direct_response,
    format_video_response as _format_video_response,
    format_write_many_files_response as _format_write_many_files_response,
)
from services.chat_confirmations import (
    extract_confirmed_command as _extract_confirmed_command,
    extract_confirmed_project_check as _extract_confirmed_project_check,
    extract_delete_continuation as _extract_delete_continuation,
    is_delete_request_text as _is_delete_request_text,
    run_confirmed_command_request as _run_confirmed_command_request,
    run_confirmed_project_check_request as _run_confirmed_project_check_request,
    with_delete_continuation as _with_delete_continuation,
)
from services.chat_delete_flow import run_confirmed_delete_request as _run_confirmed_delete_request
from services.chat_folder_summary import summarize_folder_documents as _summarize_folder_documents
from services.chat_llm_router import llm_route_request as _llm_route_request
from services.chat_router_actions import run_router_action as _run_router_action
from services.generation_runtime import (
    COMFY_MANUAL_START_STATUS,
    COMFY_QUEUED_STATUS,
    COMFY_STARTING_STATUS,
    is_generation_action,
    is_generation_tool,
    should_queue_generation,
)
from services.textual_tool_parser import (
    SUPPORTED_TEXTUAL_TOOL_NAMES,
    TEXTUAL_TOOL_CALLS_END_PATTERN,
    TEXTUAL_TOOL_MARKER_PATTERN,
    extract_textual_tool_call as _extract_textual_tool_call,
    extract_textual_tool_calls as _extract_textual_tool_calls,
)
from services.chat_textual_tools import (
    answer_from_textual_tool_results as _answer_from_textual_tool_results,
    run_textual_tool_call as _run_textual_tool_call,
    run_textual_tool_calls as _run_textual_tool_calls,
)
from services.chat_tool_loop import run_tool_calls as _run_tool_calls
from services.chat_direct_media import (
    run_direct_3d_request as _run_direct_3d_request,
    run_direct_image_request as _run_direct_image_request,
    run_previous_3d_modification as _run_previous_3d_modification,
)
from services.chat_provider_client import get_provider_client as _get_provider_client
from services.chat_tool_results import (
    THREE_D_TOOL_NAMES,
    any_requires_manual_comfy_start as _any_requires_manual_comfy_start,
    best_tool_result as _best_tool_result,
    first_3d_result as _first_3d_result,
    first_tool_result as _first_tool_result,
    requires_manual_comfy_start as _requires_manual_comfy_start,
)
from services.chat_messages import (
    remove_internal_source_message as _remove_internal_source_message,
    save_assistant_message as _save_assistant_message,
    save_user_message as _save_user_message,
    save_visible_user_message as _save_visible_user_message,
)
from services.chat_intents import (
    is_3d_intent as _is_3d_intent,
    is_image_3d_intent as _is_image_3d_intent,
    is_image_edit_intent as _is_image_edit_intent,
    is_image_generation_intent as _is_image_generation_intent,
    is_memory_intent as _is_memory_intent,
    is_modify_previous_3d_intent as _is_modify_previous_3d_intent,
    is_previous_image_edit_intent as _is_previous_image_edit_intent,
    is_text_3d_intent as _is_text_3d_intent,
    requests_multiview_followup as _requests_multiview_followup,
)
from services.chat_document_assets import (
    is_attachment_asset_intent as _is_attachment_asset_intent,
    is_project_document_asset_intent as _is_project_document_asset_intent,
    run_attachment_asset_request as _run_attachment_asset_request,
    run_project_document_asset_request as _run_project_document_asset_request,
)
from services.chat_paths import (
    DOCX_PATH_PATTERN,
    DOCUMENT_EXTENSIONS,
    GENERATED_TEXT_EXTENSIONS,
    TEXT_FILE_PATH_PATTERN,
    candidate_local_paths as _candidate_local_paths,
    document_attachments as _document_attachments,
    find_desktop_directory_by_mention as _find_desktop_directory_by_mention,
    image_attachments as _image_attachments,
    is_document_path as _is_document_path,
    resolve_local_path as _resolve_local_path,
)
from services.chat_router_context import (
    agent_trace_block as _agent_trace_block,
    direct_agent_trace_block as _direct_agent_trace_block,
)
from services.chat_router_results import (
    format_router_result as _format_router_result,
    inject_router_context as _inject_router_context,
)
from services.chat_titles import schedule_title_generation as _schedule_title_generation
from services.chat_projects import (
    project_path_for_request as _project_path_for_request,
    run_open_folder_request as _run_open_folder_request,
    with_project_context as _with_project_context,
)
from services.chat_generation_context import (
    find_latest_edit_source_image as _find_latest_edit_source_image,
    inject_3d_context as _inject_3d_context,
    inject_image_context as _inject_image_context,
    inject_request_image_context as _inject_request_image_context,
)
from services.chat_project_files import (
    project_document_paths as _project_document_paths,
)
from services.chat_documents import read_document_attachments as _read_document_attachments
from services.model_context import fit_messages_to_context as _fit_messages_to_context

router = APIRouter()

@router.post("/send")
async def send_message(req: ChatRequest):
    db = await get_db()

    await _remove_internal_source_message(db, req)
    await _save_visible_user_message(db, req)
    await _inject_request_image_context(req.conversation_id, req.image_paths)
    req.project_path = await _project_path_for_request(req)

    open_folder_result = _run_open_folder_request(req)
    if open_folder_result:
        if open_folder_result.get("ok"):
            assistant_content = f"已打开文件夹：`{open_folder_result.get('path')}`"
        else:
            assistant_content = f"打开文件夹失败：{open_folder_result.get('error', '未知错误')}"
        assistant_content += await _direct_agent_trace_block(
            req,
            None,
            "open_folder",
            "open_folder",
            open_folder_result,
            "matched open folder request",
            "project_path",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    confirmed_project_check_result = _run_confirmed_project_check_request(req)
    if confirmed_project_check_result:
        assistant_content = _format_project_check_response(confirmed_project_check_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            None,
            "run_project_check",
            "run_project_check",
            confirmed_project_check_result,
            "matched confirmed project check request",
            "confirmed_project_check",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    confirmed_project_check_result = _run_confirmed_project_check_request(req)
    if confirmed_project_check_result:
        async def confirmed_project_check_event_generator():
            full_content = _format_project_check_response(confirmed_project_check_result)
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                None,
                "run_project_check",
                "run_project_check",
                confirmed_project_check_result,
                "matched confirmed project check request",
                "confirmed_project_check",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            confirmed_project_check_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    confirmed_command_result = _run_confirmed_command_request(req)
    if confirmed_command_result:
        assistant_content = _format_command_tool_response(confirmed_command_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            None,
            "run_command",
            "run_command",
            confirmed_command_result,
            "matched confirmed command request",
            "confirmed_command",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    previous_mod_result = None
    if _is_modify_previous_3d_intent(req.content, req.image_paths) and not _requests_multiview_followup(req.content):
        latest_edit_source = await _find_latest_edit_source_image(req.conversation_id)
        if latest_edit_source:
            previous_mod_result = await _run_previous_3d_modification(
                req.conversation_id, req.content, req.image_paths
            )
    if previous_mod_result:
        assistant_content = _format_3d_response(
            previous_mod_result["tool"], previous_mod_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            None,
            "generate_3d_image",
            previous_mod_result["tool"],
            previous_mod_result["result"],
            "matched previous 3D modification request",
            "latest_active_image",
        )
        await _inject_3d_context(req.conversation_id, previous_mod_result["result"])
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    client, provider_config = await _get_provider_client(db, req.model_id)
    if not client:
        raise HTTPException(status_code=400, detail="No default model configured")

    confirmed_delete_result = await _run_confirmed_delete_request(req, client, provider_config[1])
    if confirmed_delete_result:
        delete_result, create_result = confirmed_delete_result
        assistant_content = _format_delete_then_create_response(delete_result, create_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "delete_file",
            "delete_file",
            delete_result,
            "matched confirmed delete request",
            "confirmed_delete",
        )
        if create_result:
            assistant_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "create_text_file",
                "create_text_file",
                create_result,
                "continued after confirmed delete",
                "delete_continuation",
            )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_text_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1], provider_config)
    if direct_text_edit_result:
        assistant_content = _format_text_edit_response(direct_text_edit_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "edit_text_file",
            direct_text_edit_result,
            "matched direct text file edit request",
            "project_document",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    route_decision = await _llm_route_request(client, provider_config[1], req, provider_config)
    if route_decision and route_decision.get("action") not in {"chat", "general_tools"}:
        routed_result = await _run_router_action(route_decision, req, client, provider_config[1], provider_config)
        routed_text = _format_router_result(routed_result)
        if routed_text:
            assistant_content = routed_text + await _agent_trace_block(
                req, provider_config, route_decision, routed_result
            )
            await _inject_router_context(req.conversation_id, routed_result)
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, assistant_content
            )
            _schedule_title_generation(db, req)
            return {
                "id": assistant_id,
                "conversationId": req.conversation_id,
                "role": "assistant",
                "content": assistant_content,
                "createdAt": assistant_now,
                "savedMemories": [],
            }

    if route_decision is None and _needs_implementation_choice(req.content):
        assistant_content = _format_implementation_choice_card(req.content)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "choose_implementation",
            "implementation_choice",
            {"ok": True},
            "fallback after router was unavailable",
            "direct",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    use_tool_orchestrator = bool(
        route_decision and route_decision.get("action") == "general_tools"
    )

    direct_3d_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_3d_request(req.content, req.image_paths)
    )
    if direct_3d_result:
        assistant_content = _format_3d_response(
            direct_3d_result["tool"], direct_3d_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "generate_3d_image" if _image_attachments(req.image_paths) else "generate_3d_text",
            direct_3d_result["tool"],
            direct_3d_result["result"],
            "matched direct 3D request",
            "attached_image" if _image_attachments(req.image_paths) else "none",
            _image_attachments(req.image_paths),
        )
        await _inject_3d_context(req.conversation_id, direct_3d_result["result"])
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_image_result = None
    if not use_tool_orchestrator and not _is_project_document_asset_intent(req.content, req.project_path):
        direct_image_result = await _run_direct_image_request(
            req.content,
            req.image_paths,
            req.conversation_id,
            req.project_path,
        )
    if direct_image_result:
        assistant_content = _format_image_response(
            direct_image_result["tool"], direct_image_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "edit_image" if direct_image_result["tool"] == "edit_image" else "generate_image",
            direct_image_result["tool"],
            direct_image_result["result"],
            "matched direct image request",
            "attached_image" if _image_attachments(req.image_paths) else "latest_active_image",
            _image_attachments(req.image_paths),
        )
        await _inject_image_context(req.conversation_id, direct_image_result["result"])
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    project_document_asset_result = (
        None
        if use_tool_orchestrator
        else await _run_project_document_asset_request(req, client, provider_config[1], provider_config)
    )
    if project_document_asset_result:
        if project_document_asset_result["tool"] == "generate_image":
            assistant_content = _format_image_response(
                project_document_asset_result["tool"], project_document_asset_result["result"]
            )
            await _inject_image_context(req.conversation_id, project_document_asset_result["result"])
        else:
            assistant_content = _format_3d_response(
                project_document_asset_result["tool"], project_document_asset_result["result"]
            )
            await _inject_3d_context(req.conversation_id, project_document_asset_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "project_document_3d" if "3d" in project_document_asset_result["tool"] else "project_document_image",
            project_document_asset_result["tool"],
            project_document_asset_result["result"],
            "matched project document asset request",
            "project_document",
            _project_document_paths(req.project_path or "", req.content),
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    attachment_asset_result = (
        None
        if use_tool_orchestrator
        else await _run_attachment_asset_request(req, client, provider_config[1], provider_config)
    )
    if attachment_asset_result:
        if attachment_asset_result["tool"] == "generate_image":
            assistant_content = _format_image_response(
                attachment_asset_result["tool"], attachment_asset_result["result"]
            )
            await _inject_image_context(req.conversation_id, attachment_asset_result["result"])
        else:
            assistant_content = _format_3d_response(
                attachment_asset_result["tool"], attachment_asset_result["result"]
            )
            await _inject_3d_context(req.conversation_id, attachment_asset_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "attachment_document_3d" if "3d" in attachment_asset_result["tool"] else "attachment_document_image",
            attachment_asset_result["tool"],
            attachment_asset_result["result"],
            "matched attachment document asset request",
            "document",
            _document_attachments(req.image_paths),
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    folder_summary_result = (
        None
        if use_tool_orchestrator
        else await _summarize_folder_documents(req, client, provider_config[1], provider_config)
    )
    if folder_summary_result:
        assistant_content = _format_folder_summary_response(folder_summary_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "folder_summary_docx",
            "folder_summary_docx",
            folder_summary_result,
            "matched folder summary document request",
            "project_document",
            _project_document_paths(req.project_path or "", req.content),
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_text_file_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_text_file_create(req, client, provider_config[1], provider_config=provider_config)
    )
    if direct_text_file_result:
        direct_text_file_result, _ = await _repair_text_create_result(
            req,
            client,
            provider_config[1],
            provider_config,
            direct_text_file_result,
        )
        assistant_content = _format_text_file_create_response(direct_text_file_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "create_text_file",
            "create_text_file",
            direct_text_file_result,
            "matched direct text/html file create request",
            "none",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_docx_edit_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_docx_edit(req, client, provider_config[1], provider_config)
    )
    if direct_docx_edit_result:
        assistant_content = _format_docx_edit_response(direct_docx_edit_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "edit_docx",
            "edit_docx",
            direct_docx_edit_result,
            "matched direct Word edit request",
            "document",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_docx_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_docx_create(req, client, provider_config[1], provider_config)
    )
    if direct_docx_result:
        assistant_content = _format_docx_create_response(direct_docx_result)
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "create_docx",
            "create_docx",
            direct_docx_result,
            "matched direct Word create request",
            "none",
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, assistant_content
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    direct_doc_response = (
        None
        if use_tool_orchestrator
        else await _run_direct_document_read(req, client, provider_config[1], provider_config)
    )
    if direct_doc_response is not None:
        direct_doc_response += await _direct_agent_trace_block(
            req,
            provider_config,
            "read_document",
            "read_document",
            {},
            "matched direct document read request",
            "document",
            _document_attachments(req.image_paths),
        )
        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, direct_doc_response
        )
        _schedule_title_generation(db, req)
        return {
            "id": assistant_id,
            "conversationId": req.conversation_id,
            "role": "assistant",
            "content": direct_doc_response,
            "createdAt": assistant_now,
            "savedMemories": [],
        }

    try:
        context_messages, tools = await memory_mgr.build_context(
            conversation_id=req.conversation_id,
            user_input=_with_project_context(req.content, req.project_path),
            image_paths=req.image_paths,
        )
    except Exception:
        context_messages = [
            {"role": "system", "content": "你是一个有记忆能力的个人助手。"},
            {"role": "user", "content": req.content},
        ]
        tools = []

    messages = context_messages
    messages = _fit_messages_to_context(messages, provider_config, tools)

    if tools:
        messages, tool_results, saved_memories = await _run_tool_calls(
            client,
            provider_config[1],
            messages,
            tools,
            req.conversation_id,
            req.permission_mode,
            _is_delete_request_text(req.content),
            provider_config=provider_config,
        )
    else:
        tool_results = []
        saved_memories = []

    three_d_result = _first_3d_result(tool_results)
    multiview_image_result = _first_tool_result(tool_results, "generate_multiview_images_from_image")
    generated_image_result = _first_tool_result(tool_results, "generate_image")
    generated_video_result = _first_tool_result(tool_results, "generate_video")
    modified_image_result = _first_tool_result(tool_results, "modify_image_with_flux")
    delete_result = _first_tool_result(tool_results, "delete_file")
    command_result = _first_tool_result(tool_results, "run_command")
    project_check_result = _first_tool_result(tool_results, "run_project_check")
    edit_text_result = _best_tool_result(tool_results, "edit_text_file")
    write_many_result = _best_tool_result(tool_results, "write_many_files")
    if (
        edit_text_result
        and write_many_result
        and isinstance(edit_text_result.get("result"), dict)
        and isinstance(write_many_result.get("result"), dict)
        and not edit_text_result["result"].get("ok")
        and write_many_result["result"].get("ok")
    ):
        edit_text_result = None
    edit_text_result, _ = await _repair_text_edit_result(
        req,
        client,
        provider_config[1],
        provider_config,
        edit_text_result,
        write_many_result,
    )
    if three_d_result and (generated_image_result or modified_image_result):
        source_result = (generated_image_result or modified_image_result)["result"]
        source_image = (
            source_result.get("image_path")
            or source_result.get("imagePath")
            or source_result.get("improved_image_path")
        )
        if source_image:
            three_d_result["result"].setdefault("source_image_path", source_image)
    if three_d_result:
        assistant_content = _format_3d_response(
            three_d_result["tool"], three_d_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "generate_3d_image",
            three_d_result["tool"],
            three_d_result["result"],
            "LLM tool call produced 3D result",
            "tool_call",
            _image_attachments(req.image_paths),
        )
    elif multiview_image_result:
        assistant_content = _format_image_response(
            multiview_image_result["tool"], multiview_image_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "generate_multiview_images",
            multiview_image_result["tool"],
            multiview_image_result["result"],
            "LLM tool call produced multiview images",
            "tool_call",
            _image_attachments(req.image_paths),
        )
    elif generated_image_result:
        assistant_content = _format_image_response(
            generated_image_result["tool"], generated_image_result["result"]
        )
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "generate_image",
            generated_image_result["tool"],
            generated_image_result["result"],
            "LLM tool call produced image result",
            "tool_call",
            _image_attachments(req.image_paths),
        )
    elif generated_video_result:
        assistant_content = _format_video_response(generated_video_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "generate_video",
            generated_video_result["tool"],
            generated_video_result["result"],
            "LLM tool call queued video generation",
            "tool_call",
            _image_attachments(req.image_paths),
        )
    elif delete_result:
        continuation = _extract_delete_continuation(req.content)
        if delete_result["result"].get("needs_confirmation") and continuation:
            delete_result["result"]["message"] = _with_delete_continuation(
                delete_result["result"].get("message", ""),
                continuation,
            )
        assistant_content = _format_delete_tool_response(delete_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "delete_file",
            delete_result["result"],
            "LLM tool call produced delete result",
            "tool_call",
        )
    elif project_check_result:
        assistant_content = _format_project_check_response(project_check_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "run_project_check",
            project_check_result["result"],
            "LLM tool call produced project check result",
            "tool_call",
        )
    elif command_result:
        assistant_content = _format_command_tool_response(command_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "run_command",
            command_result["result"],
            "LLM tool call produced command result",
            "tool_call",
        )
    elif edit_text_result:
        assistant_content = _format_text_edit_response(edit_text_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "edit_text_file",
            edit_text_result["result"],
            "LLM tool call produced text edit result",
            "tool_call",
        )
    elif write_many_result:
        assistant_content = _format_write_many_files_response(write_many_result["result"])
        assistant_content += await _direct_agent_trace_block(
            req,
            provider_config,
            "general_tools",
            "write_many_files",
            write_many_result["result"],
            "LLM tool call produced multi-file write result",
            "tool_call",
        )
    elif _is_delete_request_text(req.content):
        assistant_content = "没有定位到可删除目标。请提供更明确的文件名或完整路径，我会在标准模式下先弹出确认卡片。"
    else:
        try:
            response = await client.chat.completions.create(
                model=provider_config[1],
                messages=_fit_messages_to_context(messages, provider_config),
            )
            assistant_content = response.choices[0].message.content
            textual_tool_results = _run_textual_tool_calls(assistant_content or "")
            if textual_tool_results:
                assistant_content = await _answer_from_textual_tool_results(
                    client,
                    provider_config[1],
                    messages,
                    req.content,
                    textual_tool_results,
                    provider_config,
                )
                trace_result = {
                    "tool_count": len(textual_tool_results),
                    "tools": [item.get("tool") for item in textual_tool_results],
                    "results": textual_tool_results,
                }
                assistant_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "general_tools",
                    "textual_tool_calls",
                    trace_result,
                    "parsed textual tool calls fallback",
                    "textual_tool_call",
                )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM call failed: {str(e)}",
            )

    assistant_id, assistant_now = await _save_assistant_message(
        db, req.conversation_id, assistant_content
    )

    try:
        await memory_mgr.check_consolidation(conversation_id=req.conversation_id)
    except Exception:
        pass

    _schedule_title_generation(db, req)

    return {
        "id": assistant_id,
        "conversationId": req.conversation_id,
        "role": "assistant",
        "content": assistant_content,
        "createdAt": assistant_now,
        "savedMemories": saved_memories,
    }


@router.post("/send/stream")
async def send_message_stream(req: ChatRequest):
    db = await get_db()

    if req.image_paths:
        print(f"[chat] Received image_paths: {req.image_paths}")
    else:
        print(f"[chat] No image_paths in request")

    await _remove_internal_source_message(db, req)
    await _save_visible_user_message(db, req)
    await _inject_request_image_context(req.conversation_id, req.image_paths)
    req.project_path = await _project_path_for_request(req)

    open_folder_result = _run_open_folder_request(req)
    if open_folder_result:
        async def open_folder_event_generator():
            if open_folder_result.get("ok"):
                full_content = f"已打开文件夹：`{open_folder_result.get('path')}`"
            else:
                full_content = f"打开文件夹失败：{open_folder_result.get('error', '未知错误')}"
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                None,
                "open_folder",
                "open_folder",
                open_folder_result,
                "matched open folder request",
                "project_path",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            open_folder_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    confirmed_command_result = _run_confirmed_command_request(req)
    if confirmed_command_result:
        async def confirmed_command_event_generator():
            full_content = _format_command_tool_response(confirmed_command_result)
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                None,
                "run_command",
                "run_command",
                confirmed_command_result,
                "matched confirmed command request",
                "confirmed_command",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            confirmed_command_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    latest_edit_source = None
    if _is_modify_previous_3d_intent(req.content, req.image_paths) and not _requests_multiview_followup(req.content):
        latest_edit_source = await _find_latest_edit_source_image(req.conversation_id)

    if latest_edit_source:
        async def previous_mod_event_generator():
            start_text = "\u5df2\u5f00\u59cb\u57fa\u4e8e\u4e0a\u4e00\u6b21\u751f\u6210\u7684 Flux \u56fe\u7247\u4fee\u6539\uff0c\u7136\u540e\u4f1a\u7528\u4fee\u6539\u540e\u7684\u56fe\u91cd\u65b0\u751f\u6210 3D \u6a21\u578b\u3002\n\n"
            full_content = ""
            yield f"data: {json.dumps({'status': start_text.strip()}, ensure_ascii=False)}\n\n"
            if should_queue_generation():
                yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"

            try:
                mod_result = await _run_previous_3d_modification(
                    req.conversation_id, req.content, req.image_paths
                )
                if mod_result is None:
                    mod_result = {
                        "tool": "modify_previous_3d",
                        "result": {
                            "status": "error",
                            "message": "\u6ca1\u6709\u68c0\u6d4b\u5230\u53ef\u4fee\u6539\u7684\u4e0a\u4e00\u6b21 3D \u7ed3\u679c\u3002",
                        },
                    }
                if _requires_manual_comfy_start(mod_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"
                result_text = _format_3d_response(mod_result["tool"], mod_result["result"])
                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                await _inject_3d_context(req.conversation_id, mod_result["result"])
                full_content += await _direct_agent_trace_block(
                    req,
                    None,
                    "generate_3d_image",
                    mod_result["tool"],
                    mod_result["result"],
                    "matched previous 3D modification request",
                    "latest_active_image",
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = _format_3d_response(
                    "modify_previous_3d",
                    {"status": "error", "message": str(e)},
                )
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            previous_mod_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    client, provider_config = await _get_provider_client(db, req.model_id)
    if not client:
        raise HTTPException(status_code=400, detail="No default model configured")

    confirmed_delete_result = await _run_confirmed_delete_request(req, client, provider_config[1])
    if confirmed_delete_result:
        async def confirmed_delete_event_generator():
            delete_result, create_result = confirmed_delete_result
            full_content = _format_delete_then_create_response(delete_result, create_result)
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "delete_file",
                "delete_file",
                delete_result,
                "matched confirmed delete request",
                "confirmed_delete",
            )
            if create_result:
                full_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "create_text_file",
                    "create_text_file",
                    create_result,
                    "continued after confirmed delete",
                    "delete_continuation",
                )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            confirmed_delete_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if _is_text_file_edit_followup_intent(req.content) and (
        _extract_explicit_text_file_path(req.content) or await _find_latest_text_file_path(req.conversation_id)
    ):
        async def direct_text_edit_event_generator():
            yield f"data: {json.dumps({'status': '正在调用工具：edit_text_file'}, ensure_ascii=False)}\n\n"
            direct_text_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1], provider_config)
            if not direct_text_edit_result:
                full_content = "没有找到可编辑的已有文本文件。请提供文件路径，或先生成/选择一个文件。"
            else:
                full_content = _format_text_edit_response(direct_text_edit_result)
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            if not direct_text_edit_result:
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
                return
            full_content = _format_text_edit_response(direct_text_edit_result)
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "general_tools",
                "edit_text_file",
                direct_text_edit_result,
                "matched direct text file edit request",
                "project_document",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            direct_text_edit_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    route_decision = await _llm_route_request(client, provider_config[1], req, provider_config)
    if route_decision and route_decision.get("action") not in {"chat", "general_tools"}:
        async def routed_event_generator():
            full_content = ""
            try:
                action = route_decision.get("action")
                if is_generation_action(action):
                    if should_queue_generation():
                        yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"
                if action == "generate_image":
                    yield f"data: {json.dumps({'status': '正在生成图片'}, ensure_ascii=False)}\n\n"
                elif action == "generate_video":
                    yield f"data: {json.dumps({'status': '视频任务入队中'}, ensure_ascii=False)}\n\n"
                elif action == "edit_image":
                    yield f"data: {json.dumps({'status': '正在编辑图片'}, ensure_ascii=False)}\n\n"
                elif action == "generate_multiview_images":
                    yield f"data: {json.dumps({'status': '正在生成正面、左侧、背面图片'}, ensure_ascii=False)}\n\n"
                elif action == "generate_3d_multiview":
                    yield f"data: {json.dumps({'status': '正在用已知三视图生成 3D 模型'}, ensure_ascii=False)}\n\n"
                elif action in {"generate_3d_text", "generate_3d_image", "generate_3d_fusion"}:
                    yield f"data: {json.dumps({'status': '正在生成 3D 模型'}, ensure_ascii=False)}\n\n"
                elif action == "create_text_file":
                    yield f"data: {json.dumps({'status': '正在创建本地文件'}, ensure_ascii=False)}\n\n"

                routed_result = await _run_router_action(
                    route_decision,
                    req,
                    client,
                    provider_config[1],
                    provider_config,
                )
                if _requires_manual_comfy_start(routed_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"
                result_text = _format_router_result(routed_result)
                if not result_text:
                    result_text = "我没能把这次请求映射到可执行工具，已退回普通对话处理。"
                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                await _inject_router_context(req.conversation_id, routed_result)
                full_content += await _agent_trace_block(
                    req, provider_config, route_decision, routed_result
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = f"工具执行失败：{e}"
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            routed_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if route_decision is None and _needs_implementation_choice(req.content):
        async def implementation_choice_fallback_event_generator():
            full_content = _format_implementation_choice_card(req.content)
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "choose_implementation",
                "implementation_choice",
                {"ok": True},
                "fallback after router was unavailable",
                "direct",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            implementation_choice_fallback_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    use_tool_orchestrator = bool(
        route_decision and route_decision.get("action") == "general_tools"
    )

    if not use_tool_orchestrator and _is_3d_intent(req.content, req.image_paths):
        async def direct_3d_event_generator():
            if _is_image_3d_intent(req.content, req.image_paths):
                start_text = "\u6536\u5230\u56fe\u7247\uff0c\u5df2\u5f00\u59cb\u8fdb\u884c\u56fe\u7247\u8f6c 3D\u3002\u751f\u6210\u53ef\u80fd\u9700\u8981\u4e00\u70b9\u65f6\u95f4\uff0c\u6211\u4f1a\u5728\u5b8c\u6210\u540e\u76f4\u63a5\u8fd4\u56de\u6a21\u578b\u9884\u89c8\u548c\u5bfc\u51fa\u9009\u9879\u3002\n\n"
            else:
                start_text = "\u5df2\u5f00\u59cb\u8fdb\u884c\u6587\u5b57\u751f\u6210 3D\u3002\u751f\u6210\u53ef\u80fd\u9700\u8981\u4e00\u70b9\u65f6\u95f4\uff0c\u6211\u4f1a\u5728\u5b8c\u6210\u540e\u76f4\u63a5\u8fd4\u56de\u6a21\u578b\u9884\u89c8\u548c\u5bfc\u51fa\u9009\u9879\u3002\n\n"
            full_content = ""
            yield f"data: {json.dumps({'status': start_text.strip()}, ensure_ascii=False)}\n\n"
            if should_queue_generation():
                yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"

            try:
                direct_result = await _run_direct_3d_request(req.content, req.image_paths)
                if direct_result is None:
                    direct_result = {
                        "tool": "generate_3d_from_image",
                        "result": {"status": "error", "message": "No image-to-3D request detected"},
                    }
                if _requires_manual_comfy_start(direct_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"
                result_text = _format_3d_response(
                    direct_result["tool"], direct_result["result"]
                )
                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                await _inject_3d_context(req.conversation_id, direct_result["result"])
                full_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "generate_3d_image" if _image_attachments(req.image_paths) else "generate_3d_text",
                    direct_result["tool"],
                    direct_result["result"],
                    "matched direct 3D request",
                    "attached_image" if _image_attachments(req.image_paths) else "none",
                    _image_attachments(req.image_paths),
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = _format_3d_response(
                    "generate_3d_from_image",
                    {"status": "error", "message": str(e)},
                )
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            direct_3d_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if (
        not use_tool_orchestrator
        and not _is_project_document_asset_intent(req.content, req.project_path)
        and (
            _is_image_generation_intent(req.content, req.image_paths)
            or _is_image_edit_intent(req.content, req.image_paths)
            or _is_previous_image_edit_intent(req.content)
        )
    ):
        async def direct_image_event_generator():
            if _is_image_edit_intent(req.content, req.image_paths) or _is_previous_image_edit_intent(req.content):
                start_text = "已开始编辑图片，完成后会直接返回图片预览。\n\n"
            else:
                start_text = "已开始生成图片，完成后会直接返回图片预览。\n\n"
            full_content = start_text
            if should_queue_generation():
                yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"

            try:
                direct_result = await _run_direct_image_request(
                    req.content,
                    req.image_paths,
                    req.conversation_id,
                    req.project_path,
                )
                if direct_result is None:
                    direct_result = {
                        "tool": "generate_image",
                        "result": {"status": "error", "message": "没有检测到图片生成或图片编辑请求"},
                    }
                if _requires_manual_comfy_start(direct_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"
                result_text = _format_image_response(direct_result["tool"], direct_result["result"])
                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                await _inject_image_context(req.conversation_id, direct_result["result"])
                full_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "edit_image" if direct_result["tool"] == "edit_image" else "generate_image",
                    direct_result["tool"],
                    direct_result["result"],
                    "matched direct image request",
                    "attached_image" if _image_attachments(req.image_paths) else "latest_active_image",
                    _image_attachments(req.image_paths),
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = _format_image_response(
                    "generate_image",
                    {"status": "error", "message": str(e)},
                )
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            direct_image_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if not use_tool_orchestrator and _is_project_document_asset_intent(req.content, req.project_path):
        async def project_document_asset_event_generator():
            full_content = ""
            try:
                if should_queue_generation():
                    yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"
                project_document_asset_result = await _run_project_document_asset_request(
                    req,
                    client,
                    provider_config[1],
                    provider_config,
                )
                if project_document_asset_result is None:
                    project_document_asset_result = {
                        "tool": "generate_image",
                        "result": {"status": "error", "message": "没有从项目文档中识别到可执行的生成任务"},
                    }
                if _requires_manual_comfy_start(project_document_asset_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"

                start_text = _format_attachment_asset_start(project_document_asset_result["tool"])
                full_content += start_text
                yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"

                if project_document_asset_result["tool"] == "generate_image":
                    result_text = _format_image_response(
                        project_document_asset_result["tool"],
                        project_document_asset_result["result"],
                    )
                    await _inject_image_context(req.conversation_id, project_document_asset_result["result"])
                else:
                    result_text = _format_3d_response(
                        project_document_asset_result["tool"],
                        project_document_asset_result["result"],
                    )
                    await _inject_3d_context(req.conversation_id, project_document_asset_result["result"])

                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                full_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "project_document_3d" if "3d" in project_document_asset_result["tool"] else "project_document_image",
                    project_document_asset_result["tool"],
                    project_document_asset_result["result"],
                    "matched project document asset request",
                    "project_document",
                    _project_document_paths(req.project_path or "", req.content),
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = _format_image_response(
                    "generate_image",
                    {"status": "error", "message": str(e)},
                )
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            project_document_asset_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if not use_tool_orchestrator and _is_attachment_asset_intent(req.content, req.image_paths):
        async def attachment_asset_event_generator():
            full_content = ""
            try:
                if should_queue_generation():
                    yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"
                attachment_asset_result = await _run_attachment_asset_request(
                    req,
                    client,
                    provider_config[1],
                    provider_config,
                )
                if attachment_asset_result is None:
                    attachment_asset_result = {
                        "tool": "generate_image",
                        "result": {"status": "error", "message": "没有从附件中识别到可执行的生成任务"},
                    }
                if _requires_manual_comfy_start(attachment_asset_result):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"

                start_text = _format_attachment_asset_start(attachment_asset_result["tool"])
                full_content += start_text
                yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"

                if attachment_asset_result["tool"] == "generate_image":
                    result_text = _format_image_response(
                        attachment_asset_result["tool"],
                        attachment_asset_result["result"],
                    )
                    await _inject_image_context(req.conversation_id, attachment_asset_result["result"])
                else:
                    result_text = _format_3d_response(
                        attachment_asset_result["tool"],
                        attachment_asset_result["result"],
                    )
                    await _inject_3d_context(req.conversation_id, attachment_asset_result["result"])

                full_content += result_text
                yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"

                full_content += await _direct_agent_trace_block(
                    req,
                    provider_config,
                    "attachment_document_3d" if "3d" in attachment_asset_result["tool"] else "attachment_document_image",
                    attachment_asset_result["tool"],
                    attachment_asset_result["result"],
                    "matched attachment document asset request",
                    "document",
                    _document_attachments(req.image_paths),
                )
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
                _schedule_title_generation(db, req)
            except Exception as e:
                error_text = _format_image_response(
                    "generate_image",
                    {"status": "error", "message": str(e)},
                )
                full_content += error_text
                yield f"data: {json.dumps({'token': error_text}, ensure_ascii=False)}\n\n"
                assistant_id, assistant_now = await _save_assistant_message(
                    db, req.conversation_id, full_content
                )
                yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            attachment_asset_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    folder_summary_result = (
        None
        if use_tool_orchestrator
        else await _summarize_folder_documents(req, client, provider_config[1], provider_config)
    )
    if folder_summary_result:
        async def folder_summary_event_generator():
            start_text = "" if folder_summary_result.get("needs_path") else "正在阅读文件夹中的文档，并整理重点写入新的 Word 文档。\n\n"
            final_text = _format_folder_summary_response(folder_summary_result)
            full_content = start_text + final_text
            if start_text:
                yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': final_text}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "folder_summary_docx",
                "folder_summary_docx",
                folder_summary_result,
                "matched folder summary document request",
                "project_document",
                _project_document_paths(req.project_path or "", req.content),
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            folder_summary_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    direct_text_file_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_text_file_create(req, client, provider_config[1], provider_config=provider_config)
    )
    if direct_text_file_result:
        async def direct_text_file_event_generator():
            start_text = "正在创建新文件。\n\n"
            repaired_text_file_result, repair_record = await _repair_text_create_result(
                req,
                client,
                provider_config[1],
                provider_config,
                direct_text_file_result,
            )
            if repair_record:
                yield f"data: {json.dumps({'status': '正在修复文件创建结果'}, ensure_ascii=False)}\n\n"
            final_text = _format_text_file_create_response(repaired_text_file_result)
            full_content = start_text + final_text
            yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': final_text}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "create_text_file",
                "create_text_file",
                repaired_text_file_result,
                "matched direct text/html file create request",
                "none",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            direct_text_file_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    direct_docx_edit_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_docx_edit(req, client, provider_config[1], provider_config)
    )
    if direct_docx_edit_result:
        async def direct_docx_edit_event_generator():
            start_text = "正在更新 Word 文档。\n\n"
            final_text = _format_docx_edit_response(direct_docx_edit_result)
            full_content = start_text + final_text
            yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': final_text}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "edit_docx",
                "edit_docx",
                direct_docx_edit_result,
                "matched direct Word edit request",
                "document",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            direct_docx_edit_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    direct_docx_result = (
        None
        if use_tool_orchestrator
        else await _run_direct_docx_create(req, client, provider_config[1], provider_config)
    )
    if direct_docx_result:
        async def direct_docx_event_generator():
            start_text = "正在创建 Word 文档。\n\n"
            final_text = _format_docx_create_response(direct_docx_result)
            full_content = start_text + final_text
            yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': final_text}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "create_docx",
                "create_docx",
                direct_docx_result,
                "matched direct Word create request",
                "none",
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            direct_docx_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    direct_doc_response = (
        None
        if use_tool_orchestrator
        else await _run_direct_document_read(req, client, provider_config[1], provider_config)
    )
    if direct_doc_response is not None:
        async def direct_document_event_generator():
            full_content = direct_doc_response
            yield f"data: {json.dumps({'token': full_content}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "read_document",
                "read_document",
                {},
                "matched direct document read request",
                "document",
                _document_attachments(req.image_paths),
            )
            assistant_id, assistant_now = await _save_assistant_message(
                db, req.conversation_id, full_content
            )
            yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': []}, ensure_ascii=False)}\n\n"
            _schedule_title_generation(db, req)

        return StreamingResponse(
            direct_document_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        context_messages, tools = await memory_mgr.build_context(
            conversation_id=req.conversation_id,
            user_input=_with_project_context(req.content, req.project_path),
            image_paths=req.image_paths,
        )
    except Exception:
        context_messages = [
            {"role": "system", "content": "你是一个有记忆能力的个人助手。"},
            {"role": "user", "content": req.content},
        ]
        tools = []

    client, provider_config = await _get_provider_client(db, req.model_id)
    if not client:
        raise HTTPException(status_code=400, detail="No default model configured")

    async def event_generator():
        full_content = ""
        messages = _fit_messages_to_context(context_messages, provider_config, tools)
        saved_memories = []
        try:
            if tools:
                if _is_3d_intent(req.content, req.image_paths):
                    if _is_image_3d_intent(req.content, req.image_paths):
                        start_text = "\u6536\u5230\u56fe\u7247\uff0c\u5df2\u5f00\u59cb\u8fdb\u884c\u56fe\u7247\u8f6c 3D\u3002\u751f\u6210\u53ef\u80fd\u9700\u8981\u4e00\u70b9\u65f6\u95f4\uff0c\u6211\u4f1a\u5728\u5b8c\u6210\u540e\u76f4\u63a5\u8fd4\u56de\u6a21\u578b\u9884\u89c8\u548c\u5bfc\u51fa\u9009\u9879\u3002\n\n"
                    else:
                        start_text = "\u5df2\u5f00\u59cb\u8fdb\u884c\u6587\u5b57\u751f\u6210 3D\u3002\u751f\u6210\u53ef\u80fd\u9700\u8981\u4e00\u70b9\u65f6\u95f4\uff0c\u6211\u4f1a\u5728\u5b8c\u6210\u540e\u76f4\u63a5\u8fd4\u56de\u6a21\u578b\u9884\u89c8\u548c\u5bfc\u51fa\u9009\u9879\u3002\n\n"
                    yield f"data: {json.dumps({'status': start_text.strip()}, ensure_ascii=False)}\n\n"
                elif _requests_multiview_followup(req.content):
                    status_text = "正在生成图片并继续生成高质量三视图" if "高质量" in req.content else "正在生成图片并继续生成三视图"
                    yield f"data: {json.dumps({'status': status_text}, ensure_ascii=False)}\n\n"
                elif _is_image_generation_intent(req.content, req.image_paths):
                    yield f"data: {json.dumps({'status': '正在生成图片'}, ensure_ascii=False)}\n\n"

                tool_status_queue = asyncio.Queue()

                async def report_tool_start(tool_name: str):
                    if is_generation_tool(tool_name):
                        if should_queue_generation():
                            await tool_status_queue.put(COMFY_QUEUED_STATUS)
                        await tool_status_queue.put(COMFY_STARTING_STATUS)
                    await tool_status_queue.put(tool_name)

                tool_task = asyncio.create_task(
                    _run_tool_calls(
                        client,
                        provider_config[1],
                        messages,
                        tools,
                        req.conversation_id,
                        req.permission_mode,
                        _is_delete_request_text(req.content),
                        report_tool_start,
                        provider_config=provider_config,
                    )
                )
                while not tool_task.done() or not tool_status_queue.empty():
                    try:
                        active_tool = await asyncio.wait_for(tool_status_queue.get(), timeout=0.08)
                    except asyncio.TimeoutError:
                        continue
                    if active_tool in {COMFY_STARTING_STATUS, COMFY_MANUAL_START_STATUS, COMFY_QUEUED_STATUS}:
                        status_text = active_tool
                    else:
                        status_text = f"正在调用工具：{active_tool}"
                    yield f"data: {json.dumps({'status': status_text}, ensure_ascii=False)}\n\n"

                messages, tool_results, saved_memories = await tool_task
                if _any_requires_manual_comfy_start(tool_results):
                    yield f"data: {json.dumps({'status': COMFY_MANUAL_START_STATUS}, ensure_ascii=False)}\n\n"

                three_d_result = _first_3d_result(tool_results)
                multiview_image_result = _first_tool_result(tool_results, "generate_multiview_images_from_image")
                generated_image_result = _first_tool_result(tool_results, "generate_image")
                generated_video_result = _first_tool_result(tool_results, "generate_video")
                modified_image_result = _first_tool_result(tool_results, "modify_image_with_flux")
                delete_result = _first_tool_result(tool_results, "delete_file")
                command_result = _first_tool_result(tool_results, "run_command")
                project_check_result = _first_tool_result(tool_results, "run_project_check")
                edit_text_result = _best_tool_result(tool_results, "edit_text_file")
                write_many_result = _best_tool_result(tool_results, "write_many_files")
                if (
                    edit_text_result
                    and write_many_result
                    and isinstance(edit_text_result.get("result"), dict)
                    and isinstance(write_many_result.get("result"), dict)
                    and not edit_text_result["result"].get("ok")
                    and write_many_result["result"].get("ok")
                ):
                    edit_text_result = None
                repaired_edit_result, repair_record = await _repair_text_edit_result(
                    req,
                    client,
                    provider_config[1],
                    provider_config,
                    edit_text_result,
                    write_many_result,
                )
                if repair_record:
                    yield f"data: {json.dumps({'status': '正在调用工具：edit_text_file'}, ensure_ascii=False)}\n\n"
                    edit_text_result = repaired_edit_result
                if three_d_result and (generated_image_result or modified_image_result):
                    source_result = (generated_image_result or modified_image_result)["result"]
                    source_image = (
                        source_result.get("image_path")
                        or source_result.get("imagePath")
                        or source_result.get("improved_image_path")
                    )
                    if source_image:
                        three_d_result["result"].setdefault("source_image_path", source_image)
                if three_d_result:
                    result_text = _format_3d_response(
                        three_d_result["tool"], three_d_result["result"]
                    )
                elif multiview_image_result:
                    result_text = _format_image_response(
                        multiview_image_result["tool"], multiview_image_result["result"]
                    )
                elif generated_image_result:
                    result_text = _format_image_response(
                        generated_image_result["tool"], generated_image_result["result"]
                    )
                elif generated_video_result:
                    result_text = _format_video_response(generated_video_result["result"])
                elif delete_result:
                    continuation = _extract_delete_continuation(req.content)
                    if delete_result["result"].get("needs_confirmation") and continuation:
                        delete_result["result"]["message"] = _with_delete_continuation(
                            delete_result["result"].get("message", ""),
                            continuation,
                        )
                    result_text = _format_delete_tool_response(delete_result["result"])
                elif project_check_result:
                    result_text = _format_project_check_response(project_check_result["result"])
                elif command_result:
                    result_text = _format_command_tool_response(command_result["result"])
                elif edit_text_result:
                    result_text = _format_text_edit_response(edit_text_result["result"])
                elif write_many_result:
                    result_text = _format_write_many_files_response(write_many_result["result"])
                elif _is_delete_request_text(req.content):
                    result_text = "没有定位到可删除目标。请提供更明确的文件名或完整路径，我会在标准模式下先弹出确认卡片。"
                else:
                    result_text = ""
                if result_text:
                    if full_content and not full_content.endswith("\n\n"):
                        full_content += "\n\n"
                    full_content += result_text
                    yield f"data: {json.dumps({'token': result_text}, ensure_ascii=False)}\n\n"
                    if three_d_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "generate_3d_image",
                            three_d_result["tool"],
                            three_d_result["result"],
                            "LLM tool call produced 3D result",
                            "tool_call",
                            _image_attachments(req.image_paths),
                        )
                    elif multiview_image_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "generate_multiview_images",
                            multiview_image_result["tool"],
                            multiview_image_result["result"],
                            "LLM tool call produced multiview images",
                            "tool_call",
                            _image_attachments(req.image_paths),
                        )
                    elif generated_image_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "generate_image",
                            generated_image_result["tool"],
                            generated_image_result["result"],
                            "LLM tool call produced image result",
                            "tool_call",
                            _image_attachments(req.image_paths),
                        )
                    elif generated_video_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "generate_video",
                            generated_video_result["tool"],
                            generated_video_result["result"],
                            "LLM tool call queued video generation",
                            "tool_call",
                            _image_attachments(req.image_paths),
                        )
                    elif delete_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "general_tools",
                            "delete_file",
                            delete_result["result"],
                            "LLM tool call produced delete result",
                            "tool_call",
                        )
                    elif project_check_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "general_tools",
                            "run_project_check",
                            project_check_result["result"],
                            "LLM tool call produced project check result",
                            "tool_call",
                        )
                    elif command_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "general_tools",
                            "run_command",
                            command_result["result"],
                            "LLM tool call produced command result",
                            "tool_call",
                        )
                    elif edit_text_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "general_tools",
                            "edit_text_file",
                            edit_text_result["result"],
                            "LLM tool call produced text edit result",
                            "tool_call",
                        )
                    elif write_many_result:
                        full_content += await _direct_agent_trace_block(
                            req,
                            provider_config,
                            "general_tools",
                            "write_many_files",
                            write_many_result["result"],
                            "LLM tool call produced multi-file write result",
                            "tool_call",
                        )

                    assistant_id, assistant_now = await _save_assistant_message(
                        db, req.conversation_id, full_content
                    )
                    try:
                        await memory_mgr.check_consolidation(conversation_id=req.conversation_id)
                    except Exception:
                        pass
                    yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': saved_memories}, ensure_ascii=False)}\n\n"
                    _schedule_title_generation(db, req)
                    return

            stream = await client.chat.completions.create(
                model=provider_config[1],
                messages=_fit_messages_to_context(messages, provider_config),
                stream=True,
            )
            buffered_text = ""
            buffering_for_textual_tool = True
            suppress_textual_tool_stream = False
            saw_textual_tool_marker = False
            async for chunk in stream:
                if (
                    chunk.choices
                    and chunk.choices[0].delta
                    and chunk.choices[0].delta.content
                ):
                    token = chunk.choices[0].delta.content
                    full_content += token
                    if buffering_for_textual_tool:
                        buffered_text += token
                        saw_textual_tool_marker = saw_textual_tool_marker or bool(TEXTUAL_TOOL_MARKER_PATTERN.search(buffered_text))
                        parsed_textual_tools = _extract_textual_tool_calls(buffered_text)
                        if parsed_textual_tools:
                            if any(tool_name in SUPPORTED_TEXTUAL_TOOL_NAMES for tool_name, _ in parsed_textual_tools):
                                suppress_textual_tool_stream = True
                                buffering_for_textual_tool = False
                                continue
                            buffering_for_textual_tool = False
                            token = buffered_text
                            buffered_text = ""
                        if saw_textual_tool_marker and not TEXTUAL_TOOL_CALLS_END_PATTERN.search(buffered_text):
                            continue
                        if len(buffered_text) < 512:
                            continue
                        buffering_for_textual_tool = False
                        token = buffered_text
                        buffered_text = ""
                    if not suppress_textual_tool_stream:
                        yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            if buffering_for_textual_tool and buffered_text and not suppress_textual_tool_stream:
                yield f"data: {json.dumps({'token': buffered_text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return

        textual_tool_results = _run_textual_tool_calls(full_content)
        if textual_tool_results:
            full_content = await _answer_from_textual_tool_results(
                client,
                provider_config[1],
                messages,
                req.content,
                textual_tool_results,
                provider_config,
            )
            trace_result = {
                "tool_count": len(textual_tool_results),
                "tools": [item.get("tool") for item in textual_tool_results],
                "results": textual_tool_results,
            }
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "general_tools",
                "textual_tool_calls",
                trace_result,
                "parsed textual tool calls fallback",
                "textual_tool_call",
            )

        assistant_id, assistant_now = await _save_assistant_message(
            db, req.conversation_id, full_content
        )

        try:
            await memory_mgr.check_consolidation(conversation_id=req.conversation_id)
        except Exception:
            pass

        yield f"data: {json.dumps({'done': True, 'message_id': assistant_id, 'content': full_content, 'created_at': assistant_now, 'saved_memories': saved_memories}, ensure_ascii=False)}\n\n"

        _schedule_title_generation(db, req)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
