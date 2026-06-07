import datetime
import uuid
from typing import Any


async def save_user_message(db, conversation_id: str, content: str):
    user_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, conversation_id, "user", content, now),
    )
    await db.commit()
    return user_id


async def save_visible_user_message(db, req: Any):
    if req.hidden_user_message:
        return None
    return await save_user_message(db, req.conversation_id, req.content)


async def remove_internal_source_message(db, req: Any):
    if not req.remove_message_id:
        return
    await db.execute(
        "DELETE FROM stm_entries WHERE id = ? AND conversation_id = ? AND role = 'assistant'",
        (req.remove_message_id, req.conversation_id),
    )
    await db.commit()


async def save_assistant_message(db, conversation_id: str, content: str):
    assistant_id = uuid.uuid4().hex
    assistant_now = datetime.datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO stm_entries (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (assistant_id, conversation_id, "assistant", content, assistant_now),
    )
    await db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (assistant_now, conversation_id),
    )
    await db.commit()
    return assistant_id, assistant_now
