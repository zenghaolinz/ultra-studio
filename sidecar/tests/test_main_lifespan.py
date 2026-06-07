import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import main as sidecar_main


class MainLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_marks_interrupted_generation_tasks_on_startup(self) -> None:
        with patch.object(sidecar_main, "init_db", AsyncMock()) as init_db, patch.object(
            sidecar_main,
            "mark_interrupted_generation_tasks",
            AsyncMock(return_value=2),
        ) as mark_interrupted, patch.object(sidecar_main, "close_db", AsyncMock()) as close_db, patch(
            "tools.comfyui_manager.stop_comfyui"
        ):
            async with sidecar_main.lifespan(sidecar_main.app):
                pass

        init_db.assert_awaited_once()
        mark_interrupted.assert_awaited_once()
        close_db.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
