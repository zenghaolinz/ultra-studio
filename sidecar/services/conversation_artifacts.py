import uuid
import os
import sqlite3
from typing import Any

from db import sqlite as sqlite_db
from db.sqlite import get_db
from services.chat_paths import IMAGE_EXTENSIONS

MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}


def artifact_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "messageId": row["message_id"],
        "toolCallId": row["tool_call_id"],
        "generationTaskId": row["generation_task_id"],
        "kind": row["kind"],
        "source": row["source"],
        "path": row["path"],
        "prompt": row["prompt"] or "",
        "status": row["status"],
        "sequence": row["sequence"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def upsert_artifact(
    conversation_id: str,
    *,
    kind: str,
    source: str,
    path: str,
    message_id: str | None = None,
    tool_call_id: str | None = None,
    generation_task_id: str | None = None,
    prompt: str = "",
    status: str = "available",
    db=None,
) -> dict[str, Any]:
    connection = db or await get_db()
    artifact_id = uuid.uuid4().hex
    await connection.execute(
        """
        INSERT INTO conversation_artifacts(
            id, conversation_id, message_id, tool_call_id, generation_task_id,
            kind, source, path, prompt, status, sequence
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
               COALESCE(MAX(sequence), 0) + 1
        FROM conversation_artifacts
        WHERE conversation_id = ?
        ON CONFLICT(conversation_id, source, path) DO UPDATE SET
            message_id = COALESCE(excluded.message_id, message_id),
            tool_call_id = COALESCE(excluded.tool_call_id, tool_call_id),
            generation_task_id = COALESCE(excluded.generation_task_id, generation_task_id),
            prompt = CASE WHEN excluded.prompt != '' THEN excluded.prompt ELSE prompt END,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            artifact_id, conversation_id, message_id, tool_call_id,
            generation_task_id, kind, source, path, prompt, status,
            conversation_id,
        ),
    )
    await connection.commit()
    rows = await connection.execute_fetchall(
        """
        SELECT * FROM conversation_artifacts
        WHERE conversation_id = ? AND source = ? AND path = ?
        """,
        (conversation_id, source, path),
    )
    return artifact_row_to_dict(rows[0])


async def list_artifacts(
    conversation_id: str,
    *,
    kind: str | None = None,
    source: str | None = None,
    status: str = "available",
    db=None,
) -> list[dict[str, Any]]:
    connection = db or await get_db()
    clauses = ["conversation_id = ?", "status = ?"]
    parameters: list[Any] = [conversation_id, status]
    if kind:
        clauses.append("kind = ?")
        parameters.append(kind)
    if source:
        clauses.append("source = ?")
        parameters.append(source)
    rows = await connection.execute_fetchall(
        f"SELECT * FROM conversation_artifacts WHERE {' AND '.join(clauses)} ORDER BY sequence ASC",
        tuple(parameters),
    )
    return [artifact_row_to_dict(row) for row in rows]


async def record_uploaded_images(
    conversation_id: str,
    image_paths: list[str] | None,
    *,
    message_id: str | None,
    db=None,
) -> list[dict[str, Any]]:
    artifacts = []
    for path_text in image_paths or []:
        path = os.path.normpath(path_text)
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS or not os.path.isfile(path):
            continue
        artifacts.append(await upsert_artifact(
            conversation_id,
            kind="image",
            source="uploaded",
            path=path,
            message_id=message_id,
            db=db,
        ))
    return artifacts


def artifact_kind_for_path(path: str) -> str | None:
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in MODEL_EXTENSIONS:
        return "model"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return None


async def project_generation_outputs(
    conversation_id: str | None,
    *,
    generation_task_id: str,
    prompt: str,
    output_paths: dict[str, Any] | None,
    db=None,
) -> list[dict[str, Any]]:
    if not conversation_id:
        return []
    artifacts = []
    for value in (output_paths or {}).values():
        paths = value if isinstance(value, list) else [value]
        for path_text in paths:
            if not isinstance(path_text, str) or not path_text:
                continue
            path = os.path.normpath(path_text)
            kind = artifact_kind_for_path(path)
            if not kind:
                continue
            artifacts.append(await upsert_artifact(
                conversation_id,
                kind=kind,
                source="generated",
                path=path,
                generation_task_id=generation_task_id,
                prompt=prompt,
                db=db,
            ))
    return artifacts


def project_generation_outputs_sync(
    conversation_id: str | None,
    *,
    generation_task_id: str,
    prompt: str,
    output_paths: dict[str, Any] | None,
) -> None:
    if not conversation_id:
        return
    with sqlite3.connect(sqlite_db.DB_PATH, timeout=5) as connection:
        connection.execute("PRAGMA busy_timeout=5000")
        for value in (output_paths or {}).values():
            paths = value if isinstance(value, list) else [value]
            for path_text in paths:
                if not isinstance(path_text, str) or not path_text:
                    continue
                path = os.path.normpath(path_text)
                kind = artifact_kind_for_path(path)
                if not kind:
                    continue
                connection.execute(
                    """
                    INSERT INTO conversation_artifacts(
                        id, conversation_id, generation_task_id, kind, source,
                        path, prompt, status, sequence
                    )
                    SELECT ?, ?, ?, ?, 'generated', ?, ?, 'available',
                           COALESCE(MAX(sequence), 0) + 1
                    FROM conversation_artifacts
                    WHERE conversation_id = ?
                    ON CONFLICT(conversation_id, source, path) DO UPDATE SET
                        generation_task_id = excluded.generation_task_id,
                        prompt = CASE WHEN excluded.prompt != '' THEN excluded.prompt ELSE prompt END,
                        status = excluded.status,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        uuid.uuid4().hex, conversation_id, generation_task_id,
                        kind, path, prompt, conversation_id,
                    ),
                )
        connection.commit()
