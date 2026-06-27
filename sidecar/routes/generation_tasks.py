import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from services.generation_events import generation_event_broker
from services.generation_dispatcher import schedule_generation_task
from services.generation_tasks import (
    GenerationTaskConflict,
    GenerationTaskRetryUnavailable,
    cancel_generation_task,
    list_generation_tasks,
    retry_generation_task,
)

router = APIRouter(prefix="/api/generation/tasks", tags=["generation-tasks"])


@router.get("")
async def list_tasks(limit: int = 30):
    return await list_generation_tasks(limit)


@router.get("/events")
async def generation_task_events():
    async def stream():
        subscriber_id, queue = generation_event_broker.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            generation_event_broker.unsubscribe(subscriber_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = await cancel_generation_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Generation task not found")
    if task["status"] != "cancelled":
        raise HTTPException(status_code=409, detail="Generation task is already terminal")
    return task


@router.post("/{task_id}/retry")
async def retry_task(task_id: str):
    try:
        task = await retry_generation_task(task_id)
    except GenerationTaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GenerationTaskRetryUnavailable as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": "Task does not contain a retry payload"},
        ) from exc
    if not task:
        raise HTTPException(status_code=404, detail="Generation task not found")
    schedule_generation_task(task)
    return task
