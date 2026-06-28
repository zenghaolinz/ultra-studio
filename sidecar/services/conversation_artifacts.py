import uuid
from typing import Any

from db.sqlite import get_db


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
