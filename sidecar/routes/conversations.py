import datetime
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from db.sqlite import get_db
from schemas import ConversationCreate, ProjectCreate

router = APIRouter()

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


def _project_visible_files(root: Path, limit: int = 80) -> dict:
    ignored_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "target",
        "dist",
        "build",
    }
    documents = []
    images = []
    scanned = 0
    try:
        for path in root.rglob("*"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            scanned += 1
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in DOCUMENT_EXTENSIONS and suffix not in IMAGE_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            item = {
                "name": path.name,
                "path": str(path),
                "relativePath": str(path.relative_to(root)),
                "extension": suffix.lstrip("."),
                "size": stat.st_size,
                "modifiedAt": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
            if suffix in IMAGE_EXTENSIONS:
                images.append(item)
            else:
                documents.append(item)
            if len(documents) + len(images) >= limit:
                break
    except OSError:
        pass

    documents.sort(key=lambda item: item["modifiedAt"], reverse=True)
    images.sort(key=lambda item: item["modifiedAt"], reverse=True)
    return {
        "rootPath": str(root),
        "documents": documents,
        "images": images,
        "documentCount": len(documents),
        "imageCount": len(images),
        "scannedCount": scanned,
    }


@router.get("/projects")
async def list_projects():
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, name, root_path, created_at, updated_at FROM projects ORDER BY updated_at DESC"
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "rootPath": r[2],
            "createdAt": r[3],
            "updatedAt": r[4],
        }
        for r in rows
    ]


@router.post("/projects")
async def create_project(req: ProjectCreate):
    root = Path(os.path.expandvars(os.path.expanduser(req.path))).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Project folder not found: {root}")

    db = await get_db()
    now = datetime.datetime.utcnow().isoformat()
    existing = await db.execute_fetchall(
        "SELECT id, name, root_path, created_at, updated_at FROM projects WHERE root_path = ?",
        (str(root),),
    )
    if existing:
        r = existing[0]
        await db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, r[0]))
        await db.commit()
        return {
            "id": r[0],
            "name": r[1],
            "rootPath": r[2],
            "createdAt": r[3],
            "updatedAt": now,
        }

    project_id = uuid.uuid4().hex
    name = (req.name or root.name or str(root)).strip()
    await db.execute(
        "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, name, str(root), now, now),
    )
    await db.commit()
    return {
        "id": project_id,
        "name": name,
        "rootPath": str(root),
        "createdAt": now,
        "updatedAt": now,
    }


@router.get("/projects/{project_id}/files")
async def list_project_files(project_id: str):
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT root_path FROM projects WHERE id = ? LIMIT 1",
        (project_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Project not found")
    root = Path(rows[0][0])
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Project folder not found: {root}")
    return _project_visible_files(root)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    db = await get_db()
    await db.execute(
        """
        DELETE FROM stm_entries
        WHERE conversation_id IN (
            SELECT id FROM conversations WHERE project_id = ?
        )
        """,
        (project_id,),
    )
    await db.execute("DELETE FROM conversations WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()
    return {"ok": True}


@router.post("/conversations")
async def create_conversation(req: ConversationCreate):
    db = await get_db()
    if req.project_id:
        project = await db.execute_fetchall(
            "SELECT id FROM projects WHERE id = ? LIMIT 1",
            (req.project_id,),
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
    conv_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO conversations (id, title, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (conv_id, req.title, req.project_id, now, now),
    )
    await db.commit()
    return {
        "id": conv_id,
        "title": req.title,
        "projectId": req.project_id,
        "createdAt": now,
        "updatedAt": now,
    }


@router.get("/conversations")
async def list_conversations(project_id: str | None = None):
    db = await get_db()
    if project_id:
        rows = await db.execute_fetchall(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations WHERE project_id IS NULL ORDER BY updated_at DESC"
        )
    return [
        {
            "id": r[0],
            "title": r[1],
            "projectId": r[2],
            "createdAt": r[3],
            "updatedAt": r[4],
        }
        for r in rows
    ]


@router.put("/conversations/{conv_id}/title")
async def update_conversation_title(conv_id: str, body: dict):
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    db = await get_db()
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    await db.commit()
    return {"id": conv_id, "title": title, "updatedAt": now}


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str):
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, conversation_id, role, content, created_at FROM stm_entries WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    )
    return [
        {
            "id": r[0],
            "conversationId": r[1],
            "role": r[2],
            "content": r[3],
            "createdAt": r[4],
        }
        for r in rows
    ]


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    db = await get_db()
    await db.execute("DELETE FROM stm_entries WHERE conversation_id = ?", (conv_id,))
    await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    await db.commit()
    return {"ok": True}
