import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from agent_runtime.models import AgentRunRequest
from routes import agent_runs
from schemas import ChatRequest


class FakeLoop:
    async def stream(self, client, model_name, request, capabilities):
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "text.delta",
            "sequence": 1,
            "timestamp": "now",
            "data": {"text": "hello"},
        }
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "run.finished",
            "sequence": 2,
            "timestamp": "now",
            "data": {"status": "completed", "content": "hello", "metrics": {"applicationTtftMs": 10}},
        }


class ConfirmationLoop:
    async def stream(self, client, model_name, request, capabilities):
        yield {
            "runId": request.run_id,
            "conversationId": request.conversation_id,
            "type": "run.finished",
            "sequence": 1,
            "timestamp": "now",
            "data": {
                "status": "confirmation_required",
                "content": "",
                "toolCall": {
                    "id": "call-1",
                    "name": "delete_file",
                    "arguments": {"target_path": "C:/tmp/a.txt", "target_type": "file"},
                },
                "metrics": {},
            },
        }


class AgentRunRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_request_combines_new_and_legacy_attachment_fields(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="read files",
            attachment_paths=["C:/docs/spec.pdf", "C:/images/ref.png"],
            image_paths=["C:/images/ref.png", "C:/legacy.txt"],
        )

        self.assertEqual(
            req.all_attachment_paths,
            ["C:/docs/spec.pdf", "C:/images/ref.png", "C:/legacy.txt"],
        )

    def test_active_runtime_has_no_global_memory_manager_dependency(self) -> None:
        self.assertFalse(hasattr(agent_runs, "memory_mgr"))

    def test_text_only_model_keeps_text_and_removes_image_parts(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "edit this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            },
        ]

        adapted = agent_runs._adapt_messages_for_model(messages, supports_vision=False)

        self.assertEqual(adapted[1]["content"], "edit this")
        self.assertEqual(messages[1]["content"][1]["type"], "image_url")

    async def test_mixed_image_reference_injects_both_sources(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            uploaded = Path(temp_dir) / "uploaded.png"
            generated = Path(temp_dir) / "generated.png"
            uploaded.write_bytes(b"image")
            generated.write_bytes(b"image")
            artifacts = [
                {"id": "u1", "kind": "image", "source": "uploaded", "path": str(uploaded), "status": "available", "sequence": 1, "prompt": ""},
                {"id": "g1", "kind": "image", "source": "generated", "path": str(generated), "status": "available", "sequence": 2, "prompt": "cube"},
            ]
            req = ChatRequest(
                conversation_id="conversation-1",
                content="把我上传的图片和之前生成的图片融合",
            )
            with patch.object(
                agent_runs, "backfill_generation_artifacts", AsyncMock()
            ), patch.object(
                agent_runs, "list_artifacts", AsyncMock(return_value=artifacts)
            ):
                context, resolved = await agent_runs._artifact_context_for_request(req, object())

        self.assertEqual([item["id"] for item in resolved], ["u1", "g1"])
        self.assertIn(str(uploaded), context)
        self.assertIn(str(generated), context)

    async def test_resolved_image_reference_enables_generation_capability(self) -> None:
        self.assertEqual(
            agent_runs._capabilities_for_tools([], has_resolved_images=True),
            {"generation"},
        )

    async def test_reference_resolution_backfills_historical_generation_tasks(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="修改之前生成的图片",
        )
        db = object()
        with patch.object(
            agent_runs, "backfill_generation_artifacts", AsyncMock()
        ) as backfill, patch.object(
            agent_runs, "list_artifacts", AsyncMock(return_value=[])
        ):
            await agent_runs._artifact_context_for_request(req, db)

        backfill.assert_awaited_once_with("conversation-1", db=db)

    async def test_request_uploads_are_registered_with_user_message(self) -> None:
        req = ChatRequest(
            conversation_id="conversation-1",
            content="edit this",
            image_paths=["C:/images/upload.png"],
        )
        db = object()
        with patch.object(
            agent_runs, "record_uploaded_artifacts", AsyncMock(return_value=[])
        ) as record:
            await agent_runs._register_request_uploads(req, "message-1", db)

        record.assert_awaited_once_with(
            "conversation-1",
            ["C:/images/upload.png"],
            message_id="message-1",
            db=db,
        )

    async def test_artifact_context_lists_all_kinds(self) -> None:
        req = ChatRequest(conversation_id="conversation-1", content="open this file")
        db = object()
        with patch.object(
            agent_runs, "backfill_generation_artifacts", AsyncMock()
        ), patch.object(
            agent_runs, "list_artifacts", AsyncMock(return_value=[])
        ) as list_all:
            await agent_runs._artifact_context_for_request(req, db)

        list_all.assert_awaited_once_with("conversation-1", db=db)

    async def test_successful_tool_output_is_projected_to_artifact_ledger(self) -> None:
        event = {
            "type": "tool.finished",
            "data": {
                "toolCallId": "call-1",
                "name": "write_many_files",
                "isError": False,
                "result": {"files": [{"path": "C:/output/main.py"}]},
            },
        }
        db = object()
        with patch.object(
            agent_runs, "record_tool_outputs", AsyncMock(return_value=[])
        ) as record:
            await agent_runs._project_tool_artifacts(event, "conversation-1", db)

        record.assert_awaited_once_with(
            "conversation-1",
            tool_call_id="call-1",
            tool_name="write_many_files",
            result={"files": [{"path": "C:/output/main.py"}]},
            db=db,
        )

    async def test_confirmation_event_is_formatted_and_persisted_for_existing_ui(self) -> None:
        runtime_request = AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "delete it"}],
        )
        prepared = (ConfirmationLoop(), object(), "model", runtime_request, {"files"}, object())
        with patch.object(agent_runs, "_prepare_run", AsyncMock(return_value=prepared)), patch.object(
            agent_runs,
            "save_assistant_message",
            AsyncMock(return_value=("message-1", "created")),
        ) as save_message:
            response = await agent_runs.stream_agent_run(
                ChatRequest(conversation_id="conversation-1", content="delete it")
            )
            chunks = [chunk async for chunk in response.body_iterator]

        payload = json.loads(chunks[-1].removeprefix("data: ").strip())
        self.assertIn("[CONFIRM_DELETE_REQUIRED]", payload["data"]["content"])
        self.assertEqual(payload["data"]["messageId"], "message-1")
        save_message.assert_awaited_once()

    async def test_capabilities_include_generation_only_when_context_offers_it(self) -> None:
        generation_tool = {
            "type": "function",
            "function": {"name": "generate_video", "parameters": {"type": "object"}},
        }

        self.assertEqual(
            agent_runs._capabilities_for_tools([generation_tool]),
            {"generation"},
        )
        self.assertEqual(agent_runs._capabilities_for_tools([]), set())

        mutation_tool = {
            "type": "function",
            "function": {"name": "edit_text_file", "parameters": {"type": "object"}},
        }
        self.assertEqual(
            agent_runs._capabilities_for_tools([mutation_tool]),
            {"files"},
        )

    async def test_route_streams_runtime_events_and_persists_completed_text(self) -> None:
        runtime_request = AgentRunRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "hi"}],
        )
        prepared = (FakeLoop(), object(), "model", runtime_request, {"files", "web"}, object())
        with patch.object(agent_runs, "_prepare_run", AsyncMock(return_value=prepared)), patch.object(
            agent_runs,
            "save_assistant_message",
            AsyncMock(return_value=("message-1", "created")),
        ) as save_message:
            response = await agent_runs.stream_agent_run(
                ChatRequest(conversation_id="conversation-1", content="hi")
            )
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertEqual(response.media_type, "text/event-stream")
        payloads = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]
        self.assertEqual(payloads[0]["type"], "text.delta")
        self.assertEqual(payloads[-1]["data"]["messageId"], "message-1")
        save_message.assert_awaited_once_with(prepared[-1], "conversation-1", "hello")


if __name__ == "__main__":
    unittest.main()
