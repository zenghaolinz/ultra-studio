import asyncio

from memory import manager as memory_mgr
from routes.direct_files import is_docx_create_intent, is_docx_edit_intent
from schemas import ChatRequest
from services.chat_asset_prompts import (
    contains_any,
    deterministic_asset_prompt,
    document_requirement_text,
)
from services.chat_confirmations import is_delete_request_text
from services.chat_documents import read_document_attachments
from services.chat_intents import is_3d_intent, is_image_generation_intent
from services.chat_paths import document_attachments
from services.chat_project_files import project_document_paths


def is_attachment_asset_intent(content: str, image_paths: list[str] | None) -> str | None:
    docs = document_attachments(image_paths)
    if not docs:
        return None
    text = (content or "").lower()
    if is_delete_request_text(text) or is_docx_create_intent(text) or is_docx_edit_intent(text):
        return None
    if is_3d_intent(content, None):
        return "3d"

    image_words = [
        "图片",
        "图像",
        "画",
        "绘图",
        "生图",
        "出图",
        "生成图",
        "生成一张",
        "再生成一张",
        "来一张",
        "做一张",
        "按要求",
        "根据要求",
        "按附件",
        "根据附件",
        "按文档",
        "根据文档",
        "image",
        "picture",
    ]
    if any(word in text for word in image_words):
        return "image"
    return None


def is_project_document_asset_intent(content: str, project_path: str | None) -> str | None:
    if not project_path:
        return None
    text = (content or "").lower()
    if not any(word in text for word in ["文档", "文本", "txt", "pdf", "docx", "要求", "document"]):
        return None
    if is_3d_intent(content, None):
        return "3d"
    if is_image_generation_intent(content, None):
        return "image"
    return None


async def build_asset_prompt_from_documents(
    user_request: str,
    document_sections: list[str],
    client,
    model_name: str,
    target: str,
) -> str:
    raw_context = "\n\n---\n\n".join(document_sections).strip()
    requirement_text = document_requirement_text(document_sections)
    fallback = deterministic_asset_prompt(requirement_text or raw_context or user_request, target)
    if requirement_text and len(requirement_text) <= 120:
        return fallback

    system_hint = (
        "你是本地生成工具的提示词生成器。根据用户要求和附件文档，输出可直接给生成工具的提示词。"
        "只输出提示词本身，不要解释，不要给方案，不要问用户。"
        "必须忠实保留文档里的主体、颜色、风格、材质、尺寸、用途等要求。"
        "除非文档明确要求人物，否则不要生成人、人物、男人、女人或肖像。"
    )
    if target == "image":
        system_hint += "目标工具是文生图。提示词应描述画面主体、风格、颜色、构图、背景和质量要求。"
    else:
        system_hint += "目标工具是文生3D模型。提示词应描述单个清晰主体、形体、材质、颜色、风格和可建模细节。"

    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": f"用户要求：{user_request}\n\n附件文档：\n{raw_context}"},
            ],
        )
        prompt = (response.choices[0].message.content or "").strip()
        person_words = ["人", "人物", "男人", "女人", "肖像", "human", "person", "man", "woman", "portrait"]
        if not contains_any(requirement_text, person_words):
            if contains_any(prompt, person_words):
                return fallback
        return prompt or fallback
    except Exception:
        return fallback


async def run_attachment_asset_request(req: ChatRequest, client, model_name: str) -> dict | None:
    target = is_attachment_asset_intent(req.content, req.image_paths)
    if not target:
        return None

    docs = document_attachments(req.image_paths)
    sections = read_document_attachments(docs)
    if not sections:
        return None

    prompt = await build_asset_prompt_from_documents(
        req.content,
        sections,
        client,
        model_name,
        target,
    )

    if target == "3d":
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_3d_from_text,
            prompt,
            "fast",
        )
        result["source_prompt"] = prompt
        return {"tool": "generate_3d_from_text", "result": result}

    result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, "fast")
    result["source_prompt"] = prompt
    return {"tool": "generate_image", "result": result}


async def run_project_document_asset_request(req: ChatRequest, client, model_name: str) -> dict | None:
    target = is_project_document_asset_intent(req.content, req.project_path)
    if not target or not req.project_path:
        return None

    docs = project_document_paths(req.project_path, req.content)
    if not docs:
        return {
            "tool": "generate_image" if target == "image" else "generate_3d_from_text",
            "result": {
                "status": "error",
                "message": f"没有在项目文件夹中找到匹配的文档: {req.project_path}",
            },
        }

    sections = read_document_attachments(docs)
    if not sections:
        return None

    prompt = await build_asset_prompt_from_documents(
        req.content,
        sections,
        client,
        model_name,
        target,
    )

    if target == "3d":
        result = await asyncio.to_thread(
            memory_mgr.handle_generate_3d_from_text,
            prompt,
            "fast",
        )
        result["source_prompt"] = prompt
        result["source_documents"] = docs
        return {"tool": "generate_3d_from_text", "result": result}

    result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, "fast")
    result["source_prompt"] = prompt
    result["source_documents"] = docs
    return {"tool": "generate_image", "result": result}
