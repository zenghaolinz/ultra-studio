import json
from typing import Any

from agent_runtime.events import RunEventEmitter
from agent_runtime.models import AgentRunRequest, ToolCall, ToolResult
from agent_runtime.policy import PermissionPolicy
from agent_runtime.tools import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        provider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        *,
        max_turns: int = 6,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.policy = policy
        self.max_turns = max(1, max_turns)

    async def stream(
        self,
        client,
        model_name: str,
        request: AgentRunRequest,
        capabilities: set[str],
    ):
        emitter = RunEventEmitter(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
        )
        messages = [dict(message) for message in request.messages]
        definitions = self.registry.definitions(capabilities)
        full_content = ""
        model_turns = 0
        tool_count = 0
        provider_signal_seen = False
        yield emitter.emit("run.started", {"adapter": "native_tools"})

        for turn in range(1, self.max_turns + 1):
            model_turns = turn
            emitter.metrics.mark_model_started()
            yield emitter.emit("model.started", {"turn": turn})
            calls: list[ToolCall] = []
            turn_text = ""
            finish_reason = None

            async for provider_event in self.provider.stream_turn(
                client,
                model_name,
                messages,
                definitions,
            ):
                if not provider_signal_seen:
                    emitter.metrics.mark_provider_signal()
                    provider_signal_seen = True
                if provider_event.type == "text_delta":
                    emitter.metrics.mark_visible_token()
                    turn_text += provider_event.text
                    full_content += provider_event.text
                    yield emitter.emit("text.delta", {"text": provider_event.text})
                elif provider_event.type == "tool_call" and provider_event.tool_call:
                    calls.append(provider_event.tool_call)
                elif provider_event.type == "finished":
                    finish_reason = provider_event.finish_reason

            yield emitter.emit(
                "model.finished",
                {"turn": turn, "finishReason": finish_reason, "toolCallCount": len(calls)},
            )

            if not calls:
                yield emitter.emit(
                    "run.finished",
                    {
                        "status": "completed",
                        "content": full_content,
                        "metrics": emitter.metrics.finish(
                            model_turns=model_turns,
                            tool_calls=tool_count,
                        ),
                    },
                )
                return

            messages.append(self._assistant_tool_message(turn_text, calls))
            for call in calls:
                decision = self.policy.decide(
                    call.name,
                    self.registry.risk(call.name),
                    request.permission_mode,
                )
                if decision == "ask":
                    yield emitter.emit(
                        "run.finished",
                        {
                            "status": "confirmation_required",
                            "content": full_content,
                            "toolCall": call.model_dump(),
                            "metrics": emitter.metrics.finish(
                                model_turns=model_turns,
                                tool_calls=tool_count,
                            ),
                        },
                    )
                    return

                tool_count += 1
                yield emitter.emit("tool.started", {"toolCall": call.model_dump()})
                if decision == "deny":
                    result = ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content="Tool execution denied by policy",
                        is_error=True,
                    )
                else:
                    try:
                        result = await self.registry.execute(call)
                    except Exception as exc:
                        result = ToolResult(
                            tool_call_id=call.id,
                            name=call.name,
                            content=str(exc),
                            is_error=True,
                        )
                yield emitter.emit(
                    "tool.finished",
                    {
                        "toolCallId": call.id,
                        "name": call.name,
                        "isError": result.is_error,
                    },
                )
                messages.append(self._tool_result_message(result))

        yield emitter.emit(
            "run.finished",
            {
                "status": "max_turns",
                "content": full_content,
                "metrics": emitter.metrics.finish(
                    model_turns=model_turns,
                    tool_calls=tool_count,
                ),
            },
        )

    @staticmethod
    def _assistant_tool_message(text: str, calls: list[ToolCall]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in calls
            ],
        }

    @staticmethod
    def _tool_result_message(result: ToolResult) -> dict[str, Any]:
        content = result.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return {
            "role": "tool",
            "tool_call_id": result.tool_call_id,
            "name": result.name,
            "content": content,
        }
