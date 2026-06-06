import uuid
import datetime
import traceback
import json
import asyncio
import os
import re
import shutil
import base64
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from db.sqlite import get_db
from memory import manager as memory_mgr
from memory import stm as memory_stm
from schemas import ChatRequest
from routes.direct_files import (
    edit_text_result_can_fallback as _edit_text_result_can_fallback,
    extract_explicit_text_file_path as _extract_explicit_text_file_path,
    find_latest_text_file_path as _find_latest_text_file_path,
    format_docx_create_response as _format_docx_create_response,
    format_docx_edit_response as _format_docx_edit_response,
    format_implementation_choice_card as _format_implementation_choice_card,
    format_text_file_create_response as _format_text_file_create_response,
    is_docx_create_intent as _is_docx_create_intent,
    is_docx_edit_intent as _is_docx_edit_intent,
    is_text_file_edit_followup_intent as _is_text_file_edit_followup_intent,
    needs_implementation_choice as _needs_implementation_choice,
    run_direct_document_read as _run_direct_document_read,
    run_direct_docx_create as _run_direct_docx_create,
    run_direct_docx_edit as _run_direct_docx_edit,
    run_direct_text_file_create as _run_direct_text_file_create,
    run_direct_text_file_edit as _run_direct_text_file_edit,
)
from services.generation_runtime import (
    COMFY_MANUAL_START_STATUS,
    COMFY_QUEUED_STATUS,
    COMFY_STARTING_STATUS,
    generation_queue_state,
    is_generation_action,
    is_generation_tool,
)

router = APIRouter()

MAX_TOOL_CALL_ROUNDS = 6
THREE_D_TOOL_NAMES = {
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_fusion",
    "generate_3d_from_generated_multiview",
    "modify_previous_3d",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOCUMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".rs",
    ".toml",
    ".ini",
    ".log",
    ".pdf",
    ".docx",
}

FOLDER_SUMMARY_EXTENSIONS = DOCUMENT_EXTENSIONS
GENERATED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".rs",
    ".toml",
    ".ini",
    ".log",
}

COMMAND_CONFIRM_PATTERN = re.compile(
    r"(?:确认执行命令|confirm\s+(?:running|execute|run)\s+command)\s*[:：]\s*`([^`]+)`"
    r"(?:\s*[，,]\s*(?:工作目录|cwd|working\s+directory)\s*[:：]\s*`([^`]+)`)?",
    re.IGNORECASE,
)

PROJECT_CHECK_CONFIRM_PATTERN = re.compile(
    r"(?:确认项目检查|confirm\s+project\s+check)\s*[:：]\s*`([^`]+)`"
    r"(?:\s*[，,]\s*(?:类型|type|check_type)\s*[:：]\s*`?([^`\s，,]+)`?)?",
    re.IGNORECASE,
)

DELETE_CONFIRM_PATTERN = re.compile(
    r"(?:确认删除|confirm\s+deletion\s+of)\s*`([^`]+)`",
    re.IGNORECASE,
)

DELETE_CONTINUATION_PATTERN = re.compile(
    r"(?:继续任务|后续任务|continue\s+task|then)\s*[:：]\s*([\s\S]+)",
    re.IGNORECASE,
)

TEXTUAL_TOOL_INVOKE_PATTERN = re.compile(
    r"<\s*\|\s*\|\s*DSML\s*\|\s*\|\s*invoke\s+name=\"([^\"]+)\"\s*>",
    re.IGNORECASE,
)

TEXTUAL_TOOL_PARAM_PATTERN = re.compile(
    r"<\s*\|\s*\|\s*DSML\s*\|\s*\|\s*parameter\s+name=\"([^\"]+)\"[^>]*>([\s\S]*?)</\s*\|\s*\|\s*DSML\s*\|\s*\|\s*parameter>",
    re.IGNORECASE,
)

TEXTUAL_TOOL_MARKER = "<| | DSML | |"
TEXTUAL_TOOL_MARKER_PATTERN = re.compile(
    r"<\s*/?\s*\|\s*\|\s*DSML\s*\|\s*\|",
    re.IGNORECASE,
)
TEXTUAL_TOOL_CALLS_END_PATTERN = re.compile(
    r"</\s*\|\s*\|\s*DSML\s*\|\s*\|\s*tool_calls\s*>",
    re.IGNORECASE,
)

SUPPORTED_TEXTUAL_TOOL_NAMES = {
    "edit_text_file",
    "web_search",
    "web_fetch",
    "read_document",
    "read_many_files",
    "list_directory",
    "search_files",
    "write_many_files",
}

DOCX_PATH_PATTERN = re.compile(
    r"`([^`]+\.docx)`|([A-Za-z]:[\\/][^\s`\"'，。；;]+\.docx)",
    re.IGNORECASE,
)

TEXT_FILE_PATH_PATTERN = re.compile(
    r"`([^`]+\.(?:html?|css|jsx?|tsx?|py|txt|md|markdown|csv|json|jsonl|ya?ml|xml|rs|toml|ini|log))`"
    r"|([A-Za-z]:[\\/][^\s`\"'，。；;]+\.(?:html?|css|jsx?|tsx?|py|txt|md|markdown|csv|json|jsonl|ya?ml|xml|rs|toml|ini|log))",
    re.IGNORECASE,
)

LOCAL_PATH_PATTERN = re.compile(
    r"([A-Za-z]:[\\/][^\s`\"'，。；;]+|(?:Desktop|desktop|桌面)[\\/][^\s`\"'，。；;]+)"
)

ASSET_IMAGE_PATTERNS = [
    re.compile(r'活跃生成图片路径="([^"]+)"'),
    re.compile(r'活跃图像路径="([^"]+)"'),
    re.compile(r'预览图:\s*`([^`]+)`'),
    re.compile(r'生成图片\s*:\s*`([^`]+)`'),
    re.compile(r'编辑后图片\s*:\s*`([^`]+)`'),
    re.compile(r'image_2d["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
]

MULTIVIEW_CONTEXT_PATTERNS = {
    "front": [
        re.compile(r'活跃三视图正面="([^"]+)"'),
        re.compile(r'正面:\s*`([^`]+)`'),
        re.compile(r'front_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
    "left": [
        re.compile(r'活跃三视图左侧="([^"]+)"'),
        re.compile(r'左侧:\s*`([^`]+)`'),
        re.compile(r'left_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
    "back": [
        re.compile(r'活跃三视图背面="([^"]+)"'),
        re.compile(r'背面:\s*`([^`]+)`'),
        re.compile(r'back_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
}


def _is_memory_intent(content: str) -> bool:
    text = (content or "").lower()
    if any(word in text for word in ["删除", "删了", "删掉", "移除", "理解错", "误解"]):
        return False
    return any(word in text for word in ["记住", "记一下", "remember", "别忘", "偏好"])


def _is_document_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in DOCUMENT_EXTENSIONS


def _document_attachments(paths: list[str] | None) -> list[str]:
    return [path for path in paths or [] if _is_document_path(path)]


def _image_attachments(paths: list[str] | None) -> list[str]:
    return [
        path
        for path in paths or []
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]


def _candidate_local_paths(content: str) -> list[str]:
    text = content or ""
    candidates: list[str] = []
    for pattern in [
        r"`([^`]+)`",
        r'"([^"]+)"',
        r"'([^']+)'",
        r"“([^”]+)”",
    ]:
        candidates.extend(match.strip() for match in re.findall(pattern, text) if match.strip())
    candidates.extend(match.group(1).strip() for match in LOCAL_PATH_PATTERN.finditer(text))

    seen = set()
    unique = []
    for item in candidates:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _resolve_local_path(path_text: str) -> Path:
    path = path_text.strip().strip("`\"'")
    lowered = path.lower().replace("\\", "/")
    if lowered == "desktop" or lowered == "桌面":
        return Path.home() / "Desktop"
    if lowered.startswith("desktop/") or lowered.startswith("桌面/"):
        _, rest = path.replace("\\", "/", 1).split("/", 1)
        return Path.home() / "Desktop" / rest
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


async def _project_path_for_request(req: ChatRequest) -> str | None:
    if req.project_path:
        root = Path(os.path.expandvars(os.path.expanduser(req.project_path))).resolve()
        if root.exists() and root.is_dir():
            return str(root)

    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT p.root_path
        FROM conversations c
        JOIN projects p ON p.id = c.project_id
        WHERE c.id = ?
        LIMIT 1
        """,
        (req.conversation_id,),
    )
    if not rows:
        return None
    root = Path(rows[0][0])
    return str(root) if root.exists() and root.is_dir() else None


def _with_project_context(content: str, project_path: str | None) -> str:
    if not project_path:
        return content
    return (
        f"{content}\n\n"
        "[当前项目文件夹]\n"
        f"{project_path}\n\n"
        "项目规则：如果用户没有给出其他明确路径，读取、列出、创建、修改、整理文件时都默认在这个项目文件夹内完成。"
        "不要主动访问项目文件夹之外的内容；如果用户要求打开文件夹，就打开这个项目文件夹或其子路径。"
    )


def _find_desktop_directory_by_mention(content: str) -> Path | None:
    text = content or ""
    lowered = text.lower()
    if "桌面" not in text and "desktop" not in lowered:
        return None

    desktop = Path.home() / "Desktop"
    if not desktop.exists() or not desktop.is_dir():
        return None

    matches: list[Path] = []
    compact_text = re.sub(r"\s+", "", lowered)
    try:
        children = list(desktop.iterdir())
    except OSError:
        return None

    for child in children:
        if not child.is_dir():
            continue
        name = child.name.lower()
        compact_name = re.sub(r"\s+", "", name)
        if name in lowered or compact_name in compact_text:
            matches.append(child)

    if not matches:
        return None
    return sorted(matches, key=lambda path: len(path.name), reverse=True)[0]


def _nearby_path_suggestions(content: str, limit: int = 5) -> list[dict]:
    text = content or ""
    lowered = text.lower()
    roots = []
    if "桌面" in text or "desktop" in lowered:
        roots.append(Path.home() / "Desktop")
    roots.append(Path.cwd())

    seen_roots = set()
    items: list[tuple[float, Path]] = []
    compact_text = re.sub(r"\s+", "", lowered)
    for root in roots:
        try:
            root = root.resolve()
        except OSError:
            continue
        if str(root).lower() in seen_roots or not root.exists() or not root.is_dir():
            continue
        seen_roots.add(str(root).lower())
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name.lower()
            compact_name = re.sub(r"\s+", "", name)
            score = SequenceMatcher(None, compact_name, compact_text).ratio()
            if name in lowered or compact_name in compact_text:
                score += 1.0
            if child.is_dir():
                score += 0.08
            if score >= 0.18:
                items.append((score, child))

    items.sort(key=lambda item: item[0], reverse=True)
    suggestions = []
    seen_paths = set()
    for _, path in items:
        key = str(path).lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        suggestions.append({
            "name": path.name,
            "path": str(path),
            "type": "文件夹" if path.is_dir() else "文件",
        })
        if len(suggestions) >= limit:
            break
    return suggestions


def _extract_directory_path(content: str) -> Path | None:
    for candidate in _candidate_local_paths(content):
        try:
            path = _resolve_local_path(candidate)
        except OSError:
            continue
        if path.exists() and path.is_dir():
            return path
    fuzzy_desktop = _find_desktop_directory_by_mention(content)
    if fuzzy_desktop:
        return fuzzy_desktop
    return None


def _format_path_resolution_card(query: str, suggestions: list[dict]) -> str:
    lines = [
        "[PATH_RESOLUTION_REQUIRED]",
        f"查询: {query}",
        "候选:",
    ]
    for item in suggestions:
        lines.append(f"- {item.get('type', '路径')}: `{item.get('path')}`")
    lines.append("[/PATH_RESOLUTION_REQUIRED]")
    return "\n".join(lines)


def _is_folder_summary_to_docx_intent(content: str) -> bool:
    text = (content or "").lower()
    has_folder_word = any(word in text for word in ["文件夹", "目录", "folder", "directory"])
    has_summary_word = any(word in text for word in ["阅读", "读取", "整理", "总结", "重点", "提取", "汇总", "归纳"])
    has_output_word = any(word in text for word in ["新文档", "docx", "word", "写入", "生成文档", "输出文档", "报告"])
    return has_folder_word and has_summary_word and has_output_word


def _folder_documents(folder: Path, recursive: bool = False, limit: int = 12) -> list[Path]:
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    docs = []
    for item in iterator:
        if len(docs) >= limit:
            break
        if not item.is_file():
            continue
        if item.suffix.lower() in FOLDER_SUMMARY_EXTENSIONS:
            docs.append(item)
    return docs


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


def _format_folder_summary_response(result: dict) -> str:
    if result.get("needs_path"):
        return result.get("message") or _format_path_resolution_card("", [])
    if result.get("ok"):
        return (
            f"已阅读文件夹中的 {result.get('document_count', 0)} 个文档，并生成整理文档：`{result.get('path')}`"
        )
    return f"整理文件夹文档失败：{result.get('error', '未知错误')}"


def _is_open_folder_intent(content: str) -> bool:
    text = (content or "").lower()
    return any(word in text for word in ["打开", "显示", "定位", "open", "reveal"]) and any(
        word in text for word in ["文件夹", "目录", "folder", "directory", "项目"]
    )


def _run_open_folder_request(req: ChatRequest) -> dict | None:
    if not _is_open_folder_intent(req.content):
        return None
    target = _extract_directory_path(req.content)
    if not target and req.project_path:
        target = Path(req.project_path)
    if not target or not target.exists() or not target.is_dir():
        return {"ok": False, "error": "没有找到可打开的文件夹路径"}
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            return {"ok": False, "error": "当前只支持在 Windows 上直接打开文件夹", "path": str(target)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(target)}
    return {"ok": True, "path": str(target)}


def _is_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    text = (content or "").lower()
    blocked_words = [
        "\u8bed\u8a00\u6a21\u578b",
        "\u5927\u6a21\u578b",
        "\u6a21\u578b\u914d\u7f6e",
        "model config",
        "llm",
    ]
    if any(word in text for word in blocked_words):
        return False

    intent_words = [
        "3d",
        "\u4e09\u7ef4",
        "\u6a21\u578b",
        "\u5efa\u6a21",
        "\u8f6c3d",
        "\u8f6c 3d",
        "\u751f\u6210\u6a21\u578b",
    ]
    action_words = [
        "\u751f\u6210",
        "\u505a",
        "\u7ed9\u6211",
        "\u6765\u4e00\u4e2a",
        "\u8981",
        "\u60f3\u8981",
        "\u521b\u5efa",
        "\u5236\u4f5c",
        "\u8f6c",
        "\u5efa",
        "\u753b",
        "\u8bbe\u8ba1",
        "\u5e0c\u671b",
        "\u5168\u65b0",
        "\u65b0\u7684",
        "\u53e6\u4e00\u4e2a",
        "\u53e6\u5916\u4e00\u4e2a",
        "\u91cd\u65b0\u6765",
        "\u91cd\u65b0\u505a",
        "\u4ece\u96f6",
        "\u6587\u751f",
    ]

    if image_paths:
        if not any(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in image_paths):
            return False
        return any(word in text for word in intent_words)
    return any(word in text for word in intent_words) and any(
        word in text for word in action_words
    )


def _is_image_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    return bool(image_paths) and _is_3d_intent(content, image_paths)


def _is_text_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    return not image_paths and _is_3d_intent(content, image_paths)


def _is_image_generation_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if image_paths:
        return False
    text = (content or "").lower()
    if any(word in text for word in ["3d", "3D", "三维", "模型", "建模", "glb", "obj"]):
        return False
    draw_words = [
        "画",
        "绘制",
        "绘图",
        "生图",
        "生成图片",
        "生成一张图",
        "生成图",
        "图片生成",
        "出图",
        "做一张图",
        "做张图",
        "来一张",
        "来张",
        "给我一张",
        "给我张",
        "我要一张",
        "我想要一张",
        "想要一张",
        "要一张",
        "要张",
        "帮我画",
        "画一张",
    ]
    subject_words = [
        "图",
        "图片",
        "插画",
        "海报",
        "头像",
        "概念图",
        "卡通",
        "角色",
        "狗",
        "猫",
        "产品",
        "场景",
    ]
    if "图片" in text and any(word in text for word in ["想要", "我要", "给我", "来", "做", "生成"]):
        return True
    return any(word in text for word in draw_words) and any(word in text for word in subject_words)


def _is_image_edit_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if not image_paths:
        return False
    if not any(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in image_paths):
        return False
    text = (content or "").lower()
    if _is_3d_intent(content, image_paths):
        return False
    edit_words = [
        "改图",
        "编辑图片",
        "修改图片",
        "把图片",
        "这张图",
        "这张图片",
        "改成",
        "换成",
        "润色",
        "增强",
        "优化",
        "完整呈现",
        "呈现完整",
        "画完整",
        "补全",
        "扩图",
        "补全图片",
        "画面完整",
    ]
    return any(word in text for word in edit_words)


def _is_previous_image_edit_intent(content: str) -> bool:
    text = (content or "").lower()
    blocked_words = ["全新", "新的图片", "重新画一张", "不要基于", "不基于", "从零"]
    if any(word in text for word in blocked_words):
        return False
    previous_words = ["上一张", "上张", "刚才", "刚刚", "这张", "这个", "它", "他", "图片", "图中"]
    edit_words = [
        "完整呈现",
        "呈现完整",
        "画完整",
        "补全",
        "扩图",
        "补全图片",
        "画面完整",
        "改图",
        "编辑图片",
        "修改图片",
        "润色",
        "增强",
        "优化",
        "改成",
        "换成",
    ]
    return any(word in text for word in previous_words) and any(word in text for word in edit_words)


def _quality_mode_from_decision(decision: dict | None) -> str:
    mode = str((decision or {}).get("quality_mode") or "").strip().lower()
    return "quality" if mode == "quality" else "fast"


async def _inject_request_image_context(conversation_id: str, image_paths: list[str] | None):
    paths = [
        os.path.normpath(path)
        for path in image_paths or []
        if path and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]
    if not paths:
        return
    await memory_stm.inject_system_context(
        conversation_id,
        "\n".join(f'[System Context: 活跃图像路径="{path}"]' for path in paths[:4]),
    )


def _format_image_response(tool_name: str, result: dict) -> str:
    status = result.get("status")
    if tool_name == "generate_multiview_images_from_image":
        front = result.get("front_path") or result.get("frontPath")
        left = result.get("left_path") or result.get("leftPath")
        back = result.get("back_path") or result.get("backPath")
        if status == "success" and front and left and back:
            return "\n".join([
                "三视图已生成。",
                "",
                f"正面: `{front}`",
                f"左侧: `{left}`",
                f"背面: `{back}`",
                "",
                "可以继续要求我用这三张已知视角图片生成 3D 模型。",
            ])
        message = result.get("message") or "没有返回完整三视图"
        return f"三视图生成失败。\n\n原因: {message}"

    image_path = (
        result.get("image_path")
        or result.get("imagePath")
        or result.get("improved_image_path")
        or result.get("modelPath")
    )
    if status == "success" and image_path:
        label = "编辑后图片" if tool_name == "edit_image" else "生成图片"
        lines = [f"{label}已完成。", "", f"{label}: `{image_path}`"]
        source_prompt = result.get("source_prompt")
        if source_prompt:
            lines.extend(["", f"使用提示词: `{source_prompt}`"])
        return "\n".join(lines)
    message = result.get("message") or "没有返回图片文件"
    return f"图片任务失败。\n\n原因: {message}"


async def _inject_image_context(conversation_id: str, result: dict):
    if result.get("status") != "success":
        return
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if front and left and back:
        await memory_stm.inject_system_context(
            conversation_id,
            "\n".join([
                f"[System Context: 活跃三视图正面=\"{front}\"]",
                f"[System Context: 活跃三视图左侧=\"{left}\"]",
                f"[System Context: 活跃三视图背面=\"{back}\"]",
            ]),
        )
        return
    image_path = result.get("image_path") or result.get("imagePath") or result.get("improved_image_path")
    if image_path:
        await memory_stm.inject_system_context(
            conversation_id,
            f"[System Context: 活跃图像路径=\"{image_path}\"]",
        )


async def _run_direct_image_request(
    content: str,
    image_paths: list[str] | None,
    conversation_id: str | None = None,
    project_path: str | None = None,
) -> dict | None:
    if _is_image_edit_intent(content, image_paths):
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
    if conversation_id and _is_previous_image_edit_intent(content):
        source = await _find_latest_edit_source_image(conversation_id)
        if not source:
            project_images = _project_image_paths(project_path, content, limit=1)
            source = os.path.normpath(project_images[0]) if project_images else None
        if source:
            result = await asyncio.to_thread(memory_mgr.handle_modify_image, source, content.strip())
            return {"tool": "edit_image", "result": result}
    if _is_image_generation_intent(content, image_paths):
        result = await asyncio.to_thread(memory_mgr.handle_generate_image, content.strip(), "fast")
        return {"tool": "generate_image", "result": result}
    return None


def _is_attachment_asset_intent(content: str, image_paths: list[str] | None) -> str | None:
    docs = _document_attachments(image_paths)
    if not docs:
        return None
    text = (content or "").lower()
    if _is_delete_request_text(text) or _is_docx_create_intent(text) or _is_docx_edit_intent(text):
        return None
    if _is_3d_intent(content, None):
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


def _is_project_document_asset_intent(content: str, project_path: str | None) -> str | None:
    if not project_path:
        return None
    text = (content or "").lower()
    if not any(word in text for word in ["文档", "文本", "txt", "pdf", "docx", "要求", "document"]):
        return None
    if _is_3d_intent(content, None):
        return "3d"
    if _is_image_generation_intent(content, None):
        return "image"
    return None


def _project_document_paths(project_path: str, content: str) -> list[str]:
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        iterator = root.rglob("*")
        scanned = 0
        for path in iterator:
            scanned += 1
            if scanned > 1200:
                break
            if len(candidates) > 80:
                break
            if not path.is_file() or path.suffix.lower() not in DOCUMENT_EXTENSIONS:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if "文本文档" in text and path.suffix.lower() == ".txt":
                score += 0.9
            if "新建" in text and "新建" in stem:
                score += 0.7
            if "要求" in text:
                score += 0.15
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return []
    if candidates[0][0] < 0.18 and len(candidates) > 1:
        return []
    if candidates[0][0] >= 1.0:
        return [str(candidates[0][1])]
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] >= 0.35:
        return [str(candidates[0][1])]
    return [str(path) for _, path in candidates[:3]]


def _project_image_paths(project_path: str | None, content: str, limit: int = 5) -> list[str]:
    if not project_path:
        return []
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        scanned = 0
        for path in root.rglob("*"):
            scanned += 1
            if scanned > 1200:
                break
            if len(candidates) > 80:
                break
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = 0.2
            score += SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if any(word in text for word in ["文件夹", "项目", "目录", "folder"]):
                score += 0.25
            if any(word in text for word in ["图片", "图像", "照片", "png", "jpg", "jpeg", "image"]):
                score += 0.25
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    return [str(path) for _, path in candidates[:limit]]


def _project_file_candidates(project_path: str | None, content: str, limit: int = 20) -> list[dict]:
    if not project_path:
        return []
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    allowed = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS
    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        scanned = 0
        for path in root.rglob("*"):
            scanned += 1
            if scanned > 1600:
                break
            if len(candidates) > 200:
                break
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if path.suffix.lower() in IMAGE_EXTENSIONS and any(word in text for word in ["图片", "图像", "照片", "image"]):
                score += 0.5
            if path.suffix.lower() in DOCUMENT_EXTENSIONS and any(word in text for word in ["文档", "文本", "docx", "pdf", "txt", "要求"]):
                score += 0.5
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    result = []
    for _, path in candidates[:limit]:
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            kind = "image"
        elif suffix in {".pdf", ".docx", ".txt", ".md", ".markdown"}:
            kind = "document"
        else:
            kind = "file"
        result.append({
            "name": path.name,
            "path": str(path),
            "kind": kind,
            "extension": suffix,
        })
    return result


def _read_document_attachments(paths: list[str], max_chars: int = 16000) -> list[str]:
    sections: list[str] = []
    for path in paths[:4]:
        result = memory_mgr.handle_read_document(path, max_chars)
        if not result.get("ok"):
            sections.append(f"[{path}]\n读取失败: {result.get('error', 'unknown error')}")
            continue
        sections.append(f"[{result.get('name') or path}]\n{result.get('content', '')}")
    return sections


async def _build_asset_prompt_from_documents(
    user_request: str,
    document_sections: list[str],
    client,
    model_name: str,
    target: str,
) -> str:
    raw_context = "\n\n---\n\n".join(document_sections).strip()
    fallback = f"{user_request}\n\n{raw_context}".strip()
    system_hint = (
        "你是一个本地工具调度器的提示词生成器。"
        "根据用户要求和附件文档，输出可以直接交给生成工具的简洁中文提示词。"
        "只输出提示词本身，不要解释，不要给方案，不要问用户。"
        "如果文档里有主体、风格、颜色、材质、尺寸、用途等要求，全部合并进去。"
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
                {
                    "role": "user",
                    "content": f"用户要求：{user_request}\n\n附件文档：\n{raw_context}",
                },
            ],
        )
        prompt = (response.choices[0].message.content or "").strip()
        return prompt or fallback
    except Exception:
        return fallback


def _document_requirement_text(document_sections: list[str]) -> str:
    chunks: list[str] = []
    for section in document_sections:
        _, _, body = section.partition("\n")
        chunks.append(body or section)
    text = "\n".join(chunks)
    text = re.sub(r"(?i)\b(requirements?|prompt)\s*[:：]", "", text)
    text = re.sub(r"要求\s*[:：]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \n\r\t,，。；;")
    return text


def _contains_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _deterministic_asset_prompt(requirement_text: str, target: str) -> str:
    text = requirement_text.strip()
    color = ""
    if _contains_any(text, ["白色", "white"]):
        color = "white"
    elif _contains_any(text, ["黑色", "black"]):
        color = "black"
    elif _contains_any(text, ["棕色", "brown"]):
        color = "brown"

    cute = _contains_any(text, ["可爱", "cute", "adorable"])
    subject = ""
    if _contains_any(text, ["狗", "小狗", "犬", "dog", "puppy"]):
        subject = "puppy dog" if cute else "dog"
    elif _contains_any(text, ["猫", "小猫", "cat", "kitten"]):
        subject = "kitten cat" if cute else "cat"
    elif _contains_any(text, ["兔", "rabbit", "bunny"]):
        subject = "bunny rabbit" if cute else "rabbit"

    if subject:
        parts = ["a single"]
        if cute:
            parts.append("cute adorable")
        if color:
            parts.append(color)
        parts.append(subject)
        core = " ".join(parts)
    else:
        core = text

    if target == "3d":
        return (
            f"{core}, stylized 3D asset, full body, clear silhouette, clean topology-friendly shape, "
            "simple neutral background, no humans, no text, no watermark"
        )
    return (
        f"{core}, full body, centered composition, soft fluffy fur, clean simple background, "
        "high quality cute illustration, no humans, no people, no portrait, no text, no watermark"
    )


async def _build_asset_prompt_from_documents(
    user_request: str,
    document_sections: list[str],
    client,
    model_name: str,
    target: str,
) -> str:
    raw_context = "\n\n---\n\n".join(document_sections).strip()
    requirement_text = _document_requirement_text(document_sections)
    fallback = _deterministic_asset_prompt(requirement_text or raw_context or user_request, target)
    if requirement_text and len(requirement_text) <= 120:
        return fallback

    system_hint = (
        "你是本地生成工具的提示词生成器。根据用户要求和附件文档，输出可直接给生成工具的提示词。"
        "只输出提示词本身，不要解释，不要给方案，不要问用户。"
        "必须忠实保留文档里的主体、颜色、风格、材质、尺寸、用途等要求。"
        "除非文档明确要求人物，否则不要生成人、人像、男人、女人或肖像。"
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
        if not _contains_any(requirement_text, ["人", "人物", "男人", "女人", "肖像", "human", "person", "man", "woman", "portrait"]):
            if _contains_any(prompt, ["人", "人物", "男人", "女人", "肖像", "human", "person", "man", "woman", "portrait"]):
                return fallback
        return prompt or fallback
    except Exception:
        return fallback


async def _run_attachment_asset_request(req: ChatRequest, client, model_name: str) -> dict | None:
    target = _is_attachment_asset_intent(req.content, req.image_paths)
    if not target:
        return None

    docs = _document_attachments(req.image_paths)
    sections = _read_document_attachments(docs)
    if not sections:
        return None

    prompt = await _build_asset_prompt_from_documents(
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


async def _run_project_document_asset_request(req: ChatRequest, client, model_name: str) -> dict | None:
    target = _is_project_document_asset_intent(req.content, req.project_path)
    if not target or not req.project_path:
        return None

    docs = _project_document_paths(req.project_path, req.content)
    if not docs:
        return {
            "tool": "generate_image" if target == "image" else "generate_3d_from_text",
            "result": {
                "status": "error",
                "message": f"没有在项目文件夹中找到匹配的文档: {req.project_path}",
            },
        }

    sections = _read_document_attachments(docs)
    if not sections:
        return None

    prompt = await _build_asset_prompt_from_documents(
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


def _format_attachment_asset_start(tool_name: str) -> str:
    if tool_name == "generate_3d_from_text":
        return "我已读取附件要求，正在按文档内容生成 3D 模型。\n\n"
    return "我已读取附件要求，正在按文档内容生成图片。\n\n"


def _first_3d_result(tool_results: list[dict]) -> dict | None:
    for item in tool_results:
        if item.get("tool") in THREE_D_TOOL_NAMES:
            return item
    return None


def _first_tool_result(tool_results: list[dict], tool_name: str) -> dict | None:
    for item in tool_results:
        if item.get("tool") == tool_name:
            return item
    return None


def _requires_manual_comfy_start(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    payload = result.get("result") if "result" in result else result
    return isinstance(payload, dict) and bool(payload.get("manual_start_required"))


def _any_requires_manual_comfy_start(items: list[dict]) -> bool:
    return any(_requires_manual_comfy_start(item) for item in items)


def _best_tool_result(tool_results: list[dict], tool_name: str) -> dict | None:
    matches = [item for item in tool_results if item.get("tool") == tool_name]
    if not matches:
        return None
    for item in reversed(matches):
        result = item.get("result")
        if isinstance(result, dict) and result.get("ok"):
            return item
    return matches[-1]


def _format_delete_tool_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    if result.get("ok") and result.get("message"):
        return result["message"]
    return f"删除失败：{result.get('error') or result.get('message') or '未知错误'}"


def _format_delete_then_create_response(delete_result: dict, create_result: dict | None) -> str:
    if not create_result:
        return _format_delete_tool_response(delete_result)
    create_text = _format_text_file_create_response(create_result)
    if delete_result.get("ok"):
        return f"{create_text}\n\n旧文件已删除。"
    return f"{create_text}\n\n旧文件删除失败：{delete_result.get('error') or delete_result.get('message') or '未知错误'}"


def _format_command_tool_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    command = result.get("command") or ""
    cwd = result.get("cwd") or result.get("path") or ""
    if result.get("timeout"):
        return f"命令执行超时：`{command}`\n\n工作目录：`{cwd}`\n\n{result.get('stderr') or result.get('stdout') or result.get('error') or ''}".strip()
    status = "成功" if result.get("ok") else "失败"
    lines = [f"命令执行{status}：`{command}`"]
    if cwd:
        lines.append(f"工作目录：`{cwd}`")
    if "returncode" in result:
        lines.append(f"退出码：{result.get('returncode')}")
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    if stdout:
        lines.extend(["", "stdout:", "```text", stdout[-4000:], "```"])
    if stderr:
        lines.extend(["", "stderr:", "```text", stderr[-4000:], "```"])
    if not stdout and not stderr and result.get("error"):
        lines.extend(["", str(result.get("error"))])
    return "\n".join(lines)


def _format_text_edit_response(result: dict) -> str:
    path = result.get("path") or ""
    if result.get("ok"):
        if result.get("changed") is False:
            return f"文件无需修改：`{path}`"
        lines = [f"已修改文件：`{path}`"]
        if result.get("action"):
            lines.append(f"操作：{result.get('action')}")
        if result.get("replacements") is not None:
            lines.append(f"替换次数：{result.get('replacements')}")
        if result.get("backup_path"):
            lines.append(f"备份：`{result.get('backup_path')}`")
        return "\n".join(lines)
    return f"修改文件失败：{result.get('error') or result.get('message') or '未知错误'}"


def _format_write_many_files_response(result: dict) -> str:
    files = result.get("files") if isinstance(result, dict) else []
    errors = result.get("errors") if isinstance(result, dict) else []
    lines = []
    if result.get("ok"):
        lines.append(f"已写入 {result.get('written_count', len(files or []))} 个文件：")
    elif files:
        lines.append(f"部分文件已写入，另有 {result.get('error_count', len(errors or []))} 个错误：")
    else:
        return f"写入文件失败：{result.get('error') or '未知错误'}"
    for item in files or []:
        path = item.get("path") if isinstance(item, dict) else ""
        if path:
            lines.append(f"- `{path}`")
    for item in (errors or [])[:5]:
        if isinstance(item, dict):
            lines.append(f"- 错误：{item.get('path', '')} {item.get('error', '')}".strip())
    return "\n".join(lines)


def _extract_textual_tool_calls(content: str) -> list[tuple[str, dict]]:
    text = (content or "").strip()
    marker_match = TEXTUAL_TOOL_MARKER_PATTERN.search(text)
    if not marker_match:
        return []
    prefix = text[: marker_match.start()].strip()
    if "```" in text or len(prefix) > 160:
        return []

    invokes = list(TEXTUAL_TOOL_INVOKE_PATTERN.finditer(content or ""))
    calls: list[tuple[str, dict]] = []
    for index, invoke in enumerate(invokes):
        tool_name = invoke.group(1).strip()
        block_end = invokes[index + 1].start() if index + 1 < len(invokes) else len(content or "")
        block = (content or "")[invoke.start():block_end]
        args = {
            match.group(1).strip(): match.group(2).strip()
            for match in TEXTUAL_TOOL_PARAM_PATTERN.finditer(block)
        }
        calls.append((tool_name, args))

    if not calls:
        return []
    if any(tool_name in SUPPORTED_TEXTUAL_TOOL_NAMES for tool_name, _ in calls):
        return calls
    if prefix and not any(word in prefix for word in ["替换", "修改", "修复", "执行", "现在", "调用", "搜索", "读取", "获取"]):
        return []
    return calls


def _extract_textual_tool_call(content: str) -> tuple[str, dict] | None:
    calls = _extract_textual_tool_calls(content)
    return calls[0] if calls else None


def _parse_textual_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def _parse_textual_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _parse_textual_optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def _parse_textual_json(value: object, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _run_textual_tool_calls(content: str) -> list[dict]:
    results = []
    for tool_name, args in _extract_textual_tool_calls(content):
        if tool_name not in SUPPORTED_TEXTUAL_TOOL_NAMES:
            continue
        if tool_name == "edit_text_file":
            if not args.get("file_path") or not args.get("action"):
                continue
            result = memory_mgr.handle_edit_text_file(
                args.get("file_path", ""),
                args.get("action", "replace"),
                args.get("text", ""),
                args.get("find", ""),
                args.get("replace", ""),
                _parse_textual_bool(args.get("use_regex")),
                _parse_textual_bool(args.get("backup")),
            )
        elif tool_name == "web_search":
            result = memory_mgr.handle_web_search(
                args.get("query", ""),
                _parse_textual_int(args.get("max_results"), 5),
                _parse_textual_optional_int(args.get("recency_days")),
                _parse_textual_json(args.get("domains"), []),
            )
        elif tool_name == "web_fetch":
            result = memory_mgr.handle_web_fetch(
                args.get("url", ""),
                _parse_textual_int(args.get("max_chars"), 12000),
            )
        elif tool_name == "read_document":
            result = memory_mgr.handle_read_document(
                args.get("file_path", ""),
                _parse_textual_int(args.get("max_chars"), 12000),
            )
        elif tool_name == "read_many_files":
            result = memory_mgr.handle_read_many_files(
                _parse_textual_json(args.get("file_paths"), []),
                _parse_textual_int(args.get("max_chars_per_file"), 8000),
                _parse_textual_int(args.get("max_files"), 12),
            )
        elif tool_name == "list_directory":
            result = memory_mgr.handle_list_directory(
                args.get("directory_path", ""),
                _parse_textual_bool(args.get("recursive")),
                _parse_textual_int(args.get("max_items"), 120),
            )
        elif tool_name == "search_files":
            result = memory_mgr.handle_search_files(
                args.get("directory_path", ""),
                args.get("query", ""),
                args.get("file_glob", "*"),
                _parse_textual_bool(args.get("recursive") or "true"),
                _parse_textual_bool(args.get("search_content") or "true"),
                _parse_textual_int(args.get("max_matches"), 80),
            )
        elif tool_name == "write_many_files":
            result = memory_mgr.handle_write_many_files(
                args.get("root_path", ""),
                _parse_textual_json(args.get("files"), []),
                _parse_textual_bool(args.get("overwrite")),
            )
        results.append({"tool": tool_name, "result": result})
    return results


def _run_textual_tool_call(content: str) -> tuple[str, dict] | None:
    for item in _run_textual_tool_calls(content):
        if item.get("tool") == "edit_text_file":
            return item["tool"], item["result"]
    return None


def _format_textual_tool_direct_response(tool_results: list[dict]) -> str:
    edit_result = _best_tool_result(tool_results, "edit_text_file")
    write_many_result = _best_tool_result(tool_results, "write_many_files")
    if edit_result:
        return _format_text_edit_response(edit_result["result"])
    if write_many_result:
        return _format_write_many_files_response(write_many_result["result"])
    lines = []
    for item in tool_results:
        tool = item.get("tool")
        result = item.get("result") or {}
        if tool == "web_fetch":
            title = result.get("title") or result.get("url") or "网页"
            lines.append(f"已读取网页：{title}")
        elif tool == "web_search":
            count = len(result.get("results") or [])
            lines.append(f"已完成网页搜索，返回 {count} 条结果。")
        elif tool == "read_document":
            lines.append(f"已读取文档：`{result.get('path') or ''}`")
        elif tool == "list_directory":
            lines.append(f"已读取目录：`{result.get('path') or ''}`")
        elif tool == "search_files":
            lines.append(f"已搜索文件：`{result.get('path') or ''}`")
    return "\n".join(line for line in lines if line).strip() or "工具调用已执行。"


async def _answer_from_textual_tool_results(client, model_name: str, messages: list, user_content: str, tool_results: list[dict]) -> str:
    direct_tools = {"edit_text_file", "write_many_files"}
    if any(item.get("tool") in direct_tools for item in tool_results):
        return _format_textual_tool_direct_response(tool_results)
    tool_payload = json.dumps(tool_results, ensure_ascii=False)[:30000]
    response = await client.chat.completions.create(
        model=model_name,
        messages=messages
        + [
            {
                "role": "system",
                "content": (
                    "上一条 assistant 内容包含文本化 DSML 工具调用，系统已代为执行。"
                    "请基于下面工具结果直接回答用户原始问题。不要输出 DSML、XML、JSON 或工具调用语法；"
                    "如果结果来自网页，请用中文总结并保留关键来源名称或链接。"
                    f"\n\n用户原始问题：{user_content}\n\n工具结果：{tool_payload}"
                ),
            }
        ],
    )
    return (response.choices[0].message.content or "").strip() or _format_textual_tool_direct_response(tool_results)


def _format_project_check_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    if not result.get("results"):
        return f"项目检查失败：{result.get('error', '未知错误')}"
    lines = [f"项目检查{'通过' if result.get('ok') else '失败'}：`{result.get('path')}`"]
    for item in result.get("results", []):
        lines.append("")
        lines.append(_format_command_tool_response(item))
    return "\n".join(lines)


def _extract_confirmed_command(content: str) -> tuple[str, str] | None:
    match = COMMAND_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    command = (match.group(1) or "").strip()
    cwd = (match.group(2) or "").strip()
    if not command:
        return None
    return command, cwd


def _run_confirmed_command_request(req: ChatRequest) -> dict | None:
    parsed = _extract_confirmed_command(req.content)
    if not parsed:
        return None
    command, cwd = parsed
    return memory_mgr.handle_run_command(
        command,
        cwd or req.project_path or "",
        "powershell",
        180,
        True,
        req.permission_mode,
    )


def _extract_confirmed_project_check(content: str) -> tuple[str, str] | None:
    match = PROJECT_CHECK_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    path = (match.group(1) or "").strip()
    check_type = (match.group(2) or "auto").strip() or "auto"
    if not path:
        return None
    return path, check_type


def _run_confirmed_project_check_request(req: ChatRequest) -> dict | None:
    parsed = _extract_confirmed_project_check(req.content)
    if not parsed:
        return None
    path, check_type = parsed
    return memory_mgr.handle_run_project_check(
        path,
        check_type,
        180,
        True,
        req.permission_mode,
    )


def _extract_delete_continuation(content: str) -> str:
    text = content or ""
    explicit = DELETE_CONTINUATION_PATTERN.search(text)
    if explicit:
        return explicit.group(1).strip()
    patterns = [
        r"(再写[\s\S]+)",
        r"(重新写[\s\S]+)",
        r"(重写[\s\S]+)",
        r"(然后写[\s\S]+)",
        r"(并写[\s\S]+)",
        r"(再创建[\s\S]+)",
        r"(重新创建[\s\S]+)",
        r"(然后创建[\s\S]+)",
        r"(并创建[\s\S]+)",
        r"(再做[\s\S]+)",
        r"(重新做[\s\S]+)",
        r"(然后做[\s\S]+)",
        r"(并做[\s\S]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_confirmed_delete(content: str) -> tuple[str, str] | None:
    match = DELETE_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    target = (match.group(1) or "").strip()
    if not target:
        return None
    return target, _extract_delete_continuation(content)


def _with_delete_continuation(message: str, continuation: str) -> str:
    continuation = (continuation or "").strip()
    if not continuation or "[CONFIRM_DELETE_REQUIRED]" not in (message or ""):
        return message
    return message.replace(
        "[/CONFIRM_DELETE_REQUIRED]",
        f"后续任务: `{continuation}`\n[/CONFIRM_DELETE_REQUIRED]",
    )


def _delete_then_create_prompt(target_path: str, continuation: str) -> str:
    target = Path(target_path)
    ext = target.suffix.lower()
    format_hint = ""
    if ext in {".html", ".htm"}:
        format_hint = "请重新创建同路径 HTML 文件，生成完整可直接打开运行的单文件 HTML，包含 CSS 和 JS。"
    elif ext == ".py":
        format_hint = "请重新创建同路径 Python 文件，生成完整可运行代码。"
    elif ext in {".css", ".js", ".ts", ".tsx", ".jsx"}:
        format_hint = f"请重新创建同路径 {ext} 代码文件。"
    else:
        format_hint = "请按被删除文件的类型重新创建同路径文本/代码文件。"
    return (
        f"删除已完成。现在执行后续任务：{continuation}\n\n"
        f"目标文件名：{target.name}\n目标文件夹：{target.parent}\n目标路径：{target_path}\n"
        f"{format_hint}\n不要创建 .bak 备份。"
    )


async def _run_confirmed_delete_request(
    req: ChatRequest,
    client,
    model_name: str,
) -> tuple[dict, dict | None] | None:
    parsed = _extract_confirmed_delete(req.content)
    if not parsed:
        return None
    target, continuation = parsed
    target_path = Path(target)
    recursive = target_path.exists() and target_path.is_dir()
    delete_result = memory_mgr.handle_delete_path(
        target,
        "auto",
        recursive,
        True,
        req.permission_mode,
    )
    create_result = None
    if delete_result.get("ok") and continuation:
        create_prompt = _delete_then_create_prompt(target, continuation)
        create_result = await _run_direct_text_file_create(
            req,
            client,
            model_name,
            force=True,
            prompt_override=create_prompt,
        )
    return delete_result, create_result


def _is_delete_request_text(content: str) -> bool:
    text = (content or "").lower()
    return any(word in text for word in ["删除", "删掉", "移除", "清理", "确认删除", "delete", "remove"])


def _format_3d_response(tool_name: str, result: dict) -> str:
    mode_label = {
        "generate_3d_from_text": "\u6587\u751f 3D",
        "generate_3d_from_image": "\u56fe\u7247\u8f6c 3D",
        "generate_3d_fusion": "\u53cc\u56fe\u878d\u5408 3D",
        "modify_previous_3d": "\u4fee\u6539\u540e 3D",
    }.get(tool_name, "3D \u751f\u6210")

    status = result.get("status")
    model_path = result.get("model_path") or result.get("modelPath")
    image_2d = result.get("image_2d") or result.get("image2D")
    image_normal = result.get("image_normal") or result.get("imageNormal")
    image_uv = result.get("image_uv") or result.get("imageUV")

    if status == "success" and model_path:
        lines = [f"{mode_label} 已完成。", "", f"3D 模型: `{model_path}`"]
        if image_2d:
            lines.append(f"预览图: `{image_2d}`")
        if image_normal:
            lines.append(f"法线图: `{image_normal}`")
        if image_uv:
            lines.append(f"UV 贴图: `{image_uv}`")
        source1 = result.get("image1_path") or result.get("image1Path")
        source2 = result.get("image2_path") or result.get("image2Path")
        if source1:
            lines.append(f"源图1: `{source1}`")
        if source2:
            lines.append(f"源图2: `{source2}`")
        front = result.get("front_path") or result.get("frontPath")
        left = result.get("left_path") or result.get("leftPath")
        back = result.get("back_path") or result.get("backPath")
        if front and left and back:
            lines.extend([f"正面: `{front}`", f"左侧: `{left}`", f"背面: `{back}`"])
        return "\n".join(lines)

    message = result.get("message") or "\u672a\u8fd4\u56de 3D \u6a21\u578b\u6587\u4ef6"
    lines = [f"{mode_label} \u5931\u8d25\u3002", "", f"\u539f\u56e0: {message}"]
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if front and left and back:
        lines.extend(["", "已完成的中间产物："])
        lines.extend([f"正面: `{front}`", f"左侧: `{left}`", f"背面: `{back}`"])
    if "mat1 and mat2 shapes cannot be multiplied" in message:
        lines.extend(
            [
                "",
                "\u8fd9\u4e2a\u9519\u8bef\u901a\u5e38\u8868\u793a\u5f53\u524d ComfyUI \u5de5\u4f5c\u6d41\u91cc\u7684 Flux2 \u6a21\u578b\u548c\u6587\u672c\u7f16\u7801\u5668\u7ef4\u5ea6\u4e0d\u5339\u914d\u3002\u8bf7\u68c0\u67e5\u5de5\u4f5c\u6d41\u4e2d UNet/GGUF \u6a21\u578b\u4e0e Qwen/CLIP \u6587\u672c\u7f16\u7801\u5668\u662f\u5426\u6765\u81ea\u540c\u4e00\u5957 Flux2 \u914d\u7f6e\u3002",
            ]
        )
    return "\n".join(lines)


def _is_modify_previous_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if image_paths:
        return False

    text = (content or "").lower()
    blocked_words = [
        "\u8bed\u8a00\u6a21\u578b",
        "\u5927\u6a21\u578b",
        "\u6a21\u578b\u914d\u7f6e",
        "model config",
        "llm",
    ]
    if any(word in text for word in blocked_words):
        return False

    new_request_words = [
        "\u5168\u65b0",
        "\u65b0\u7684",
        "\u65b0\u6a21\u578b",
        "\u53e6\u4e00\u4e2a",
        "\u53e6\u5916\u4e00\u4e2a",
        "\u91cd\u65b0\u6765",
        "\u91cd\u65b0\u505a",
        "\u91cd\u65b0\u751f\u6210\u4e00\u4e2a",
        "\u4e0d\u8981\u57fa\u4e8e",
        "\u4e0d\u57fa\u4e8e",
        "\u4e0d\u8981\u6cbf\u7528",
        "\u4e0d\u8981\u7528\u4e0a",
        "\u4ece\u96f6",
        "\u6587\u751f\u6a21\u578b",
        "\u6587\u751f 3d",
    ]
    if any(word in text for word in new_request_words):
        return False

    previous_words = [
        "\u4e0a\u4e00\u4e2a",
        "\u4e0a\u6b21",
        "\u4e4b\u524d",
        "\u521a\u624d",
        "\u521a\u521a",
        "\u8fd9\u4e2a",
        "\u8fd9\u53ea",
        "\u5b83",
        "\u5176",
    ]
    edit_words = [
        "\u4fee\u6539",
        "\u6539",
        "\u6539\u6210",
        "\u6362\u6210",
        "\u8c03\u6574",
        "\u4f18\u5316",
        "\u589e\u5f3a",
        "\u6da6\u8272",
        "\u53d8\u6210",
        "\u53d8",
        "\u91cd\u65b0\u751f\u6210",
    ]
    attribute_words = [
        "\u9ed1\u8272",
        "\u767d\u8272",
        "\u7ea2\u8272",
        "\u84dd\u8272",
        "\u7eff\u8272",
        "\u9ec4\u8272",
        "\u6a59\u8272",
        "\u7d2b\u8272",
        "\u7c89\u8272",
        "\u7070\u8272",
        "\u68d5\u8272",
        "\u91d1\u5c5e",
        "\u6728\u8d28",
        "\u73bb\u7483",
        "\u6bdb\u7ed2",
        "\u53ef\u7231",
        "\u5361\u901a",
        "\u98ce\u683c",
        "\u6750\u8d28",
        "\u989c\u8272",
        "black",
        "white",
        "red",
        "blue",
        "green",
        "yellow",
        "metal",
        "metallic",
        "wood",
        "glass",
    ]
    preference_words = [
        "\u5e0c\u671b",
        "\u60f3",
        "\u60f3\u8981",
        "\u662f",
        "\u6210\u4e3a",
        "\u770b\u8d77\u6765",
    ]

    has_previous_ref = any(word in text for word in previous_words)
    has_explicit_edit = any(word in text for word in edit_words)
    has_attribute_change = any(word in text for word in attribute_words) and any(
        word in text for word in preference_words
    )
    return has_previous_ref and (has_explicit_edit or has_attribute_change)


def _requests_multiview_followup(content: str) -> bool:
    text = (content or "").lower()
    return any(
        word in text
        for word in ["三视图", "三视角", "多视图", "多视角", "前左后", "正面、左侧、背面"]
    )


async def _find_latest_edit_source_image(conversation_id: str) -> str | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 40",
        (conversation_id,),
    )

    for (content,) in rows:
        if not content:
            continue
        for pattern in ASSET_IMAGE_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            path = os.path.normpath(match.group(1))
            if os.path.exists(path):
                return path
    return None


async def _find_latest_multiview_paths(conversation_id: str) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 60",
        (conversation_id,),
    )
    found = {"front": "", "left": "", "back": ""}
    for row in rows:
        content = row["content"] or ""
        for key, patterns in MULTIVIEW_CONTEXT_PATTERNS.items():
            if found[key]:
                continue
            for pattern in patterns:
                match = pattern.search(content)
                if not match:
                    continue
                path = os.path.normpath(match.group(1))
                if os.path.exists(path):
                    found[key] = path
                    break
        if all(found.values()):
            return found
    return None


async def _inject_3d_context(conversation_id: str, result: dict):
    parts = []
    image_path = (
        result.get("source_image_path")
        or result.get("sourceImagePath")
        or result.get("image_2d")
        or result.get("image2D")
    )
    model_path = result.get("model_path") or result.get("modelPath")
    source1 = result.get("image1_path") or result.get("image1Path")
    source2 = result.get("image2_path") or result.get("image2Path")
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if image_path:
        parts.append(f"[System Context: 活跃生成图片路径=\"{image_path}\"]")
    if model_path:
        parts.append(f"[System Context: 活跃模型路径=\"{model_path}\"]")
    if source1:
        parts.append(f"[System Context: 活跃融合源图1=\"{source1}\"]")
    if source2:
        parts.append(f"[System Context: 活跃融合源图2=\"{source2}\"]")
    if front and left and back:
        parts.append(f"[System Context: 活跃三视图正面=\"{front}\"]")
        parts.append(f"[System Context: 活跃三视图左侧=\"{left}\"]")
        parts.append(f"[System Context: 活跃三视图背面=\"{back}\"]")
    if parts:
        await memory_stm.inject_system_context(conversation_id, "\n".join(parts))


async def _run_direct_3d_request(content: str, image_paths: list[str] | None) -> dict | None:
    if not _is_3d_intent(content, image_paths):
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


async def _run_previous_3d_modification(
    conversation_id: str,
    content: str,
    image_paths: list[str] | None,
) -> dict | None:
    if not _is_modify_previous_3d_intent(content, image_paths):
        return None

    source_image = await _find_latest_edit_source_image(conversation_id)
    if not source_image:
        if _is_3d_intent(content, image_paths):
            return None
        return {
            "tool": "modify_previous_3d",
            "result": {
                "status": "error",
                "message": "\u6ca1\u627e\u5230\u4e0a\u4e00\u6b21\u751f\u6210\u7684 Flux \u6e90\u56fe\uff0c\u65e0\u6cd5\u57fa\u4e8e\u4e4b\u524d\u7684\u6a21\u578b\u4fee\u6539\u3002",
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


async def _get_provider_client(db, model_id: str | None = None):
    config_row = []
    if model_id:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs WHERE id = ? LIMIT 1",
            (model_id,),
        )
    if not config_row:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs WHERE is_default = 1 LIMIT 1"
        )
    if not config_row:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs ORDER BY created_at DESC LIMIT 1"
        )
    if not config_row:
        return None, None
    provider_config = config_row[0]
    client = AsyncOpenAI(
        api_key=provider_config[2] or "sk-placeholder",
        base_url=provider_config[3],
    )
    return client, provider_config


def _model_capabilities(provider_config, vision_override: bool | None = None) -> dict:
    provider = (provider_config[0] if provider_config else "") or ""
    model_name = (provider_config[1] if provider_config else "") or ""
    text = f"{provider} {model_name}".lower()
    vision_markers = [
        "vision",
        "vl",
        "qwen-vl",
        "qwen2-vl",
        "qwen2.5-vl",
        "qwen-omni",
        "gpt-4o",
        "gpt-4.1",
        "o3",
        "o4",
        "gemini",
        "claude-3",
        "claude-4",
        "glm-4v",
        "glm-4.5v",
        "kimi-vl",
    ]
    text_only_markers = ["qwen3", "qwen3.5", "deepseek", "llama", "mistral", "mixtral"]
    supports_vision = any(marker in text for marker in vision_markers)
    if any(marker in text for marker in text_only_markers) and not any(marker in text for marker in ["vl", "vision", "omni"]):
        supports_vision = False
    if vision_override is True:
        supports_vision = True
    elif vision_override is False:
        supports_vision = False
    return {
        "provider": provider,
        "model_name": model_name,
        "supports_vision": supports_vision,
        "vision_reason": (
            "user enabled Vision"
            if vision_override is True
            else "user disabled Vision"
            if vision_override is False
            else "model name indicates vision/multimodal support"
            if supports_vision
            else "model name treated as text-only"
        ),
    }


def _image_url_part(path: str) -> dict | None:
    norm_path = os.path.normpath(path)
    if not os.path.exists(norm_path):
        return None
    ext = os.path.splitext(norm_path)[1].lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext)
    if not mime:
        return None
    try:
        with open(norm_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    except OSError:
        return None


async def _build_visual_edit_prompt(
    client,
    model_name: str,
    source_path: str,
    user_request: str,
    capabilities: dict,
) -> str:
    if not capabilities.get("supports_vision"):
        return user_request
    image_part = _image_url_part(source_path)
    if not image_part:
        return user_request
    system_hint = (
        "你是图片编辑提示词生成器。请先理解输入图片内容，再结合用户要求，"
        "输出一条可直接交给图像编辑/重绘工作流的简洁提示词。"
        "必须保留原图主体、构图和风格，只修改用户要求的部分。只输出提示词本身。"
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"用户要求：{user_request}"},
                        image_part,
                    ],
                },
            ],
        )
        prompt = (response.choices[0].message.content or "").strip()
        return prompt or user_request
    except Exception as e:
        print(f"[router] visual prompt failed: {e}")
        return user_request


ROUTER_ACTIONS = {
    "chat",
    "general_tools",
    "generate_image",
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


def _router_safe_json(text: str) -> dict:
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


async def _build_router_context(req: ChatRequest, capabilities: dict | None = None) -> dict:
    latest_image = await _find_latest_edit_source_image(req.conversation_id)
    latest_multiview = await _find_latest_multiview_paths(req.conversation_id)
    image_paths = _image_attachments(req.image_paths)
    document_paths = _document_attachments(req.image_paths)
    project_documents = []
    project_images = []
    project_files = []
    if req.project_path:
        project_documents = _project_document_paths(req.project_path, req.content)[:5]
        project_images = _project_image_paths(req.project_path, req.content)[:5]
        project_files = _project_file_candidates(req.project_path, req.content)[:20]
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


def _result_output_paths(routed_result: dict | str | None) -> list[str]:
    if not isinstance(routed_result, dict):
        return []
    result = routed_result.get("result") if "result" in routed_result else routed_result
    if not isinstance(result, dict):
        return []
    keys = [
        "image_path",
        "improved_image_path",
        "model_path",
        "image_2d",
        "image_normal",
        "image_uv",
        "front_path",
        "left_path",
        "back_path",
        "path",
        "output_path",
    ]
    paths = []
    for key in keys:
        value = result.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    files = result.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
    deduped = []
    seen = set()
    for path in paths:
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


async def _agent_trace_block(
    req: ChatRequest,
    provider_config,
    decision: dict | None,
    routed_result: dict | str | None,
) -> str:
    capabilities = _model_capabilities(provider_config, req.vision_enabled)
    context = await _build_router_context(req, capabilities)
    trace = {
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
        "outputs": _result_output_paths(routed_result),
    }
    return "\n\n[AGENT_TRACE]" + json.dumps(trace, ensure_ascii=False) + "[/AGENT_TRACE]"


async def _direct_agent_trace_block(
    req: ChatRequest,
    provider_config,
    action: str,
    tool: str,
    result: dict | None = None,
    reason: str = "",
    source: str = "direct",
    source_files: list[str] | None = None,
) -> str:
    decision = {
        "action": action,
        "tool": tool,
        "source": source,
        "source_files": source_files or [],
        "reason": reason or "matched direct tool path",
        "prompt": req.content,
    }
    routed_result = {"tool": tool, "result": result or {}}
    return await _agent_trace_block(req, provider_config, decision, routed_result)


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
        "可选 action: chat, general_tools, generate_image, edit_image, generate_3d_text, "
        "generate_3d_image, generate_3d_fusion, generate_multiview_images, generate_3d_multiview, project_document_image, project_document_3d, "
        "attachment_document_image, attachment_document_3d, read_document, create_docx, edit_docx, folder_summary_docx, create_text_file, choose_implementation。"
        "规则：如果用户要生成/画一张新图片，选 generate_image；如果用户上传图片、引用 latest_active_image，或要求修改项目/文件夹里的图片，并要求补全、画完整、扩图、改颜色、润色、修改，选 edit_image；"
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


async def _run_project_document_read(req: ChatRequest, client, model_name: str) -> str | None:
    docs = _document_attachments(req.image_paths)
    if not docs:
        docs = _project_document_paths(req.project_path or "", req.content)[:5]
    if not docs:
        return None

    sections = _read_document_attachments(docs, 14000)
    system_hint = (
        "你是项目文档阅读助手。基于已读取的项目文件内容回答用户，不要编造。"
        "如果用户要求总结，就按要点输出；如果用户要求生成图片/模型提示词，则忠实提取文档要求。"
    )
    user_text = f"用户需求：{req.content}\n\n文档路径：\n" + "\n".join(docs) + "\n\n文档内容：\n\n" + "\n\n---\n\n".join(sections)
    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_hint},
            {"role": "user", "content": user_text},
        ],
    )
    return response.choices[0].message.content or ""


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
        result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, quality_mode)
        result["source_prompt"] = prompt
        result["quality_mode"] = quality_mode
        return {"tool": "generate_image", "result": result}

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
                result = await asyncio.to_thread(memory_mgr.handle_generate_image, prompt, quality_mode)
                result["source_prompt"] = prompt
                result["source_mode"] = "text_only_model_no_source_image"
                result["quality_mode"] = quality_mode
                return {"tool": "generate_image", "result": result}
            return {
                "tool": "edit_image",
                "result": {"status": "error", "message": "没有找到可编辑的源图片，请先上传图片、生成一张图片，或在当前项目文件夹中放入图片。"},
            }
        edit_prompt = await _build_visual_edit_prompt(client, model_name, source, prompt, capabilities)
        result = await asyncio.to_thread(memory_mgr.handle_modify_image, source, edit_prompt)
        result["source_prompt"] = edit_prompt
        result["source_image"] = source
        result["used_multimodal_prompt"] = bool(capabilities.get("supports_vision") and edit_prompt != prompt)
        return {"tool": "edit_image", "result": result}

    if action == "generate_3d_text":
        result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_text, prompt, quality_mode)
        result["quality_mode"] = quality_mode
        return {"tool": "generate_3d_from_text", "result": result}

    if action in {"generate_3d_image", "generate_3d_fusion"}:
        image_paths = [os.path.normpath(path) for path in _image_attachments(req.image_paths)]
        if not image_paths:
            latest = await _find_latest_edit_source_image(req.conversation_id)
            if latest:
                image_paths = [latest]
        if action == "generate_3d_fusion" and len(image_paths) >= 2:
            result = await asyncio.to_thread(memory_mgr.handle_generate_3d_fusion, image_paths[0], image_paths[1], prompt)
            return {"tool": "generate_3d_fusion", "result": result}
        if image_paths:
            result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_image, image_paths[0])
            return {"tool": "generate_3d_from_image", "result": result}
        result = await asyncio.to_thread(memory_mgr.handle_generate_3d_from_text, prompt, quality_mode)
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
        result = await asyncio.to_thread(memory_mgr.handle_generate_multiview_images_from_image, source, quality_mode)
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


def _format_router_result(routed_result: dict | str | None) -> str | None:
    if routed_result is None:
        return None
    if isinstance(routed_result, str):
        return routed_result
    if "tool" in routed_result:
        tool = routed_result["tool"]
        result = routed_result.get("result") or {}
        if tool in {"generate_image", "edit_image", "generate_multiview_images_from_image"}:
            return _format_image_response(tool, result)
        if tool in THREE_D_TOOL_NAMES:
            return _format_3d_response(tool, result)
        if tool == "implementation_choice":
            return result.get("message") or _format_implementation_choice_card("")
        if tool == "create_text_file":
            return _format_text_file_create_response(result or {})
    if routed_result.get("path") and routed_result.get("ok") is not None:
        if str(routed_result.get("path", "")).lower().endswith(".docx"):
            return _format_docx_create_response(routed_result)
    if routed_result.get("document_count") is not None or routed_result.get("needs_path"):
        return _format_folder_summary_response(routed_result)
    return None


async def _inject_router_context(conversation_id: str, routed_result: dict | str | None):
    if not isinstance(routed_result, dict) or "tool" not in routed_result:
        return
    result = routed_result.get("result") or {}
    if routed_result["tool"] in {"generate_image", "edit_image", "generate_multiview_images_from_image"}:
        await _inject_image_context(conversation_id, result)
    elif routed_result["tool"] in THREE_D_TOOL_NAMES:
        await _inject_3d_context(conversation_id, result)


async def _save_user_message(db, conversation_id: str, content: str):
    user_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, conversation_id, "user", content, now),
    )
    await db.commit()
    return user_id


async def _save_visible_user_message(db, req: ChatRequest):
    if req.hidden_user_message:
        return None
    return await _save_user_message(db, req.conversation_id, req.content)


async def _remove_internal_source_message(db, req: ChatRequest):
    if not req.remove_message_id:
        return
    await db.execute(
        "DELETE FROM stm_entries WHERE id = ? AND conversation_id = ? AND role = 'assistant'",
        (req.remove_message_id, req.conversation_id),
    )
    await db.commit()


def _schedule_title_generation(db, req: ChatRequest):
    if not req.hidden_user_message:
        asyncio.create_task(_maybe_generate_title(db, req.conversation_id, req.content))


async def _save_assistant_message(db, conversation_id: str, content: str):
    assistant_id = uuid.uuid4().hex
    assistant_now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (assistant_id, conversation_id, "assistant", content, assistant_now),
    )
    await db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (assistant_now, conversation_id),
    )
    await db.commit()
    return assistant_id, assistant_now


async def _maybe_generate_title(db, conversation_id: str, user_content: str, model_id: str | None = None):
    row = await db.execute_fetchall(
        "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not row or row[0][0] != "新对话":
        return
    client, provider_config = await _get_provider_client(db, model_id)
    if not client:
        return
    try:
        response = await client.chat.completions.create(
            model=provider_config[1],
            messages=[
                {
                    "role": "system",
                    "content": "用不超过8个汉字概括以下对话的主题，只输出标题，不要加引号或其他符号。",
                },
                {"role": "user", "content": user_content[:200]},
            ],
            max_tokens=20,
        )
        title = response.choices[0].message.content.strip().strip('"').strip("'")
        if title:
            now = datetime.datetime.utcnow().isoformat()
            await db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            await db.commit()
    except Exception:
        pass


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
            elif tool_call.function.name == "generate_3d_from_text":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_text(
                        args.get("prompt", ""),
                        args.get("quality_mode", "fast"),
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
            if generation_queue_state().get("busy"):
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
                    if generation_queue_state().get("busy"):
                        yield f"data: {json.dumps({'status': COMFY_QUEUED_STATUS}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'status': COMFY_STARTING_STATUS}, ensure_ascii=False)}\n\n"
                if action == "generate_image":
                    yield f"data: {json.dumps({'status': '正在生成图片'}, ensure_ascii=False)}\n\n"
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
            if generation_queue_state().get("busy"):
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
            if generation_queue_state().get("busy"):
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
                if generation_queue_state().get("busy"):
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
                if generation_queue_state().get("busy"):
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
                        if generation_queue_state().get("busy"):
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
