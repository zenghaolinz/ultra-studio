from typing import Literal, Optional

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    conversation_id: str = Field(min_length=1)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    image_paths: Optional[list[str]] = None
    permission_mode: str = "standard"
    project_path: Optional[str] = None
    model_id: Optional[str] = None
    vision_enabled: bool = False
    hidden_user_message: bool = False
    remove_message_id: Optional[str] = None


class ConversationCreate(BaseModel):
    title: str = "新对话"


    project_id: Optional[str] = None


class ProjectCreate(BaseModel):
    path: str = Field(min_length=1)
    name: Optional[str] = None


class ModelConfigCreate(BaseModel):
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    api_key: str = ""
    base_url: str = ""
    is_default: bool = False


class EmbeddingConfigCreate(BaseModel):
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    dimensions: int = Field(default=768, ge=1, le=4096)
    api_key: str = ""
    base_url: str = ""
    is_default: bool = False


class MemoryBranchCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    domain: str = "个人"


class MemoryRememberRequest(BaseModel):
    content: str = Field(min_length=1)
    branch_path: str = "个人/喜好偏好"
    tags: list[str] = Field(default_factory=list)
