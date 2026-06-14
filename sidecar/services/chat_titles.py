import asyncio

from schemas import ChatRequest
from services.chat_messages import utc_iso
from services.chat_provider_client import get_provider_client
from services.model_context import fit_messages_to_context

NEW_CONVERSATION_TITLE = "\u65b0\u5bf9\u8bdd"
TITLE_SYSTEM_PROMPT = (
    "\u7528\u4e0d\u8d85\u8fc78\u4e2a\u6c49\u5b57\u6982\u62ec\u4ee5\u4e0b"
    "\u5bf9\u8bdd\u7684\u4e3b\u9898\uff0c\u53ea\u8f93\u51fa\u6807\u9898\uff0c"
    "\u4e0d\u8981\u52a0\u5f15\u53f7\u6216\u5176\u4ed6\u7b26\u53f7\u3002"
)


def schedule_title_generation(db, req: ChatRequest):
    if not req.hidden_user_message:
        asyncio.create_task(maybe_generate_title(db, req.conversation_id, req.content))


async def maybe_generate_title(db, conversation_id: str, user_content: str, model_id: str | None = None):
    row = await db.execute_fetchall(
        "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not row or row[0][0] != NEW_CONVERSATION_TITLE:
        return

    client, provider_config = await get_provider_client(db, model_id)
    if not client:
        return

    try:
        response = await client.chat.completions.create(
            model=provider_config[1],
            messages=fit_messages_to_context([
                {
                    "role": "system",
                    "content": TITLE_SYSTEM_PROMPT,
                },
                {"role": "user", "content": user_content[:200]},
            ], provider_config),
            max_tokens=20,
        )
        title = response.choices[0].message.content.strip().strip('"').strip("'")
        if title:
            now = utc_iso()
            await db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            await db.commit()
    except Exception:
        pass
