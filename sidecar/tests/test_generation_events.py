import asyncio
import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from services.generation_events import GenerationEventBroker


class GenerationEventBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_delivers_snapshot_to_each_subscriber(self) -> None:
        broker = GenerationEventBroker(queue_size=2)
        first_id, first = broker.subscribe()
        second_id, second = broker.subscribe()

        await broker.publish({"id": "task-1", "status": "running"})

        self.assertEqual((await first.get())["task"]["id"], "task-1")
        self.assertEqual((await second.get())["task"]["status"], "running")
        broker.unsubscribe(first_id)
        broker.unsubscribe(second_id)

    async def test_unsubscribe_isolates_finished_listener(self) -> None:
        broker = GenerationEventBroker(queue_size=2)
        listener_id, queue = broker.subscribe()
        broker.unsubscribe(listener_id)

        await broker.publish({"id": "task-1"})

        self.assertTrue(queue.empty())

    async def test_overflow_replaces_stale_updates_with_resync_marker(self) -> None:
        broker = GenerationEventBroker(queue_size=1)
        _, queue = broker.subscribe()
        await broker.publish({"id": "task-1", "status": "queued"})

        await broker.publish({"id": "task-1", "status": "running"})

        self.assertEqual(await queue.get(), {"type": "resync"})


if __name__ == "__main__":
    unittest.main()
