import asyncio
import uuid
from typing import Any


class GenerationEventBroker:
    def __init__(self, queue_size: int = 64) -> None:
        self._queue_size = max(1, queue_size)
        self._subscribers: dict[
            str, tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]
        ] = {}

    def subscribe(self) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        subscriber_id = uuid.uuid4().hex
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._subscribers[subscriber_id] = (asyncio.get_running_loop(), queue)
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: str) -> None:
        self._subscribers.pop(subscriber_id, None)

    async def publish(self, task: dict[str, Any]) -> None:
        self.publish_nowait(task)

    def publish_nowait(self, task: dict[str, Any]) -> None:
        event = {"type": "task_updated", "task": task}
        for loop, queue in tuple(self._subscribers.values()):
            loop.call_soon_threadsafe(self._deliver, queue, event)

    @staticmethod
    def _deliver(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "resync"})
            return
        queue.put_nowait(event)


generation_event_broker = GenerationEventBroker()
