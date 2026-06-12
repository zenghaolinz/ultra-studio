import uuid
import datetime

from db.sqlite import get_db


STM_WINDOW_SIZE = 20
CONSOLIDATE_CHUNK_SIZE = 5
OVERLAP_SIZE = 1


async def get_recent_entries(
    conversation_id: str, limit: int = STM_WINDOW_SIZE
) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, conversation_id, role, content, created_at FROM stm_entries "
        "WHERE conversation_id = ? AND (visible IS NULL OR visible = 1) "
        "ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [
        {
            "id": r[0],
            "conversationId": r[1],
            "role": r[2],
            "content": r[3],
            "createdAt": r[4],
        }
        for r in reversed(rows)
    ]


async def get_recent_all_entries(
    conversation_id: str, limit: int = STM_WINDOW_SIZE
) -> list[dict]:
    """Get recent entries including system context messages for LLM context building."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, conversation_id, role, content, created_at FROM stm_entries "
        "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [
        {
            "id": r[0],
            "conversationId": r[1],
            "role": r[2],
            "content": r[3],
            "createdAt": r[4],
        }
        for r in reversed(rows)
    ]


async def add_entry(conversation_id: str, role: str, content: str) -> str:
    db = await get_db()
    entry_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (entry_id, conversation_id, role, content, now),
    )
    await db.commit()
    return entry_id


async def inject_system_context(conversation_id: str, content: str):
    db = await get_db()
    entry_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at, visible) VALUES (?, ?, ?, ?, ?, ?)",
        (entry_id, conversation_id, "system", content, now, 0),
    )
    await db.commit()


async def get_stm_count(conversation_id: str) -> int:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT COUNT(*) FROM stm_entries WHERE conversation_id = ?",
        (conversation_id,),
    )
    return row[0][0]


async def get_oldest_chunk(
    conversation_id: str, chunk_size: int = CONSOLIDATE_CHUNK_SIZE
) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, conversation_id, role, content, created_at FROM stm_entries "
        "WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, chunk_size),
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


async def remove_entries(entry_ids: list[str]):
    db = await get_db()
    placeholders = ",".join("?" * len(entry_ids))
    await db.execute(f"DELETE FROM stm_entries WHERE id IN ({placeholders})", entry_ids)
    await db.commit()


async def remove_entry(entry_id: str):
    await remove_entries([entry_id])
