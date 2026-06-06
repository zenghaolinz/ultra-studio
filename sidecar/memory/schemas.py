from dataclasses import dataclass, field


@dataclass
class STMEntry:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


@dataclass
class LTMEntry:
    id: str
    content: str
    domain: str = ""
    branch: str = ""
    tags: list[str] = field(default_factory=list)
    access_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def branch_path(self) -> str:
        return f"{self.domain}/{self.branch}"


@dataclass
class ActivatedMemory:
    entries: list[LTMEntry] = field(default_factory=list)
    last_branch_paths: list[str] = field(default_factory=list)
    last_query: str = ""


@dataclass
class MemoryBranch:
    domain: str
    name: str
    description: str = ""
    created_at: str = ""
