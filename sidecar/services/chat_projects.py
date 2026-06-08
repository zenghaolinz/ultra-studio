import os
from pathlib import Path
from typing import Any

from db.sqlite import get_db
from services.chat_intents import is_open_folder_intent
from services.chat_paths import extract_directory_path


async def project_path_for_request(req: Any) -> str | None:
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


def with_project_context(content: str, project_path: str | None) -> str:
    if not project_path:
        return content
    return (
        f"{content}\n\n"
        "[当前项目文件夹]\n"
        f"{project_path}\n\n"
        "项目规则：如果用户没有给出其他明确路径，读取、列出、创建、修改、整理文件时都默认在这个项目文件夹内完成。"
        "不要主动访问项目文件夹之外的内容；如果用户要求打开文件夹，就打开这个项目文件夹或其子路径。"
    )


def run_open_folder_request(req: Any) -> dict | None:
    if not is_open_folder_intent(req.content):
        return None
    target = extract_directory_path(req.content)
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
