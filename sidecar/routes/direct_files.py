import json
import os
import re
from pathlib import Path

from db.sqlite import get_db
from memory import manager as memory_mgr
from schemas import ChatRequest

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


def _safe_json(text: str) -> dict:
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}


def _document_attachments(paths: list[str] | None) -> list[str]:
    return [
        path
        for path in paths or []
        if os.path.splitext(path)[1].lower() in DOCUMENT_EXTENSIONS
    ]


def is_docx_create_intent(content: str) -> bool:
    blocked_text = (content or "").lower()
    if any(word in blocked_text for word in ["删除", "删了", "删掉", "移除", "理解错", "误解"]):
        return False
    text = (content or "").lower()
    has_docx = any(word in text for word in ["docx", "word", "文档"])
    has_create = any(word in text for word in ["创建", "新建", "生成", "写一个", "写一则", "写一篇", "在里面写"])
    return has_docx and has_create


def is_text_file_create_intent(content: str) -> bool:
    text = (content or "").lower()
    if is_docx_create_intent(content):
        return False
    create_words = ["创建", "新建", "写一个", "写一份", "写一款", "生成一个", "做一个", "做一款", "实现"]
    file_words = [
        "html",
        "网页",
        "网站",
        "小游戏",
        "游戏",
        "扫雷",
        "贪吃蛇",
        "五子棋",
        "俄罗斯方块",
        "2048",
        "代码",
        "程序",
        ".html",
        ".js",
        ".css",
        ".py",
        ".txt",
        ".md",
    ]
    return any(word in text for word in create_words) and any(word in text for word in file_words)


def _is_game_file_request(content: str) -> bool:
    text = (content or "").lower()
    game_words = ["小游戏", "游戏", "扫雷", "贪吃蛇", "五子棋", "俄罗斯方块", "2048", "snake", "minesweeper"]
    create_words = ["创建", "新建", "写一个", "写一份", "写一款", "生成一个", "做一个", "做一款", "实现", "build", "make", "create"]
    return any(word in text for word in create_words) and any(word in text for word in game_words)


def _has_explicit_text_file_format(content: str) -> bool:
    text = (content or "").lower()
    explicit_words = [
        "html",
        ".html",
        "网页",
        "浏览器",
        "python",
        ".py",
        "tkinter",
        "pygame",
        "javascript",
        ".js",
        "react",
        "vue",
        "单文件",
        "选择实现方式",
    ]
    return any(word in text for word in explicit_words)


def needs_implementation_choice(content: str) -> bool:
    return _is_game_file_request(content) and not _has_explicit_text_file_format(content)


def format_implementation_choice_card(content: str) -> str:
    return "\n".join(
        [
            "[IMPLEMENTATION_CHOICE_REQUIRED]",
            f"需求: {content}",
            "候选:",
            "- html: HTML 单文件，可双击打开，适合扫雷/贪吃蛇这类轻量小游戏。",
            "- python: Python Tkinter 单文件，适合本地运行和后续改逻辑。",
            "- web: 多文件 Web 项目，可生成 index.html、style.css、app.js 等，适合后续扩展成完整前端应用。",
            "[/IMPLEMENTATION_CHOICE_REQUIRED]",
        ]
    )


def _infer_text_file_name(content: str) -> str:
    text = content or ""
    explicit = re.search(r"([^\s`\"'，。；;\\/]+\.(?:html|htm|js|css|py|txt|md|json))", text, re.I)
    if explicit:
        return explicit.group(1)
    lowered = text.lower()
    if "python" in lowered or ".py" in lowered or "tkinter" in lowered or "pygame" in lowered:
        if "贪吃蛇" in text and "扫雷" in text:
            return "mini_games.py"
        if "扫雷" in text or "minesweeper" in lowered:
            return "minesweeper.py"
        if "贪吃蛇" in text or "snake" in lowered:
            return "snake_game.py"
        return "script.py"
    if "html" in lowered or "网页" in text or "网站" in text or "小游戏" in text or "游戏" in text:
        if "贪吃蛇" in text and "扫雷" in text:
            return "mini_games.html"
        if "扫雷" in text or "minesweeper" in lowered:
            return "minesweeper.html"
        if "贪吃蛇" in text:
            return "snake_game.html"
        return "index.html"
    if "markdown" in lowered or ".md" in lowered:
        return "document.md"
    return "新建文件.txt"


def _safe_project_output_path(project_path: str | None, filename: str) -> Path:
    root = Path(project_path).resolve() if project_path else (Path.home() / "Desktop")
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / filename).resolve()
    if root not in candidate.parents and candidate != root:
        candidate = root / Path(filename).name
    if candidate.exists():
        stem = candidate.stem
        suffix = candidate.suffix
        index = 2
        while True:
            next_candidate = candidate.with_name(f"{stem}_{index}{suffix}")
            if not next_candidate.exists():
                candidate = next_candidate
                break
            index += 1
    return candidate


def _normalize_generated_file_item(item: dict, fallback_name: str) -> tuple[str, str] | None:
    raw_name = str(item.get("filename") or item.get("path") or item.get("name") or fallback_name).strip()
    content = item.get("content")
    if not raw_name or content is None:
        return None
    normalized = raw_name.replace("\\", "/").lstrip("/")
    if re.match(r"^[A-Za-z]:/", normalized):
        normalized = Path(normalized).name
    parts = [part for part in normalized.split("/") if part not in {"", ".", ".."}]
    if not parts:
        parts = [fallback_name]
    safe_name = "/".join(parts)
    suffix = Path(safe_name).suffix.lower()
    allowed_special = {".gitignore", "dockerfile", "makefile", "readme", "license"}
    if suffix and suffix not in GENERATED_TEXT_EXTENSIONS:
        safe_name = f"{Path(safe_name).stem or Path(fallback_name).stem}.txt"
    elif not suffix and Path(safe_name).name.lower() not in allowed_special:
        safe_name = f"{safe_name}.txt"
    return safe_name, str(content)


def _generated_file_items(payload: dict, fallback_name: str) -> list[tuple[str, str]]:
    raw_files = payload.get("files")
    files: list[tuple[str, str]] = []
    if isinstance(raw_files, list):
        for item in raw_files[:20]:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_generated_file_item(item, fallback_name)
            if normalized:
                files.append(normalized)
    if files:
        return files
    normalized = _normalize_generated_file_item(
        {"filename": payload.get("filename") or fallback_name, "content": payload.get("content")},
        fallback_name,
    )
    return [normalized] if normalized else []


def _candidate_local_paths(content: str) -> list[str]:
    text = content or ""
    candidates: list[str] = []
    for pattern in [r"`([^`]+)`", r'"([^"]+)"', r"'([^']+)'", r"“([^”]+)”"]:
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


def _extract_directory_path(content: str) -> Path | None:
    for candidate in _candidate_local_paths(content):
        try:
            path = _resolve_local_path(candidate)
        except OSError:
            continue
        if path.exists() and path.is_dir():
            return path
    return None


async def run_direct_text_file_create(
    req: ChatRequest,
    client,
    model_name: str,
    force: bool = False,
    prompt_override: str | None = None,
) -> dict | None:
    request_text = prompt_override or req.content
    if req.image_paths or (not force and not is_text_file_create_intent(request_text)):
        return None
    filename = _infer_text_file_name(request_text)
    explicit_folder = _extract_directory_path(request_text)
    output_root = str(explicit_folder) if explicit_folder else req.project_path
    output_path = _safe_project_output_path(output_root, filename)
    system_hint = (
        "你是本地文件生成助手。只输出 JSON，不要 Markdown。"
        "优先输出格式: {\"files\":[{\"filename\":\"相对路径/文件名\",\"content\":\"完整文件内容\"}]}。"
        "兼容单文件格式: {\"filename\":\"文件名\",\"content\":\"完整文件内容\"}。"
        "如果任务需要多个文件才完整，例如 Web 小工具、页面、Demo 或小项目，就一次返回多个 files。"
        "如果用户明确要求 HTML 单文件，输出一个可直接打开运行的完整单文件 HTML，包含 CSS 和 JS。"
        "如果用户要求多个小游戏且未要求拆分项目，可以写在同一个 HTML 文件里；如果用户要求 Web 项目，可拆分为 index.html、style.css、app.js。"
        "不要创建 .bak 备份；新文件重名时系统会自动生成不冲突的文件名。"
        "filename 必须是相对路径，不要输出绝对路径，不要使用 ..。"
    )
    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_hint},
            {"role": "user", "content": request_text},
        ],
        response_format={"type": "json_object"},
    )
    payload = _safe_json(response.choices[0].message.content or "{}")
    files = _generated_file_items(payload, filename)
    if not files:
        return {"ok": False, "error": "模型没有返回可写入的文件内容", "path": str(output_path)}
    write_result = memory_mgr.handle_write_many_files(
        output_root or str(Path.home() / "Desktop"),
        [{"path": relative_name, "content": content} for relative_name, content in files],
        False,
    )
    if not write_result.get("files"):
        return {
            "ok": False,
            "error": write_result.get("error") or "没有成功写入文件",
            "path": str(output_path),
            "write_result": write_result,
        }
    written = []
    for item in write_result.get("files", []):
        item_path = Path(item.get("path", ""))
        written.append(
            {
                "path": str(item_path),
                "name": item.get("name") or item_path.name,
                "extension": item_path.suffix.lower(),
                "size_bytes": item.get("size_bytes", 0),
            }
        )
    first = written[0]
    return {
        "ok": bool(write_result.get("ok")),
        "path": first["path"],
        "name": first["name"],
        "extension": first["extension"],
        "size_bytes": first["size_bytes"],
        "files": written,
        "file_count": len(written),
        "errors": write_result.get("errors", []),
        "error_count": write_result.get("error_count", 0),
    }


def is_text_file_edit_followup_intent(content: str) -> bool:
    text = (content or "").lower()
    blocked_words = [
        "删除",
        "删掉",
        "移除",
        "新建",
        "创建新的",
        "全新",
        "重新创建",
        "重新生成",
        "重新写",
        "重写",
        "重做",
        "另一个",
        "另外一个",
        "delete",
        "remove",
        "new file",
        "from scratch",
    ]
    if any(word in text for word in blocked_words):
        return False
    edit_words = [
        "修改",
        "改成",
        "改为",
        "换成",
        "替换",
        "修复",
        "优化",
        "美化",
        "调整",
        "扩大",
        "缩小",
        "加入",
        "添加",
        "增加",
        "加一个",
        "加上",
        "补充",
        "追加",
        "对手",
        "敌人",
        "按钮",
        "分数",
        "关卡",
        "难度",
        "颜色",
        "布局",
        "edit",
        "modify",
        "update",
        "add",
        "fix",
    ]
    return any(word in text for word in edit_words)


def extract_explicit_text_file_path(content: str) -> str | None:
    for match in TEXT_FILE_PATH_PATTERN.finditer(content or ""):
        path = (match.group(1) or match.group(2) or "").strip()
        if path:
            return path
    for candidate in _candidate_local_paths(content):
        suffix = Path(candidate.strip("`\"'")).suffix.lower()
        if suffix in GENERATED_TEXT_EXTENSIONS:
            return candidate
    return None


async def find_latest_text_file_path(conversation_id: str) -> str | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT content FROM stm_entries
        WHERE conversation_id = ? AND role = 'assistant'
        ORDER BY created_at DESC
        LIMIT 40
        """,
        (conversation_id,),
    )
    fallback = None
    for (content,) in rows:
        for match in TEXT_FILE_PATH_PATTERN.finditer(content or ""):
            path = (match.group(1) or match.group(2) or "").strip()
            if not path:
                continue
            if fallback is None:
                fallback = path
            try:
                resolved = _resolve_local_path(path)
                if resolved.exists() and resolved.is_file():
                    return str(resolved)
            except Exception:
                continue
    return fallback


def _wants_no_backup(content: str) -> bool:
    text = (content or "").lower()
    return any(word in text for word in ["删除备份", "不要备份", "不保留备份", "清理备份"])


def _wants_backup(content: str) -> bool:
    text = (content or "").lower()
    if _wants_no_backup(content):
        return False
    return any(word in text for word in ["备份", "保留副本", "留个副本", "backup", "bak"])


async def run_direct_text_file_edit(req: ChatRequest, client, model_name: str) -> dict | None:
    if req.image_paths:
        return None

    target_path = extract_explicit_text_file_path(req.content)
    if not target_path:
        target_path = await find_latest_text_file_path(req.conversation_id)
    if not target_path or not is_text_file_edit_followup_intent(req.content):
        return None

    try:
        resolved = _resolve_local_path(target_path)
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if resolved.suffix.lower() not in GENERATED_TEXT_EXTENSIONS:
        return None

    original_result = memory_mgr.handle_read_document(str(resolved), 2_000_000)
    if not original_result.get("ok"):
        return original_result
    original = original_result.get("content") or ""
    system_hint = (
        "你是本地代码文件编辑助手。只输出 JSON，不要 Markdown。"
        '格式：{"content":"完整更新后的文件内容"}。'
        "必须在用户给定的现有文件基础上修改，保留原有可用功能，只实现用户要求的增量变化。"
        "不要输出解释，不要创建新文件，不要删除旧文件。"
    )
    user_text = (
        f"用户修改需求：{req.content}\n\n"
        f"目标路径：{resolved}\n\n"
        "当前完整文件内容：\n"
        "```text\n"
        f"{original}\n"
        "```"
    )
    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_hint},
            {"role": "user", "content": user_text},
        ],
        response_format={"type": "json_object"},
    )
    payload = _safe_json(response.choices[0].message.content or "{}")
    updated = str(payload.get("content") or "")
    if not updated.strip():
        return {"ok": False, "error": "模型没有返回更新后的文件内容", "path": str(resolved)}
    if updated == original:
        return {"ok": True, "path": str(resolved), "changed": False, "action": "replace", "replacements": 0}
    backup_path = None
    if _wants_backup(req.content):
        backup_path = resolved.with_suffix(resolved.suffix + ".bak")
        index = 2
        while backup_path.exists():
            backup_path = resolved.with_suffix(resolved.suffix + f".{index}.bak")
            index += 1
        backup_path.write_text(original, encoding="utf-8")
    resolved.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "path": str(resolved),
        "changed": True,
        "action": "replace",
        "replacements": 1,
        "backup_path": str(backup_path) if backup_path else None,
        "fallback": "full_file_rewrite",
    }


def edit_text_result_can_fallback(result: dict | None) -> bool:
    if not isinstance(result, dict) or result.get("ok"):
        return False
    error = str(result.get("error") or result.get("message") or "")
    return result.get("needs_read") or "未找到要替换的内容" in error or "oldString not found" in error


def is_docx_edit_intent(content: str) -> bool:
    text = (content or "").lower()
    doc_words = ["docx", "word", "文档", "文件", "这个", "这个文档", "这个文件", "里面", "在里面"]
    edit_words = ["再写", "追加", "补充", "加上", "加入", "写入", "在里面写", "改成", "替换", "修改"]
    new_words = ["新建", "创建新的", "全新", "另一个", "另外一个"]
    return (
        any(word in text for word in doc_words)
        and any(word in text for word in edit_words)
        and not any(word in text for word in new_words)
    )


def _is_docx_followup_edit_intent(content: str) -> bool:
    text = (content or "").lower()
    new_artifact_words = [
        "html",
        "网页",
        "网站",
        "小游戏",
        "游戏",
        "代码",
        "程序",
        "app",
        "python",
        "javascript",
        "typescript",
        "react",
        "vue",
    ]
    if any(word in text for word in new_artifact_words):
        return False
    followup_words = [
        "再写",
        "继续写",
        "继续",
        "再来",
        "再加",
        "追加",
        "补充",
        "加到",
        "加入",
        "写入",
        "在里面写",
        "加一篇",
        "再写一篇",
    ]
    blocked_words = ["新建", "创建新的", "全新", "另一个", "另外一个", "不要用之前"]
    return any(word in text for word in followup_words) and not any(word in text for word in blocked_words)


async def _find_latest_docx_path(conversation_id: str) -> str | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT content FROM stm_entries
        WHERE conversation_id = ? AND role = 'assistant'
        ORDER BY created_at DESC
        LIMIT 30
        """,
        (conversation_id,),
    )
    for (content,) in rows:
        for match in DOCX_PATH_PATTERN.finditer(content or ""):
            path = (match.group(1) or match.group(2) or "").strip()
            if path and path.lower().endswith(".docx"):
                return path
    return None


def _delete_docx_backups(file_path: str) -> list[str]:
    path = Path(file_path)
    deleted: list[str] = []
    parent = path.parent
    if not parent.exists():
        return deleted
    patterns = [f"{path.name}.bak", f"{path.stem}{path.suffix}_*.bak"]
    for pattern in patterns:
        for candidate in parent.glob(pattern):
            if candidate.is_file():
                try:
                    candidate.unlink()
                    deleted.append(str(candidate))
                except OSError:
                    pass
    return deleted


async def _generate_docx_paragraphs(content: str, client, model_name: str) -> tuple[str, list[str]]:
    system_hint = (
        "你只输出 JSON，不要 Markdown。格式："
        '{"title":"标题","paragraphs":["段落1","段落2"]}。'
        "根据用户要求生成适合追加写入 Word 文档的内容。"
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception:
        payload = {}

    title = str(payload.get("title") or "").strip()
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        paragraphs = [content.strip()]
    return title, [str(item) for item in paragraphs if str(item).strip()]


async def run_direct_docx_edit(req: ChatRequest, client, model_name: str) -> dict | None:
    if req.image_paths:
        return None

    explicit = DOCX_PATH_PATTERN.search(req.content or "")
    target_path = None
    if explicit:
        target_path = (explicit.group(1) or explicit.group(2) or "").strip()
    if not target_path:
        target_path = await _find_latest_docx_path(req.conversation_id)
    if not (is_docx_edit_intent(req.content) or (target_path and _is_docx_followup_edit_intent(req.content))):
        return None
    if not target_path:
        return None

    existing = memory_mgr.handle_read_document(target_path, 6000)
    existing_text = existing.get("content", "") if existing.get("ok") else ""
    generation_request = (
        f"用户要求：{req.content}\n\n"
        f"当前 Word 文档内容：\n{existing_text}\n\n"
        "请只生成要追加到文档末尾的新内容，不要重复已有内容，不要输出备份/删除备份等文件操作说明。"
    )
    title, paragraphs = await _generate_docx_paragraphs(generation_request, client, model_name)
    text = "\n".join(([title] if title else []) + paragraphs)
    wants_backup = _wants_backup(req.content)
    result = memory_mgr.handle_edit_docx_document(target_path, "append", text, "", "", wants_backup)
    if _wants_no_backup(req.content) and result.get("ok"):
        result["deleted_backups"] = _delete_docx_backups(target_path)
    return result


def _extract_requested_docx_path(content: str, project_path: str | None = None) -> str:
    text = content or ""
    explicit = LOCAL_PATH_PATTERN.search(text)
    if explicit:
        path = explicit.group(1).strip("`\"'")
        if not path.lower().endswith(".docx"):
            path = f"{path}.docx"
        return path

    name_match = re.search(r"(?:文件名|命名为|叫|名为)[:：]?\s*([^\s，。；;`\"']+)", text)
    if name_match:
        filename = name_match.group(1).strip()
    elif "冷笑话" in text:
        filename = "冷笑话.docx"
    else:
        filename = "新建文档.docx"

    if not filename.lower().endswith(".docx"):
        filename = f"{filename}.docx"
    if any(word in text.lower() for word in ["desktop", "桌面"]):
        return f"Desktop/{filename}"
    if project_path:
        return str(Path(project_path) / filename)
    return filename


async def run_direct_docx_create(req: ChatRequest, client, model_name: str) -> dict | None:
    if req.image_paths or not is_docx_create_intent(req.content):
        return None

    output_path = _extract_requested_docx_path(req.content, req.project_path)
    system_hint = (
        "你只输出 JSON，不要 Markdown。格式："
        '{"title":"标题","paragraphs":["段落1","段落2"]}。'
        "根据用户要求生成适合写入 Word 文档的简短内容。"
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": req.content},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception:
        payload = {}

    title = str(payload.get("title") or "文档").strip()
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        if "冷笑话" in req.content:
            title = "冷笑话"
            paragraphs = ["问：什么门永远关不上？", "答：球门。"]
        else:
            paragraphs = [req.content.strip()]

    return memory_mgr.handle_create_docx_document(
        output_path,
        title,
        [str(item) for item in paragraphs],
        False,
    )


def _is_document_read_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if not _document_attachments(image_paths):
        return False
    text = (content or "").lower()
    return any(
        word in text
        for word in ["总结", "阅读", "读取", "分析", "提取", "看看", "概括", "回答", "讲讲", "整理重点"]
    )


async def run_direct_document_read(req: ChatRequest, client, model_name: str) -> str | None:
    docs = _document_attachments(req.image_paths)
    if not _is_document_read_intent(req.content, req.image_paths):
        return None

    sections = []
    for path in docs[:3]:
        result = memory_mgr.handle_read_document(path, 12000)
        if not result.get("ok"):
            sections.append(f"[{path}]\n读取失败：{result.get('error', 'unknown error')}")
            continue
        sections.append(f"[{result.get('name') or path}]\n{result.get('content', '')}")

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "你是文档阅读助手。基于用户提供的文档内容回答，不要编造。如果内容不足，直接说明。回答要简洁、结构清楚。",
            },
            {
                "role": "user",
                "content": f"用户需求：{req.content}\n\n文档内容：\n\n" + "\n\n---\n\n".join(sections),
            },
        ],
    )
    return response.choices[0].message.content or ""


def format_docx_create_response(result: dict) -> str:
    if result.get("ok"):
        return f"已创建 Word 文档：`{result.get('path')}`"
    return f"创建 Word 文档失败：{result.get('error', '未知错误')}"


def format_docx_edit_response(result: dict) -> str:
    if result.get("ok"):
        backup = result.get("backup_path")
        deleted_backups = result.get("deleted_backups") or []
        lines = [f"已更新 Word 文档：`{result.get('path')}`"]
        if backup:
            lines.append(f"备份文件：`{backup}`")
        if deleted_backups:
            lines.append(f"已删除备份：{len(deleted_backups)} 个")
        return "\n".join(lines)
    return f"修改 Word 文档失败：{result.get('error', '未知错误')}"


def format_text_file_create_response(result: dict) -> str:
    if not result.get("ok"):
        files = result.get("files")
        if isinstance(files, list) and files:
            lines = [f"部分文件已创建，但有 {result.get('error_count', 0)} 个错误："]
            for item in files:
                path = item.get("path") if isinstance(item, dict) else ""
                if path:
                    lines.append(f"- `{path}`")
            for item in result.get("errors", [])[:5]:
                lines.append(f"- 错误：{item.get('path', '')} {item.get('error', '')}")
            return "\n".join(lines)
        return f"创建文件失败：{result.get('error', '未知错误')}"
    files = result.get("files")
    if isinstance(files, list) and len(files) > 1:
        lines = [f"已创建 {len(files)} 个文件："]
        for item in files:
            path = item.get("path") if isinstance(item, dict) else ""
            if path:
                lines.append(f"- `{path}`")
        return "\n".join(lines)
    path = result.get("path", "")
    name = result.get("name") or Path(path).name
    return f"已创建文件：`{path}`\n\n{name}"


def format_delete_then_create_response(delete_result: dict, create_result: dict | None) -> str:
    if not create_result or not create_result.get("ok"):
        if delete_result.get("needs_confirmation") and delete_result.get("message"):
            return delete_result["message"]
        if delete_result.get("ok") and delete_result.get("message"):
            return delete_result["message"]
        return f"删除失败：{delete_result.get('error') or delete_result.get('message') or '未知错误'}"
    create_text = format_text_file_create_response(create_result)
    if delete_result.get("ok"):
        return f"{create_text}\n\n旧文件已删除。"
    return f"{create_text}\n\n旧文件删除失败：{delete_result.get('error') or delete_result.get('message') or '未知错误'}"
