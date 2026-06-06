from pydantic import BaseModel
from typing import Literal, Optional


class MessageCreate(BaseModel):
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    conversation_id: str
    content: str
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
    path: str
    name: Optional[str] = None


class ModelConfigCreate(BaseModel):
    provider: str
    model_name: str
    api_key: str = ""
    base_url: str = ""
    is_default: bool = False


class EmbeddingConfigCreate(BaseModel):
    provider: str
    model_name: str
    dimensions: int = 768
    api_key: str = ""
    base_url: str = ""
    is_default: bool = False


class MemoryBranchCreate(BaseModel):
    name: str
    description: str = ""
    domain: str = "个人"


class MemoryRememberRequest(BaseModel):
    content: str
    branch_path: str = "个人/喜好偏好"
    tags: list[str] = []
