import os
from pathlib import Path
from typing import Any

from db.sqlite import get_db


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
