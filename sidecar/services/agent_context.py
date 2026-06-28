import base64
import mimetypes
import os
from typing import Any

from services.chat_paths import IMAGE_EXTENSIONS


SYSTEM_CONTRACT = """You are Ultra Studio's creation and project assistant.
Use the available tools when the request requires files, web access, image/video/3D generation, or local execution.
Treat attachment and resolved-artifact paths as exact local paths. Never invent or silently swap a path.
Read a document with a file tool before making claims about its contents.
Do not claim that a generated or written output exists until its tool result confirms it.
Ask for clarification when the requested target cannot be resolved safely."""

FILE_KINDS = {"document", "code", "archive", "file"}
GENERATION_KINDS = {"image", "audio", "video", "model"}


def infer_agent_capabilities(
    content: str,
    *,
    attachment_kinds: set[str] | None = None,
    resolved_kinds: set[str] | None = None,
) -> set[str]:
    text = (content or "").lower()
    kinds = set(attachment_kinds or set()) | set(resolved_kinds or set())
    capabilities: set[str] = set()
    file_tokens = [
        "file", "document", "pdf", "word", "docx", "code", "script",
        "folder", "directory", "project", "app", "website", "game",
        "文件", "文档", "代码", "脚本", "目录", "文件夹", "项目", "网页", "游戏",
    ]
    web_tokens = [
        "search the web", "web search", "search online", "latest news", "current information",
        "搜索网页", "联网搜索", "网上查", "最新消息", "当前信息",
    ]
    generation_tokens = [
        "generate image", "create image", "edit image", "generate video", "3d model",
        "生成图片", "画一张", "修改图片", "生成视频", "生成模型", "3d模型", "三维模型",
    ]
    if kinds & FILE_KINDS or any(token in text for token in file_tokens):
        capabilities.add("files")
    if kinds & GENERATION_KINDS or any(token in text for token in generation_tokens):
        capabilities.add("generation")
    if any(token in text for token in web_tokens):
        capabilities.add("web")
    return capabilities


def _attachment_text(user_input: str, attachment_paths: list[str] | None) -> str:
    existing = [
        os.path.normpath(path)
        for path in attachment_paths or []
        if isinstance(path, str) and os.path.isfile(os.path.normpath(path))
    ]
    if not existing:
        return user_input
    paths = "\n".join(f"- {path}" for path in existing)
    return f"{user_input}\n\n[Current message attachments]\n{paths}"


def _user_content(
    user_text: str,
    attachment_paths: list[str] | None,
    *,
    include_image_content: bool,
) -> str | list[dict[str, Any]]:
    if not include_image_content:
        return user_text
    parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for path_text in attachment_paths or []:
        path = os.path.normpath(path_text)
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS or not os.path.isfile(path):
            continue
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        })
    return parts if len(parts) > 1 else user_text


async def build_agent_context(
    db,
    *,
    conversation_id: str,
    user_input: str,
    current_message_id: str | None = None,
    attachment_paths: list[str] | None = None,
    include_image_content: bool = False,
    history_limit: int = 20,
) -> list[dict[str, Any]]:
    clauses = ["conversation_id = ?", "(visible IS NULL OR visible = 1)"]
    parameters: list[Any] = [conversation_id]
    if current_message_id:
        clauses.append("id != ?")
        parameters.append(current_message_id)
    parameters.append(history_limit)
    rows = await db.execute_fetchall(
        f"""
        SELECT role, content FROM stm_entries
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC LIMIT ?
        """,
        tuple(parameters),
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_CONTRACT}]
    messages.extend(
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
        if row["role"] in {"user", "assistant"}
    )
    user_text = _attachment_text(user_input, attachment_paths)
    messages.append({
        "role": "user",
        "content": _user_content(
            user_text,
            attachment_paths,
            include_image_content=include_image_content,
        ),
    })
    return messages
