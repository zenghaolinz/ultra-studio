import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from db import sqlite as sqlite_db
from services import generation_tasks
from services.conversation_artifacts import (
    backfill_generation_artifacts,
    list_artifacts,
    project_generation_outputs,
    record_tool_outputs,
    record_uploaded_images,
)


class ArtifactProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "agent.db"
        with patch.object(sqlite_db, "DB_PATH", str(self.db_path)):
            await sqlite_db._migrate()
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self.db.execute(
            "INSERT INTO conversations(id, title) VALUES ('conversation-1', 'test')"
        )
        await self.db.commit()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_records_uploaded_images_with_message_provenance(self) -> None:
        first = Path(self.temp_dir.name) / "first.png"
        second = Path(self.temp_dir.name) / "second.jpg"
        ignored = Path(self.temp_dir.name) / "notes.txt"
        first.write_bytes(b"png")
        second.write_bytes(b"jpg")
        ignored.write_text("text", encoding="utf-8")

        await record_uploaded_images(
            "conversation-1",
            [str(first), str(ignored), str(second)],
            message_id="message-1",
            db=self.db,
        )
        artifacts = await list_artifacts("conversation-1", db=self.db)

        self.assertEqual([item["source"] for item in artifacts], ["uploaded", "uploaded"])
        self.assertEqual([item["messageId"] for item in artifacts], ["message-1", "message-1"])
        self.assertEqual([Path(item["path"]).name for item in artifacts], ["first.png", "second.jpg"])

    async def test_projects_generated_outputs_with_task_provenance(self) -> None:
        image = Path(self.temp_dir.name) / "generated.png"
        model = Path(self.temp_dir.name) / "model.glb"
        image.write_bytes(b"png")
        model.write_bytes(b"glb")

        await project_generation_outputs(
            "conversation-1",
            generation_task_id="task-1",
            prompt="blue cube",
            output_paths={"imagePath": str(image), "modelPath": str(model)},
            db=self.db,
        )
        artifacts = await list_artifacts("conversation-1", db=self.db)

        self.assertEqual([item["kind"] for item in artifacts], ["image", "model"])
        self.assertTrue(all(item["source"] == "generated" for item in artifacts))
        self.assertTrue(all(item["generationTaskId"] == "task-1" for item in artifacts))

    async def test_projects_written_files_from_tool_results(self) -> None:
        code = Path(self.temp_dir.name) / "main.py"
        document = Path(self.temp_dir.name) / "report.docx"
        code.write_text("print('ok')", encoding="utf-8")
        document.write_bytes(b"docx")

        projected = await record_tool_outputs(
            "conversation-1",
            tool_call_id="call-1",
            tool_name="write_many_files",
            result={
                "files": [{"path": str(code)}],
                "output": {"file_path": str(document)},
                "ignored_input": "not-a-path",
            },
            db=self.db,
        )

        self.assertEqual([item["kind"] for item in projected], ["code", "document"])
        self.assertTrue(all(item["source"] == "tool" for item in projected))
        self.assertTrue(all(item["toolCallId"] == "call-1" for item in projected))

    async def test_async_task_success_invokes_artifact_projection(self) -> None:
        with patch.object(generation_tasks, "get_db", AsyncMock(return_value=self.db)), patch.object(
            generation_tasks, "_publish_task", AsyncMock()
        ), patch.object(
            generation_tasks, "project_generation_outputs", AsyncMock()
        ) as project:
            task_id = await generation_tasks.create_generation_task(
                "generate_image", "blue cube", "fast",
                conversation_id="conversation-1",
            )
            changed = await generation_tasks.update_generation_task(
                task_id, "success", {"imagePath": "C:/output.png"}
            )

        self.assertTrue(changed)
        project.assert_awaited_once_with(
            "conversation-1",
            generation_task_id=task_id,
            prompt="blue cube",
            output_paths={"imagePath": "C:/output.png"},
            db=self.db,
        )

    async def test_sync_task_success_invokes_artifact_projection(self) -> None:
        with patch.object(generation_tasks, "DB_PATH", str(self.db_path)), patch.object(
            generation_tasks, "project_generation_outputs_sync"
        ) as project:
            task_id = generation_tasks.create_generation_task_sync(
                "generate_image", "blue cube", "fast", status="running",
                conversation_id="conversation-1",
            )
            generation_tasks.update_generation_task_sync(
                task_id, "success", {"imagePath": "C:/output.png"}
            )

        project.assert_called_once_with(
            "conversation-1",
            generation_task_id=task_id,
            prompt="blue cube",
            output_paths={"imagePath": "C:/output.png"},
        )

    async def test_backfills_existing_successful_generation_tasks(self) -> None:
        image = Path(self.temp_dir.name) / "historical.png"
        image.write_bytes(b"image")
        await self.db.execute(
            """
            INSERT INTO generation_tasks(
                id, task_type, status, conversation_id, prompt, output_paths
            ) VALUES (?, 'generate_image', 'success', ?, ?, ?)
            """,
            ("historical-task", "conversation-1", "old blue cube", json.dumps({"imagePath": str(image)})),
        )
        await self.db.commit()

        await backfill_generation_artifacts("conversation-1", db=self.db)
        await backfill_generation_artifacts("conversation-1", db=self.db)
        artifacts = await list_artifacts("conversation-1", db=self.db)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["generationTaskId"], "historical-task")


if __name__ == "__main__":
    unittest.main()
