import asyncio
import os

from memory import manager as memory_mgr
from services.chat_generation_context import find_latest_edit_source_image, resolve_referenced_image_asset
from services.chat_intents import (
    has_previous_image_reference,
    is_3d_intent,
    is_image_edit_intent,
    is_image_generation_intent,
    is_modify_previous_3d_intent,
    is_previous_image_edit_intent,
)
from services.chat_paths import IMAGE_EXTENSIONS
from services.chat_project_files import project_image_paths


async def run_direct_image_request(
    content: str,
    image_paths: list[str] | None,
    conversation_id: str | None = None,
    project_path: str | None = None,
) -> dict | None:
    if is_image_edit_intent(content, image_paths):
        source = next(
            (
                os.path.normpath(path)
                for path in image_paths or []
                if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
            ),
            None,
        )
        if not source:
            return None
        result = await asyncio.to_thread(memory_mgr.handle_modify_image, source, content.strip())
        return {"tool": "edit_image", "result": result}

    if conversation_id and is_previous_image_edit_intent(content):
        explicit_reference = has_previous_image_reference(content)
        source = await resolve_referenced_image_asset(conversation_id, content)
        if not source:
            source = await find_latest_edit_source_image(conversation_id)
        if not source and explicit_reference:
            project_images = project_image_paths(project_path, content, limit=1)
            source = os.path.normpath(project_images[0]) if project_images else None
        if source:
            result = await asyncio.to_thread(memory_mgr.handle_modify_image, source, content.strip())
            return {"tool": "edit_image", "result": result}

    if is_image_generation_intent(content, image_paths):
        result = await asyncio.to_thread(memory_mgr.handle_generate_image, content.strip(), "fast")
        return {"tool": "generate_image", "result": result}

    return None


async def run_direct_3d_request(content: str, image_paths: list[str] | None) -> dict | None:
    if not is_3d_intent(content, image_paths):
        return None

    paths = [
        os.path.normpath(path)
        for path in image_paths or []
        if path and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]
    if not paths:
        prompt = content.strip()
        if not prompt:
            return {
                "tool": "generate_3d_from_text",
                "result": {"status": "error", "message": "Prompt cannot be empty"},
            }
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_3d_from_text,
            prompt,
            "fast",
        )
        return {"tool": "generate_3d_from_text", "result": result}

    if len(paths) >= 2:
        prompt = content.strip() or "Fuse these two images into one coherent 3D asset"
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_3d_fusion,
            paths[0],
            paths[1],
            prompt,
        )
        return {"tool": "generate_3d_fusion", "result": result}

    result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_image, paths[0])
    return {"tool": "generate_3d_from_image", "result": result}


async def run_previous_3d_modification(
    conversation_id: str,
    content: str,
    image_paths: list[str] | None,
) -> dict | None:
    if not is_modify_previous_3d_intent(content, image_paths):
        return None

    source_image = await find_latest_edit_source_image(conversation_id)
    if not source_image:
        if is_3d_intent(content, image_paths):
            return None
        return {
            "tool": "modify_previous_3d",
            "result": {
                "status": "error",
                "message": "No previous Flux source image was found, so the previous 3D model cannot be modified.",
            },
        }

    improved = await asyncio.to_thread(
        memory_mgr.handle_modify_image,
        source_image,
        content.strip(),
        0.5,
    )
    if improved.get("status") != "success" or not improved.get("improved_image_path"):
        return {"tool": "modify_previous_3d", "result": improved}

    regenerated = await asyncio.to_thread(
        memory_mgr.handle_generate_3d_from_image,
        improved["improved_image_path"],
    )
    if regenerated.get("status") == "success":
        regenerated["image_2d"] = improved["improved_image_path"]
        regenerated["source_image"] = source_image
        regenerated["message"] = "Modified previous Flux image and regenerated 3D."
    return {"tool": "modify_previous_3d", "result": regenerated}
