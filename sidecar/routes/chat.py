import json

from fastapi import APIRouter, HTTPException

from routes.agent_runs import stream_agent_run
from schemas import ChatRequest

router = APIRouter()


@router.post("/send/stream")
async def send_message_stream(req: ChatRequest):
    """Compatibility URL for clients that have not moved to /api/agent/runs/stream."""
    return await stream_agent_run(req)


@router.post("/send")
async def send_message(req: ChatRequest):
    """Collect the agent event stream for legacy non-streaming clients."""
    response = await stream_agent_run(req)
    completion = None
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        for line in str(chunk).splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "run.finished":
                completion = event.get("data") or {}

    if completion is None:
        raise HTTPException(status_code=502, detail="Agent runtime ended without completion")
    if completion.get("status") not in {"completed", "confirmation_required"}:
        raise HTTPException(
            status_code=502,
            detail=f"Agent runtime stopped with status: {completion.get('status')}",
        )
    return {
        "id": completion.get("messageId"),
        "conversationId": req.conversation_id,
        "role": "assistant",
        "content": completion.get("content", ""),
        "createdAt": completion.get("createdAt", ""),
        "savedMemories": [],
    }
