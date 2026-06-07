import re
from pathlib import Path
from typing import Any

from memory import manager as memory_mgr


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


def extract_confirmed_command(content: str) -> tuple[str, str] | None:
    match = COMMAND_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    command = (match.group(1) or "").strip()
    cwd = (match.group(2) or "").strip()
    if not command:
        return None
    return command, cwd


def run_confirmed_command_request(req: Any) -> dict | None:
    parsed = extract_confirmed_command(req.content)
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


def extract_confirmed_project_check(content: str) -> tuple[str, str] | None:
    match = PROJECT_CHECK_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    path = (match.group(1) or "").strip()
    check_type = (match.group(2) or "auto").strip() or "auto"
    if not path:
        return None
    return path, check_type


def run_confirmed_project_check_request(req: Any) -> dict | None:
    parsed = extract_confirmed_project_check(req.content)
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


def extract_delete_continuation(content: str) -> str:
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


def extract_confirmed_delete(content: str) -> tuple[str, str] | None:
    match = DELETE_CONFIRM_PATTERN.search(content or "")
    if not match:
        return None
    target = (match.group(1) or "").strip()
    if not target:
        return None
    return target, extract_delete_continuation(content)


def with_delete_continuation(message: str, continuation: str) -> str:
    continuation = (continuation or "").strip()
    if not continuation or "[CONFIRM_DELETE_REQUIRED]" not in (message or ""):
        return message
    return message.replace(
        "[/CONFIRM_DELETE_REQUIRED]",
        f"后续任务: `{continuation}`\n[/CONFIRM_DELETE_REQUIRED]",
    )


def delete_then_create_prompt(target_path: str, continuation: str) -> str:
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


def is_delete_request_text(content: str) -> bool:
    text = (content or "").lower()
    return any(word in text for word in ["删除", "删掉", "移除", "清理", "确认删除", "delete", "remove"])
