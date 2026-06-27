import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from db.sqlite import DB_PATH, get_db
from services.generation_events import generation_event_broker

TERMINAL_STATUSES = {"success", "error", "cancelled"}
TRANSITION_SOURCES = {
    "running": ("queued",),
    "success": ("queued", "running"),
    "error": ("queued", "running"),
    "cancelled": ("queued", "running"),
}
_claimed_task_id: ContextVar[str | None] = ContextVar("claimed_generation_task_id", default=None)


@contextmanager
def claim_generation_task(task_id: str):
    token = _claimed_task_id.set(task_id)
    try:
        yield
    finally:
        _claimed_task_id.reset(token)


class GenerationTaskConflict(Exception):
    pass


class GenerationTaskRetryUnavailable(Exception):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _retry_payload(
    task_type: str,
    prompt: str,
    quality_mode: str,
    input_paths: list[str],
    request_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if request_payload is not None:
        return request_payload
    quality = quality_mode or "fast"
    if task_type == "text_to_3d" and prompt:
        return {"prompt": prompt, "quality_mode": quality}
    if task_type == "image_to_3d" and input_paths:
        return {"image_path": input_paths[0], "quality_mode": quality}
    if task_type == "fusion_to_3d" and len(input_paths) >= 2:
        return {"image1_path": input_paths[0], "image2_path": input_paths[1], "prompt": prompt, "quality_mode": quality}
    if task_type == "multiview_to_3d" and input_paths:
        return {"image_paths": input_paths, "quality_mode": quality}
    if task_type == "improve_image" and input_paths and prompt:
        return {"image_path": input_paths[0], "improvement_prompt": prompt, "quality_mode": quality}
    if task_type == "generate_image" and prompt:
        return {"prompt": prompt, "quality_mode": quality}
    if task_type == "generate_multiview_images" and input_paths:
        return {"image_path": input_paths[0], "prompt": prompt, "quality_mode": quality}
    if task_type == "generate_video" and prompt:
        return {"image_path": input_paths[0] if input_paths else None, "prompt": prompt, "quality_mode": quality}
    return {}


async def create_generation_task(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    status: str = "queued",
    conversation_id: str | None = None,
    queue_position: int | None = None,
    request_payload: dict[str, Any] | None = None,
    retry_of_task_id: str | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    db = await get_db()
    now = now_iso()
    await db.execute(
        """
        INSERT INTO generation_tasks
        (id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, error_code, request_payload, retry_of_task_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '', '', ?, ?, ?, ?)
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
            json.dumps(_retry_payload(task_type, prompt, quality_mode, input_paths or [], request_payload), ensure_ascii=False),
            retry_of_task_id,
            now,
            now,
        ),
    )
    await db.commit()
    await _publish_task(task_id)
    return task_id


async def create_running_generation_task(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    conversation_id: str | None = None,
    queue_position: int | None = None,
    request_payload: dict[str, Any] | None = None,
    retry_of_task_id: str | None = None,
) -> str:
    claimed_task_id = _claimed_task_id.get()
    if claimed_task_id:
        changed = await update_generation_task(claimed_task_id, "running")
        if not changed:
            raise GenerationTaskConflict("Retry task is no longer queued")
        return claimed_task_id
    return await create_generation_task(
        task_type,
        prompt,
        quality_mode,
        input_paths,
        status="running",
        conversation_id=conversation_id,
        queue_position=queue_position,
        request_payload=request_payload,
        retry_of_task_id=retry_of_task_id,
    )


def create_generation_task_sync(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
    status: str = "queued",
    conversation_id: str | None = None,
    queue_position: int | None = None,
    request_payload: dict[str, Any] | None = None,
    retry_of_task_id: str | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    now = now_iso()
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            INSERT INTO generation_tasks
            (id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, error_code, request_payload, retry_of_task_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '', '', ?, ?, ?, ?)
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
                json.dumps(_retry_payload(task_type, prompt, quality_mode, input_paths or [], request_payload), ensure_ascii=False),
                retry_of_task_id,
                now,
                now,
            ),
        )
        conn.commit()
    task = _get_generation_task_sync(task_id)
    if task:
        generation_event_broker.publish_nowait(task)
    return task_id


async def update_generation_task(
    task_id: str | None,
    status: str,
    output_paths: dict | None = None,
    error: str = "",
    queue_position: int | None = None,
) -> bool:
    if not task_id:
        return False
    sources = TRANSITION_SOURCES.get(status)
    if not sources:
        return False
    db = await get_db()
    now = now_iso()
    completed_at = now if status in TERMINAL_STATUSES else None
    placeholders = ", ".join("?" for _ in sources)
    cursor = await db.execute(
        f"""
        UPDATE generation_tasks
        SET status = ?,
            output_paths = ?,
            error = ?,
            queue_position = COALESCE(?, queue_position),
            updated_at = ?,
            completed_at = ?
        WHERE id = ? AND status IN ({placeholders})
        """,
        (
            status,
            json.dumps(output_paths or {}, ensure_ascii=False),
            error or "",
            queue_position,
            now,
            completed_at,
            task_id,
            *sources,
        ),
    )
    await db.commit()
    changed = bool(cursor.rowcount)
    if changed:
        await _publish_task(task_id)
    return changed


def update_generation_task_sync(
    task_id: str | None,
    status: str,
    output_paths: dict | None = None,
    error: str = "",
    queue_position: int | None = None,
) -> None:
    if not task_id:
        return
    sources = TRANSITION_SOURCES.get(status)
    if not sources:
        return
    now = now_iso()
    completed_at = now if status in TERMINAL_STATUSES else None
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        placeholders = ", ".join("?" for _ in sources)
        conn.execute(
            f"""
            UPDATE generation_tasks
            SET status = ?,
                output_paths = ?,
                error = ?,
                queue_position = COALESCE(?, queue_position),
                updated_at = ?,
                completed_at = ?
            WHERE id = ? AND status IN ({placeholders})
            """,
            (
                status,
                json.dumps(output_paths or {}, ensure_ascii=False),
                error or "",
                queue_position,
                now,
                completed_at,
                task_id,
                *sources,
            ),
        )
        conn.commit()
    task = _get_generation_task_sync(task_id)
    if task:
        generation_event_broker.publish_nowait(task)


async def cancel_running_generation_tasks(error: str = "User cancelled generation") -> None:
    db = await get_db()
    now = now_iso()
    rows = await db.execute_fetchall("SELECT id FROM generation_tasks WHERE status = 'running'")
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
    for row in rows:
        await _publish_task(row["id"])


async def get_generation_task(task_id: str) -> dict[str, Any] | None:
    db = await get_db()
    row = await db.execute_fetchall(
        """
        SELECT id, task_type, status, conversation_id, queue_position, prompt, quality_mode,
               input_paths, output_paths, error, error_code, request_payload, retry_of_task_id,
               created_at, updated_at, completed_at
        FROM generation_tasks
        WHERE id = ?
        """,
        (task_id,),
    )
    return generation_task_row_to_dict(row[0]) if row else None


async def _publish_task(task_id: str) -> None:
    task = await get_generation_task(task_id)
    if task:
        await generation_event_broker.publish(task)


def _get_generation_task_sync(task_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, task_type, status, conversation_id, queue_position, prompt, quality_mode,
                   input_paths, output_paths, error, error_code, request_payload, retry_of_task_id,
                   created_at, updated_at, completed_at
            FROM generation_tasks WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
    return generation_task_row_to_dict(row) if row else None


async def cancel_generation_task(
    task_id: str,
    error: str = "User cancelled generation",
) -> dict[str, Any] | None:
    changed = await update_generation_task(task_id, "cancelled", {}, error)
    if not changed:
        return await get_generation_task(task_id)
    return await get_generation_task(task_id)


async def retry_generation_task(task_id: str) -> dict[str, Any] | None:
    original = await get_generation_task(task_id)
    if not original:
        return None
    if original["status"] not in TERMINAL_STATUSES:
        raise GenerationTaskConflict("Only terminal tasks can be retried")
    if not original["requestPayload"]:
        raise GenerationTaskRetryUnavailable("retry_payload_missing")
    retry_id = await create_generation_task(
        original["taskType"],
        original["prompt"],
        original["qualityMode"],
        original["inputPaths"],
        conversation_id=original["conversationId"],
        request_payload=original["requestPayload"],
        retry_of_task_id=task_id,
    )
    return await get_generation_task(retry_id)


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
            error_code = CASE
                WHEN status = 'queued' THEN 'sidecar_restarted_before_start'
                ELSE 'sidecar_restarted'
            END,
            updated_at = ?,
            completed_at = ?
        WHERE status IN ('queued', 'running')
        """,
        (error, now, now),
    )
    await db.commit()
    rows = await db.execute_fetchall(
        "SELECT id FROM generation_tasks WHERE error_code IN ('sidecar_restarted', 'sidecar_restarted_before_start') AND updated_at = ?",
        (now,),
    )
    for row in rows:
        await _publish_task(row["id"])
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
    try:
        request_payload = json.loads(row["request_payload"] or "{}")
    except Exception:
        request_payload = {}
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
        "errorCode": row["error_code"] or "",
        "requestPayload": request_payload,
        "retryOfTaskId": row["retry_of_task_id"],
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
               error_code, request_payload, retry_of_task_id,
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
