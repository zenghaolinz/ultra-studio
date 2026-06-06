import datetime
import uuid
from typing import Any


def row_to_tool_event(row: Any) -> dict:
    return {
        "id": row["id"],
        "label": row["label"] or "",
        "detail": row["detail"] or "",
        "createdAt": row["created_at"],
    }


async def list_tool_events_for_messages(db, message_ids: list[str]) -> dict[str, list[dict]]:
    if not message_ids:
        return {}
    placeholders = ",".join("?" for _ in message_ids)
    rows = await db.execute_fetchall(
        f"""
        SELECT id, message_id, label, detail, created_at, position
        FROM message_tool_events
        WHERE message_id IN ({placeholders})
        ORDER BY message_id, position, created_at
        """,
        tuple(message_ids),
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["message_id"], []).append(row_to_tool_event(row))
    return grouped


async def replace_tool_events(
    db,
    conversation_id: str,
    message_id: str,
    events: list[dict],
) -> list[dict]:
    await db.execute(
        "DELETE FROM message_tool_events WHERE conversation_id = ? AND message_id = ?",
        (conversation_id, message_id),
    )
    normalized: list[dict] = []
    for index, event in enumerate(events):
        event_id = str(event.get("id") or uuid.uuid4().hex)
        label = str(event.get("label") or "").strip()
        if not label:
            continue
        detail = str(event.get("detail") or "")
        created_at = str(event.get("createdAt") or event.get("created_at") or datetime.datetime.utcnow().isoformat())
        await db.execute(
            """
            INSERT INTO message_tool_events
            (id, message_id, conversation_id, label, detail, created_at, position)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, message_id, conversation_id, label, detail, created_at, index),
        )
        normalized.append(
            {
                "id": event_id,
                "label": label,
                "detail": detail,
                "createdAt": created_at,
            }
        )
    await db.commit()
    return normalized
