import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_runtime.models import ToolCall, ToolDefinition, ToolResult


class UnknownToolError(Exception):
    pass


class ToolArgumentError(Exception):
    pass


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: Callable[[dict[str, Any]], Any]
    risk: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        executor: Callable[[dict[str, Any]], Any],
        *,
        risk: str,
    ) -> None:
        self._tools[definition.name] = RegisteredTool(definition, executor, risk)

    def definitions(self, capabilities: set[str] | None = None) -> list[ToolDefinition]:
        return [
            tool.definition
            for tool in self._tools.values()
            if capabilities is None or tool.definition.capability in capabilities
        ]

    def risk(self, tool_name: str) -> str:
        tool = self._tools.get(tool_name)
        if not tool:
            raise UnknownToolError(tool_name)
        return tool.risk

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if not tool:
            raise UnknownToolError(call.name)
        self._validate_arguments(tool.definition, call.arguments)
        result = tool.executor(call.arguments)
        if inspect.isawaitable(result):
            result = await result
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=result,
        )

    @staticmethod
    def _validate_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> None:
        schema = definition.parameters
        for name in schema.get("required", []):
            if name not in arguments:
                raise ToolArgumentError(f"Missing required argument: {name}")
        properties = schema.get("properties", {})
        type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
        for name, value in arguments.items():
            expected_name = properties.get(name, {}).get("type")
            expected_type = type_map.get(expected_name)
            if expected_type and not isinstance(value, expected_type):
                raise ToolArgumentError(f"Invalid type for argument: {name}")
