from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    permission_mode: str = "standard"


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any]
    capability: str = "general"

    @field_validator("parameters")
    @classmethod
    def require_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("tool parameters must use a JSON object schema")
        return value


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_call_id: str
    name: str
    content: Any
    is_error: bool = False


class AgentCompletion(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["completed", "confirmation_required", "failed", "max_turns"]
    content: str = ""
    tool_results: list[ToolResult] = Field(default_factory=list)
    metrics: dict[str, int | float | None] = Field(default_factory=dict)
