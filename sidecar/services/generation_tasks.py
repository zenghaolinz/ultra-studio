import json
import sqlite3
import time
import uuid
from typing import Any

from db.sqlite import DB_PATH, get_db

TERMINAL_STATUSES = {"success", "error", "cancelled"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


async def create_generation_task(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    status: str = "queued",
    conversation_id: str | None = None,
    queue_position: int | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    db = await get_db()
    now = now_iso()
    await db.execute(
        """
        INSERT INTO generation_tasks
        (id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '', ?, ?)
        """,
        (
            task_id,
            task_type,
            status,
            conversation_id,
            queue_position,
            prompt or "",
            quality_mode or "",
            json.dumps(input_paths or [], ensure_ascii=False),
            now,
            now,
        ),
    )
    await db.commit()
    return task_id


async def create_running_generation_task(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    conversation_id: str | None = None,
    queue_position: int | None = None,
) -> str:
    return await create_generation_task(
        task_type,
        prompt,
        quality_mode,
        input_paths,
        status="running",
        conversation_id=conversation_id,
        queue_position=queue_position,
    )


def create_generation_task_sync(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    status: str = "queued",
    conversation_id: str | None = None,
    queue_position: int | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    now = now_iso()
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            INSERT INTO generation_tasks
            (id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '', ?, ?)
            """,
            (
                task_id,
                task_type,
                status,
                conversation_id,
                queue_position,
                prompt or "",
                quality_mode or "",
                json.dumps(input_paths or [], ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    return task_id


async def update_generation_task(
    task_id: str | None,
    status: str,
    output_paths: dict | None = None,
    error: str = "",
    queue_position: int | None = None,
) -> None:
    if not task_id:
        return
    db = await get_db()
    now = now_iso()
    completed_at = now if status in TERMINAL_STATUSES else None
    await db.execute(
        """
        UPDATE generation_tasks
        SET status = ?,
            output_paths = ?,
            error = ?,
            queue_position = COALESCE(?, queue_position),
            updated_at = ?,
            completed_at = ?
        WHERE id = ? AND status != 'cancelled'
        """,
        (
            status,
            json.dumps(output_paths or {}, ensure_ascii=False),
            error or "",
            queue_position,
            now,
            completed_at,
            task_id,
        ),
    )
    await db.commit()


def update_generation_task_sync(
    task_id: str | None,
    status: str,
    output_paths: dict | None = None,
    error: str = "",
    queue_position: int | None = None,
) -> None:
    if not task_id:
        return
    now = now_iso()
    completed_at = now if status in TERMINAL_STATUSES else None
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            UPDATE generation_tasks
            SET status = ?,
                output_paths = ?,
                error = ?,
                queue_position = COALESCE(?, queue_position),
                updated_at = ?,
                completed_at = ?
            WHERE id = ? AND status != 'cancelled'
            """,
            (
                status,
                json.dumps(output_paths or {}, ensure_ascii=False),
                error or "",
                queue_position,
                now,
                completed_at,
                task_id,
            ),
        )
        conn.commit()


async def cancel_running_generation_tasks(error: str = "User cancelled generation") -> None:
    db = await get_db()
    now = now_iso()
    await db.execute(
        """
        UPDATE generation_tasks
        SET status = 'cancelled',
            error = ?,
            updated_at = ?,
            completed_at = ?
        WHERE status = 'running'
        """,
        (error, now, now),
    )
    await db.commit()


async def mark_interrupted_generation_tasks(
    error: str = "Generation interrupted because the sidecar restarted",
) -> int:
    db = await get_db()
    now = now_iso()
    cursor = await db.execute(
        """
        UPDATE generation_tasks
        SET status = 'error',
            error = ?,
            updated_at = ?,
            completed_at = ?
        WHERE status = 'running'
        """,
        (error, now, now),
    )
    await db.commit()
    return cursor.rowcount if cursor.rowcount is not None else 0


def generation_task_row_to_dict(row) -> dict[str, Any]:
    try:
        input_paths = json.loads(row["input_paths"] or "[]")
    except Exception:
        input_paths = []
    try:
        output_paths = json.loads(row["output_paths"] or "{}")
    except Exception:
        output_paths = {}
    return {
        "id": row["id"],
        "taskType": row["task_type"],
        "status": row["status"],
        "conversationId": row["conversation_id"] if "conversation_id" in row.keys() else None,
        "queuePosition": row["queue_position"] if "queue_position" in row.keys() else None,
        "prompt": row["prompt"] or "",
        "qualityMode": row["quality_mode"] or "",
        "inputPaths": input_paths,
        "outputPaths": output_paths,
        "error": row["error"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


async def list_generation_tasks(limit: int = 30) -> list[dict[str, Any]]:
    db = await get_db()
    safe_limit = max(1, min(limit, 100))
    rows = await db.execute_fetchall(
        """
        SELECT id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error,
               created_at, updated_at, completed_at
        FROM generation_tasks
        ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    return [generation_task_row_to_dict(row) for row in rows]


def task_result(task_id: str, message: str = "Generation task queued") -> dict[str, Any]:
    return {
        "status": "queued",
        "task_id": task_id,
        "message": message,
    }
