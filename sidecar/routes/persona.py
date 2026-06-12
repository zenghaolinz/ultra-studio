import datetime
from fastapi import APIRouter, HTTPException
from db.sqlite import get_db

router = APIRouter()


@router.get("/persona")
async def get_persona():
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content, updated_at FROM persona WHERE id = 1"
    )
    if not rows:
        return {"content": "", "updatedAt": ""}
    return {"content": rows[0][0], "updatedAt": rows[0][1]}


@router.put("/persona")
async def update_persona(body: dict):
    content = body.get("content", "").strip()
    db = await get_db()
    now = datetime.datetime.utcnow().isoformat()
    rows = await db.execute_fetchall("SELECT id FROM persona WHERE id = 1")
    if rows:
        await db.execute(
            "UPDATE persona SET content = ?, updated_at = ? WHERE id = 1",
            (content, now),
        )
    else:
        await db.execute(
            "INSERT INTO persona (id, content, updated_at) VALUES (1, ?, ?)",
            (content, now),
        )
    await db.commit()
    return {"content": content, "updatedAt": now}
