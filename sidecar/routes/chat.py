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
from memory import stm as memory_stm
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
from services.chat_direct_media import (
    run_direct_3d_request as _run_direct_3d_request,
    run_direct_image_request as _run_direct_image_request,
    run_previous_3d_modification as _run_previous_3d_modification,
)
from services.chat_document_read import run_project_document_read as _run_project_document_read
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
    is_folder_summary_to_docx_intent as _is_folder_summary_to_docx_intent,
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
    extract_directory_path as _extract_directory_path,
    find_desktop_directory_by_mention as _find_desktop_directory_by_mention,
    format_path_resolution_card as _format_path_resolution_card,
    image_attachments as _image_attachments,
    is_document_path as _is_document_path,
    nearby_path_suggestions as _nearby_path_suggestions,
    resolve_local_path as _resolve_local_path,
)
from services.chat_router import (
    ROUTER_ACTIONS,
    model_capabilities as _model_capabilities,
    quality_mode_from_decision as _quality_mode_from_decision,
    router_safe_json as _router_safe_json,
)
from services.chat_router_context import (
    agent_trace_block as _agent_trace_block,
    build_router_context as _build_router_context,
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
    find_latest_multiview_paths as _find_latest_multiview_paths,
    inject_3d_context as _inject_3d_context,
    inject_image_context as _inject_image_context,
    inject_request_image_context as _inject_request_image_context,
)
from services.chat_project_files import (
    project_document_paths as _project_document_paths,
    project_image_paths as _project_image_paths,
)
from services.chat_documents import (
    folder_documents as _folder_documents,
    read_document_attachments as _read_document_attachments,
)
from services.chat_visual_prompts import build_visual_edit_prompt as _build_visual_edit_prompt

router = APIRouter()

MAX_TOOL_CALL_ROUNDS = 6

async def _summarize_folder_documents(req: ChatRequest, client, model_name: str) -> dict | None:
    if req.image_paths or not _is_folder_summary_to_docx_intent(req.content):
        return None
    folder = _extract_directory_path(req.content)
    if not folder and req.project_path:
        candidate = Path(req.project_path)
        if candidate.exists() and candidate.is_dir():
            folder = candidate
    if not folder:
        return {
            "needs_path": True,
            "message": _format_path_resolution_card(req.content, _nearby_path_suggestions(req.content)),
        }

    recursive = any(word in (req.content or "").lower() for word in ["递归", "包含子文件夹", "子目录", "recursive"])
    docs = _folder_documents(folder, recursive=recursive, limit=12)
    if not docs:
        return {
            "ok": False,
            "error": f"文件夹中没有找到可读取的文档: {folder}",
        }

    sections = []
    for doc in docs:
        result = memory_mgr.handle_read_document(str(doc), 9000)
        if not result.get("ok"):
            sections.append(f"[{doc.name}]\n读取失败：{result.get('error', 'unknown error')}")
            continue
        sections.append(
            f"[文件: {result.get('name') or doc.name}]\n路径: {result.get('path') or str(doc)}\n\n{result.get('content', '')}"
        )

    output_path = folder / "资料整理报告.docx"
    system_hint = (
        "你是资料整理助手。请基于用户给定文件夹内文档内容，输出 JSON，不要 Markdown。"
        '格式为 {"title":"标题","paragraphs":["段落1","段落2"]}。'
        "要求：按文档归纳重点，合并重复信息，保留关键结论、待办事项、风险或疑问；"
        "如果某些文件读取失败，也在最后简短说明。"
    )
    user_text = (
        f"用户需求：{req.content}\n\n"
        f"文件夹：{folder}\n"
        f"已读取文档数量：{len(docs)}\n\n"
        "文档内容如下：\n\n"
        + "\n\n---\n\n".join(sections)
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": user_text},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception:
        payload = {}

    title = str(payload.get("title") or "资料整理报告").strip()
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        paragraphs = [
            f"已读取文件夹：{folder}",
            f"共发现 {len(docs)} 个可读取文档。",
            "模型未能生成结构化整理内容，请重试或缩小文档范围。",
        ]

    create_result = memory_mgr.handle_create_docx_document(
        str(output_path),
        title,
        [str(item) for item in paragraphs if str(item).strip()],
        False,
    )
    if create_result.get("ok"):
        create_result["source_folder"] = str(folder)
        create_result["document_count"] = len(docs)
        create_result["documents"] = [str(doc) for doc in docs]
    return create_result


async def _llm_route_request(client, model_name: str, req: ChatRequest, provider_config=None) -> dict | None:
    if _is_delete_request_text(req.content):
        return {"action": "general_tools", "reason": "delete requests must use confirmed file tools"}
    if any(word in (req.content or "").lower() for word in ["cmd", "powershell", "命令", "终端", "运行", "执行", "测试", "构建", "build", "test", "npm", "git status", "git diff"]):
        return {"action": "general_tools", "reason": "system command or project verification request must use local tools"}
    if memory_mgr.infer_tool_scope(req.content, req.image_paths) == "web":
        return {"action": "general_tools", "reason": "web search requests must use web tools"}
    capabilities = _model_capabilities(provider_config, req.vision_enabled)
    context = await _build_router_context(req, capabilities)
    system_hint = (
        "你是 Ultra Studio 的工具路由器。只输出 JSON，不要 Markdown。"
        "根据用户请求和上下文选择一个 action。"
        "可选 action: chat, general_tools, generate_image, generate_video, edit_image, generate_3d_text, "
        "generate_3d_image, generate_3d_fusion, generate_multiview_images, generate_3d_multiview, project_document_image, project_document_3d, "
        "attachment_document_image, attachment_document_3d, read_document, create_docx, edit_docx, folder_summary_docx, create_text_file, choose_implementation。"
        "规则：如果用户要生成/画一张新图片，选 generate_image；如果用户要生成视频、短片、动画、图生视频或文生视频，选 generate_video；如果用户上传图片、引用 latest_active_image，或要求修改项目/文件夹里的图片，并要求补全、画完整、扩图、改颜色、润色、修改，选 edit_image；"
        "如果用户要求创建本地代码、脚本、网页、HTML、Markdown、TXT、JSON、CSS/JS/Python 文件、可运行 Demo、小游戏或工具，选 create_text_file；"
        "如果用户是在已有/刚生成的代码、HTML、网页、小游戏或文本文件上要求加入、添加、修改、修复、优化、美化某个功能，选 general_tools，不要选 create_text_file，也不要删除旧文件。"
        "create_text_file 支持一次请求创建多个文件，适合需要 index.html/style.css/app.js、多个脚本或项目骨架的任务。"
        "如果用户要创建可运行的软件/小游戏/工具，但没有指定实现载体，且 HTML、Python、本地脚本或 Web UI 都合理，选 choose_implementation，让界面弹出选项；"
        "如果请求已经明确指定 HTML、Python、网页、单文件、浏览器、Tkinter、Pygame 等实现方式，不要选 choose_implementation，直接选 create_text_file。"
        "不要把小游戏、脚本或网页创建误判为 Word 文档；只有用户明确说 Word/DOCX/文档报告时才选 create_docx。"
        "如果用户基于单张上传图片或 latest_active_image 要求生成三视图/前左后视图，选 generate_multiview_images；"
        "如果用户要求用已经由系统生成且上下文 latest_multiview 明确标注 front/left/back 的三视图继续生成 3D 模型，选 generate_3d_multiview；"
        "不要将用户上传的多张未标注图片交给 LLM 判断视角后选择 generate_3d_multiview。"
        "如果一个请求包含两个或更多需要依次执行、且后一步依赖前一步输出文件的操作，选 general_tools，让 Agent 使用工具结果继续规划和调用下一步；不要把多步骤请求压缩成单个生成 action。"
        "如果用户要 3D/模型/GLB，按是否有图片选择 generate_3d_image/generate_3d_fusion/generate_3d_text；"
        "如果用户说根据文档/文本/附件/项目文件夹要求生成图片或模型，优先选 project_document_image/project_document_3d 或 attachment_document_image/attachment_document_3d；"
        "如果用户要求读取、总结、分析项目文件夹内的 docx/pdf/txt/md 等文档，选 read_document 或 folder_summary_docx。"
        "如果 model_capabilities.supports_vision=false，不要声称已看懂图片内容；可以选择 edit_image 让图像工作流基于源图执行，或在无源图时选择 generate_image。"
        "如果只是问答或描述图片内容，选 chat；如果需要本地文件工具但不属于上述生成任务，选 general_tools。"
        "质量选择：如果用户明确要求高质量、更精细、慢一点但效果更好，quality_mode 选 quality；如果用户没有明确要求质量，quality_mode 必须选 fast。"
        "输出格式: {\"action\":\"...\",\"prompt\":\"可选的优化后提示词\",\"quality_mode\":\"fast|quality\",\"source\":\"latest_active_image|attached_image|project_image|document|project_document|none\",\"source_files\":[\"可选路径\"],\"reason\":\"一句话原因\"}"
    )
    user_text = json.dumps(
        {
            "user_request": req.content,
            "context": context,
        },
        ensure_ascii=False,
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": user_text},
            ],
            response_format={"type": "json_object"},
        )
        decision = _router_safe_json(response.choices[0].message.content or "{}")
    except Exception as e:
        print(f"[router] route failed: {e}")
        return None

    action = str(decision.get("action") or "chat").strip()
    if action not in ROUTER_ACTIONS:
        return None
    decision["action"] = action
    decision.setdefault("prompt", req.content)
    decision["quality_mode"] = _quality_mode_from_decision(decision)
    print(f"[router] action={action} quality={decision.get('quality_mode')} source={decision.get('source')} reason={decision.get('reason')}")
    return decision


async def _run_router_action(decision: dict, req: ChatRequest, client, model_name: str, provider_config=None) -> dict | str | None:
    action = decision.get("action")
    prompt = str(decision.get("prompt") or req.content).strip() or req.content
    quality_mode = _quality_mode_from_decision(decision)
    capabilities = _model_capabilities(provider_config, req.vision_enabled)

    if action == "choose_implementation":
        return {
            "tool": "implementation_choice",
            "result": {"ok": True, "message": _format_implementation_choice_card(req.content)},
        }

    if action == "create_text_file":
        result = await _run_direct_text_file_create(req, client, model_name, force=True, prompt_override=prompt)
        return {"tool": "create_text_file", "result": result or {"ok": False, "error": "没有生成可写入的本地文件内容"}}

    if action == "generate_image":
        result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, quality_mode, req.conversation_id)
        result["source_prompt"] = prompt
        result["quality_mode"] = quality_mode
        return {"tool": "generate_image", "result": result}

    if action == "generate_video":
        image_paths = [os.path.normpath(path) for path in _image_attachments(req.image_paths)]
        source = image_paths[0] if image_paths else await _find_latest_edit_source_image(req.conversation_id)
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_video,
            prompt,
            source,
            quality_mode if quality_mode in {"fast", "quality"} else "quality",
            4,
            1024,
            576,
            req.conversation_id,
        )
        result["source_prompt"] = prompt
        result["source_image"] = source
        return {"tool": "generate_video", "result": result}

    if action == "edit_image":
        source = None
        image_paths = _image_attachments(req.image_paths)
        if image_paths:
            source = os.path.normpath(image_paths[0])
        if not source:
            source = await _find_latest_edit_source_image(req.conversation_id)
        if not source:
            project_images = _project_image_paths(req.project_path, req.content, limit=1)
            source = os.path.normpath(project_images[0]) if project_images else None
        if not source:
            if not capabilities.get("supports_vision"):
                result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, quality_mode, req.conversation_id)
                result["source_prompt"] = prompt
                result["source_mode"] = "text_only_model_no_source_image"
                result["quality_mode"] = quality_mode
                return {"tool": "generate_image", "result": result}
            return {
                "tool": "edit_image",
                "result": {"status": "error", "message": "没有找到可编辑的源图片，请先上传图片、生成一张图片，或在当前项目文件夹中放入图片。"},
            }
        edit_prompt = await _build_visual_edit_prompt(client, model_name, source, prompt, capabilities)
        result = await asyncio.to_thread(memory_mgr.handle_modify_image, source, edit_prompt, 0.5, req.conversation_id)
        result["source_prompt"] = edit_prompt
        result["source_image"] = source
        result["used_multimodal_prompt"] = bool(capabilities.get("supports_vision") and edit_prompt != prompt)
        return {"tool": "edit_image", "result": result}

    if action == "generate_3d_text":
        result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_text, prompt, quality_mode, req.conversation_id)
        result["quality_mode"] = quality_mode
        return {"tool": "generate_3d_from_text", "result": result}

    if action in {"generate_3d_image", "generate_3d_fusion"}:
        image_paths = [os.path.normpath(path) for path in _image_attachments(req.image_paths)]
        if not image_paths:
            latest = await _find_latest_edit_source_image(req.conversation_id)
            if latest:
                image_paths = [latest]
        if action == "generate_3d_fusion" and len(image_paths) >= 2:
            result = await asyncio.to_thread(memory_mgr.handle_generate_3d_fusion, image_paths[0], image_paths[1], prompt, req.conversation_id)
            return {"tool": "generate_3d_fusion", "result": result}
        if image_paths:
            result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_image, image_paths[0], req.conversation_id)
            return {"tool": "generate_3d_from_image", "result": result}
        result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_text, prompt, quality_mode, req.conversation_id)
        result["quality_mode"] = quality_mode
        return {"tool": "generate_3d_from_text", "result": result}

    if action == "generate_multiview_images":
        image_paths = [os.path.normpath(path) for path in _image_attachments(req.image_paths)]
        source = image_paths[0] if image_paths else await _find_latest_edit_source_image(req.conversation_id)
        if not source:
            return {
                "tool": "generate_multiview_images_from_image",
                "result": {"status": "error", "message": "没有找到源图片，请先上传一张图片或先生成一张图片。"},
            }
        result = await asyncio.to_thread(memory_mgr.handle_generate_multiview_images_from_image, source, quality_mode, req.conversation_id)
        result["source_image"] = source
        result["quality_mode"] = quality_mode
        return {"tool": "generate_multiview_images_from_image", "result": result}

    if action == "generate_3d_multiview":
        views = await _find_latest_multiview_paths(req.conversation_id)
        if not views:
            return {
                "tool": "generate_3d_from_generated_multiview",
                "result": {"status": "error", "message": "没有找到系统已知视角的 front/left/back 三视图，请先生成三视图。"},
            }
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_3d_from_generated_multiview,
            views["front"],
            views["left"],
            views["back"],
            quality_mode,
            req.conversation_id,
        )
        result["quality_mode"] = quality_mode
        return {"tool": "generate_3d_from_generated_multiview", "result": result}

    if action in {"project_document_image", "project_document_3d"}:
        return await _run_project_document_asset_request(req, client, model_name)

    if action in {"attachment_document_image", "attachment_document_3d"}:
        return await _run_attachment_asset_request(req, client, model_name)

    if action == "folder_summary_docx":
        return await _summarize_folder_documents(req, client, model_name)

    if action == "create_docx":
        return await _run_direct_docx_create(req, client, model_name)

    if action == "edit_docx":
        return await _run_direct_docx_edit(req, client, model_name)

    if action == "read_document":
        direct = await _run_direct_document_read(req, client, model_name)
        if direct is not None:
            return direct
        return await _run_project_document_read(req, client, model_name)

    return None


async def _run_tool_calls(
    client,
    model_name,
    messages,
    tools,
    conversation_id: str = "",
    permission_mode: str = "standard",
    force_file_action: bool = False,
    status_callback=None,
):
    saved_memories = []
    tool_results = []
    read_file_paths: set[str] = set()
    for _ in range(MAX_TOOL_CALL_ROUNDS):
        if force_file_action and not _first_tool_result(tool_results, "delete_file"):
            messages.append({
                "role": "system",
                "content": (
                    "当前任务是本地文件删除。必须通过工具完成，不能用普通文本回答。"
                    "如果目标在文件夹中，先 list_directory；目录列表返回后，选择精确子文件 path 调用 delete_file。"
                    "标准模式 confirmed=false；自主模式可以 confirmed=true。"
                ),
            })
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            if force_file_action and not _first_tool_result(tool_results, "delete_file"):
                messages.append({
                    "role": "system",
                    "content": (
                        "用户请求的是本地文件删除任务。不能用普通文本回答无法访问。"
                        "你必须继续使用工具完成：如果还没有定位目标，调用 list_directory；"
                        "如果已经从目录列表中看到了匹配的文本文件，调用 delete_file。"
                        "标准权限下 delete_file confirmed=false 以触发确认卡片；自主模式可以直接删除。"
                    ),
                })
                continue
            return messages, tool_results, saved_memories

        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            if status_callback:
                await status_callback(tool_call.function.name)
                await asyncio.sleep(0)
            if tool_call.function.name == "recall_memory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    branch_path = args.get("branch_path", "")
                    results = memory_mgr.handle_recall_memory(branch_path)
                except Exception as e:
                    results = [{"error": str(e)}]

                tool_results.append({"tool": tool_call.function.name, "result": results})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(results, ensure_ascii=False),
                    }
                )
            elif tool_call.function.name == "save_memory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    content = args.get("content", "")
                    branch_path = args.get("branch_path", "个人/喜好偏好")
                    tags = args.get("tags", [])
                    save_result = memory_mgr.handle_save_memory(
                        content, branch_path, tags
                    )
                except Exception as e:
                    save_result = {"ok": False, "error": str(e)}

                if save_result.get("ok"):
                    saved_memories.append(content)
                tool_results.append({"tool": tool_call.function.name, "result": save_result})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(save_result, ensure_ascii=False),
                    }
                )
            elif tool_call.function.name == "generate_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_image(
                        args.get("prompt", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await _inject_image_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_video":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_video(
                        args.get("prompt", ""),
                        args.get("image_path") or None,
                        args.get("quality_mode", "quality"),
                        int(args.get("duration_seconds", 4)),
                        int(args.get("width", 1024)),
                        int(args.get("height", 576)),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "generate_3d_from_text":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_text(
                        args.get("prompt", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await _inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_from_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_image(
                        args.get("image_path", ""),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        parts = []
                        if result.get("image_2d"):
                            parts.append(f"[System Context: 活跃生成图片路径=\"{result['image_2d']}\"]")
                        if result.get("model_path"):
                            parts.append(f"[System Context: 活跃模型路径=\"{result['model_path']}\"]")
                        if parts:
                            await memory_stm.inject_system_context(conversation_id, "\n".join(parts))
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_fusion":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_fusion(
                        args.get("image1_path", ""),
                        args.get("image2_path", ""),
                        args.get("prompt", ""),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await _inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_multiview_images_from_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_multiview_images_from_image(
                        args.get("image_path", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await _inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_from_generated_multiview":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_generated_multiview(
                        args.get("front_path", ""),
                        args.get("left_path", ""),
                        args.get("back_path", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await _inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "modify_image_with_flux":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_modify_image(
                        args.get("source_path", ""),
                        args.get("modification_prompt", ""),
                        args.get("denoise_strength", 0.5),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success" and result.get("improved_image_path"):
                    try:
                        ctx_msg = f"[System Context: 活跃图像路径=\"{result['improved_image_path']}\"]"
                        await memory_stm.inject_system_context(conversation_id, ctx_msg)
                    except Exception:
                        pass
            elif tool_call.function.name == "read_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_read_document(
                        args.get("file_path", ""),
                        int(args.get("max_chars", 12000)),
                    )
                    if result.get("ok") and result.get("path"):
                        read_file_paths.add(str(Path(result["path"]).resolve()).lower())
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "read_many_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_read_many_files(
                        args.get("file_paths", []),
                        int(args.get("max_chars_per_file", 8000)),
                        int(args.get("max_files", 12)),
                    )
                    for item in result.get("files") or []:
                        if isinstance(item, dict) and item.get("path"):
                            read_file_paths.add(str(Path(item["path"]).resolve()).lower())
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "web_search":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_web_search(
                        args.get("query", ""),
                        int(args.get("max_results", 5)),
                        args.get("recency_days"),
                        args.get("domains", []),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e), "results": []}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "web_fetch":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_web_fetch(
                        args.get("url", ""),
                        int(args.get("max_chars", 12000)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "list_directory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_list_directory(
                        args.get("directory_path", ""),
                        bool(args.get("recursive", False)),
                        int(args.get("max_items", 120)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if force_file_action:
                    messages.append({
                        "role": "system",
                        "content": (
                            "上面是目录列表。若用户要求删除文件夹里的文本文档，请从 items 中选择 .txt/.md 等文本文件的精确 path，"
                            "然后调用 delete_file，target_type=file，recursive=false。不要删除父文件夹，也不要回答没有权限。"
                        ),
                    })
            elif tool_call.function.name == "search_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_search_files(
                        args.get("directory_path", ""),
                        args.get("query", ""),
                        args.get("file_glob", "*"),
                        bool(args.get("recursive", True)),
                        bool(args.get("search_content", True)),
                        int(args.get("max_matches", 80)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "organize_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_organize_files(
                        args.get("directory_path", ""),
                        args.get("strategy", "by_type"),
                        bool(args.get("apply_changes", False)),
                        bool(args.get("recursive", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "edit_text_file":
                try:
                    args = json.loads(tool_call.function.arguments)
                    file_path = str(Path(args.get("file_path", "")).resolve()).lower()
                    if file_path not in read_file_paths:
                        result = {
                            "ok": False,
                            "error": "修改已有文本文件前必须先调用 read_document 或 read_many_files 读取该文件内容。",
                            "path": args.get("file_path", ""),
                            "needs_read": True,
                        }
                    else:
                        result = memory_mgr.handle_edit_text_file(
                            args.get("file_path", ""),
                            args.get("action", ""),
                            args.get("text", ""),
                            args.get("find", ""),
                            args.get("replace", ""),
                            bool(args.get("use_regex", False)),
                            bool(args.get("backup", False)),
                        )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if (
                    not result.get("ok")
                    and "未找到要替换的内容" in str(result.get("error") or "")
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 edit_text_file 的精确 replace 没有命中。不要把失败直接返回给用户。"
                                "请先用 read_document 读取该文件确认当前内容，然后用 write_many_files 写回完整更新后的文件，"
                                "或用更可靠的 edit_text_file 参数重试。用户要的是完成修改文件。"
                            ),
                        }
                    )
                elif result.get("needs_read"):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 edit_text_file 被拦截，因为还没有读取目标文件。"
                                "请先调用 read_document 读取同一路径，再基于读取到的真实内容调用 edit_text_file。"
                                "不要改用创建新文件或删除旧文件。"
                            ),
                        }
                    )
            elif tool_call.function.name == "write_many_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    root_path = Path(args.get("root_path", "")).resolve()
                    files = args.get("files", [])
                    overwrite = bool(args.get("overwrite", False))
                    unread_existing = []
                    if overwrite:
                        for item in files or []:
                            if not isinstance(item, dict):
                                continue
                            raw_name = str(item.get("path") or item.get("filename") or item.get("name") or "").replace("\\", "/")
                            parts = [part for part in raw_name.lstrip("/").split("/") if part not in {"", ".", ".."}]
                            if not parts:
                                continue
                            target = (root_path / Path(*parts)).resolve()
                            if target.exists() and str(target).lower() not in read_file_paths:
                                unread_existing.append(str(target))
                    if unread_existing:
                        result = {
                            "ok": False,
                            "error": "覆盖已有文本/代码文件前必须先读取原文件内容。",
                            "paths": unread_existing,
                            "needs_read": True,
                        }
                    else:
                        result = memory_mgr.handle_write_many_files(
                            args.get("root_path", ""),
                            files,
                            overwrite,
                        )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_read"):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 write_many_files 覆盖已有文件被拦截，因为还没有读取原文件。"
                                "请先调用 read_document 或 read_many_files 读取 paths 中的目标文件，"
                                "再选择 edit_text_file 精确修改，或在确实需要整文件写回时 overwrite=true 写回同一路径。"
                            ),
                        }
                    )
            elif tool_call.function.name == "run_command":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_run_command(
                        args.get("command", ""),
                        args.get("cwd", ""),
                        args.get("shell", "powershell"),
                        int(args.get("timeout_seconds", 60)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_confirmation"):
                    return messages, tool_results, saved_memories
            elif tool_call.function.name == "run_project_check":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_run_project_check(
                        args.get("project_path", ""),
                        args.get("check_type", "auto"),
                        int(args.get("timeout_seconds", 180)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_confirmation"):
                    return messages, tool_results, saved_memories
            elif tool_call.function.name == "delete_file":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_delete_path(
                        args.get("target_path", ""),
                        args.get("target_type", "auto"),
                        bool(args.get("recursive", False)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                return messages, tool_results, saved_memories
            elif tool_call.function.name == "create_docx_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_create_docx_document(
                        args.get("file_path", ""),
                        args.get("title", ""),
                        args.get("paragraphs", []),
                        bool(args.get("overwrite", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "edit_docx_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_edit_docx_document(
                        args.get("file_path", ""),
                        args.get("action", ""),
                        args.get("text", ""),
                        args.get("find", ""),
                        args.get("replace", ""),
                        bool(args.get("backup", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            else:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": "Unknown function"}),
                    }
                )

    return messages, tool_results, saved_memories


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

    direct_text_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1])
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
        else await _run_project_document_asset_request(req, client, provider_config[1])
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
        else await _run_attachment_asset_request(req, client, provider_config[1])
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
        else await _summarize_folder_documents(req, client, provider_config[1])
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
        else await _run_direct_text_file_create(req, client, provider_config[1])
    )
    if direct_text_file_result:
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
        else await _run_direct_docx_edit(req, client, provider_config[1])
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
        else await _run_direct_docx_create(req, client, provider_config[1])
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
        else await _run_direct_document_read(req, client, provider_config[1])
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

    if tools:
        messages, tool_results, saved_memories = await _run_tool_calls(
            client,
            provider_config[1],
            messages,
            tools,
            req.conversation_id,
            req.permission_mode,
            _is_delete_request_text(req.content),
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
    if (
        edit_text_result
        and _edit_text_result_can_fallback(edit_text_result.get("result"))
        and not (write_many_result and isinstance(write_many_result.get("result"), dict) and write_many_result["result"].get("ok"))
        and _is_text_file_edit_followup_intent(req.content)
    ):
        fallback_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1])
        if fallback_edit_result and fallback_edit_result.get("ok"):
            edit_text_result = {"tool": "edit_text_file", "result": fallback_edit_result}
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
                messages=messages,
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
            direct_text_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1])
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
        else await _summarize_folder_documents(req, client, provider_config[1])
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
        else await _run_direct_text_file_create(req, client, provider_config[1])
    )
    if direct_text_file_result:
        async def direct_text_file_event_generator():
            start_text = "正在创建新文件。\n\n"
            final_text = _format_text_file_create_response(direct_text_file_result)
            full_content = start_text + final_text
            yield f"data: {json.dumps({'token': start_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'token': final_text}, ensure_ascii=False)}\n\n"
            full_content += await _direct_agent_trace_block(
                req,
                provider_config,
                "create_text_file",
                "create_text_file",
                direct_text_file_result,
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
        else await _run_direct_docx_edit(req, client, provider_config[1])
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
        else await _run_direct_docx_create(req, client, provider_config[1])
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
        else await _run_direct_document_read(req, client, provider_config[1])
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
        messages = context_messages
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
                if (
                    edit_text_result
                    and _edit_text_result_can_fallback(edit_text_result.get("result"))
                    and not (write_many_result and isinstance(write_many_result.get("result"), dict) and write_many_result["result"].get("ok"))
                    and _is_text_file_edit_followup_intent(req.content)
                ):
                    yield f"data: {json.dumps({'status': '正在调用工具：edit_text_file'}, ensure_ascii=False)}\n\n"
                    fallback_edit_result = await _run_direct_text_file_edit(req, client, provider_config[1])
                    if fallback_edit_result and fallback_edit_result.get("ok"):
                        edit_text_result = {"tool": "edit_text_file", "result": fallback_edit_result}
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
                messages=messages,
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
