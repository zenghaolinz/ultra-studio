import json
from dataclasses import dataclass
from typing import Any, Literal

from agent_runtime.models import ToolCall, ToolDefinition


class ProviderProtocolError(Exception):
    pass


@dataclass(frozen=True)
class ProviderEvent:
    type: Literal["text_delta", "tool_call", "finished"]
    text: str = ""
    tool_call: ToolCall | None = None
    finish_reason: str | None = None


class NativeToolProvider:
    async def stream_turn(
        self,
        client,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ):
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = [self._tool_payload(tool) for tool in tools]
            kwargs["tool_choice"] = "auto"
        stream = await client.chat.completions.create(**kwargs)
        pending_calls: dict[int, dict[str, str]] = {}
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if text:
                yield ProviderEvent(type="text_delta", text=text)
            for fragment in (getattr(delta, "tool_calls", None) if delta else None) or []:
                index = int(getattr(fragment, "index", 0) or 0)
                current = pending_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                current["id"] = getattr(fragment, "id", None) or current["id"]
                function = getattr(fragment, "function", None)
                if function:
                    current["name"] = getattr(function, "name", None) or current["name"]
                    current["arguments"] += getattr(function, "arguments", None) or ""
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                for index in sorted(pending_calls):
                    pending = pending_calls[index]
                    try:
                        arguments = json.loads(pending["arguments"] or "{}")
                    except json.JSONDecodeError as exc:
                        raise ProviderProtocolError("Tool arguments were not valid JSON") from exc
                    yield ProviderEvent(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=pending["id"] or f"tool-{index}",
                            name=pending["name"],
                            arguments=arguments,
                        ),
                    )
                yield ProviderEvent(type="finished", finish_reason=str(finish_reason))
                pending_calls.clear()

    @staticmethod
    def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
