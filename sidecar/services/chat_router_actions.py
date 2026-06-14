import asyncio
import os

from memory import manager as memory_mgr
from routes.direct_files import (
    format_implementation_choice_card,
    run_direct_document_read,
    run_direct_docx_create,
    run_direct_docx_edit,
    run_direct_text_file_create,
)
from schemas import ChatRequest
from services.chat_document_assets import (
    run_attachment_asset_request,
    run_project_document_asset_request,
)
from services.chat_document_read import run_project_document_read
from services.chat_folder_summary import summarize_folder_documents
from services.chat_generation_context import (
    find_latest_edit_source_image,
    find_latest_multiview_paths,
)
from services.chat_paths import image_attachments
from services.chat_project_files import project_image_paths
from services.chat_result_repair import repair_text_create_result
from services.chat_router import model_capabilities, quality_mode_from_decision
from services.chat_visual_prompts import build_visual_edit_prompt


async def run_router_action(decision: dict, req: ChatRequest, client, model_name: str, provider_config=None) -> dict | str | None:
    action = decision.get("action")
    prompt = str(decision.get("prompt") or req.content).strip() or req.content
    quality_mode = quality_mode_from_decision(decision)
    capabilities = model_capabilities(provider_config, req.vision_enabled)

    if action == "choose_implementation":
        return {
            "tool": "implementation_choice",
            "result": {"ok": True, "message": format_implementation_choice_card(req.content)},
        }

    if action == "create_text_file":
        result = await run_direct_text_file_create(
            req,
            client,
            model_name,
            force=True,
            prompt_override=prompt,
            provider_config=provider_config,
        )
        result, _ = await repair_text_create_result(
            req,
            client,
            model_name,
            provider_config,
            result,
            force=True,
            prompt_override=prompt,
        )
        return {"tool": "create_text_file", "result": result or {"ok": False, "error": "没有生成可写入的本地文件内容"}}

    if action == "generate_image":
        result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, quality_mode, req.conversation_id)
        result["source_prompt"] = prompt
        result["quality_mode"] = quality_mode
        return {"tool": "generate_image", "result": result}

    if action == "generate_video":
        image_paths = [os.path.normpath(path) for path in image_attachments(req.image_paths)]
        source = image_paths[0] if image_paths else await find_latest_edit_source_image(req.conversation_id)
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
        image_paths = image_attachments(req.image_paths)
        if image_paths:
            source = os.path.normpath(image_paths[0])
        if not source:
            source = await find_latest_edit_source_image(req.conversation_id)
        if not source:
            project_images = project_image_paths(req.project_path, req.content, limit=1)
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
        edit_prompt = await build_visual_edit_prompt(client, model_name, source, prompt, capabilities, provider_config)
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
        image_paths = [os.path.normpath(path) for path in image_attachments(req.image_paths)]
        if not image_paths:
            latest = await find_latest_edit_source_image(req.conversation_id)
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
        image_paths = [os.path.normpath(path) for path in image_attachments(req.image_paths)]
        source = image_paths[0] if image_paths else await find_latest_edit_source_image(req.conversation_id)
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
        views = await find_latest_multiview_paths(req.conversation_id)
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
        return await run_project_document_asset_request(req, client, model_name, provider_config)

    if action in {"attachment_document_image", "attachment_document_3d"}:
        return await run_attachment_asset_request(req, client, model_name, provider_config)

    if action == "folder_summary_docx":
        return await summarize_folder_documents(req, client, model_name, provider_config)

    if action == "create_docx":
        return await run_direct_docx_create(req, client, model_name, provider_config)

    if action == "edit_docx":
        return await run_direct_docx_edit(req, client, model_name, provider_config)

    if action == "read_document":
        direct = await run_direct_document_read(req, client, model_name, provider_config)
        if direct is not None:
            return direct
        return await run_project_document_read(req, client, model_name, provider_config)

    return None
