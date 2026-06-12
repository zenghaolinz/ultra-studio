import json
from memory.json_store import (
    add_entry,
    remove_entry,
    update_entry,
    list_entries,
    search_entries,
    load_branch,
    increment_access,
)
from memory.schemas import LTMEntry


async def store_memory(
    content: str, branch_path: str = "个人/喜好偏好", tags: list[str] | None = None
) -> str:
    parts = branch_path.split("/", 1)
    if len(parts) != 2:
        domain, branch = "个人", "喜好偏好"
    else:
        domain, branch = parts
    entry_id = add_entry(domain, branch, content, tags)
    return entry_id


async def get_entry(entry_id: str, branch_path: str | None = None) -> LTMEntry | None:
    if branch_path:
        parts = branch_path.split("/", 1)
        if len(parts) != 2:
            return None
        domain, branch = parts
        data = load_branch(domain, branch)
        for e in data.get("entries", []):
            if e["id"] == entry_id:
                return _json_to_entry(e, domain, branch)
    return None


async def search_similar(
    query_text: str, branch_path: str = "", top_k: int = 5
) -> list[LTMEntry]:
    if branch_path:
        parts = branch_path.split("/", 1)
        if len(parts) == 2:
            domain, branch = parts
            results = search_entries(domain, branch, query_text)
            return [_json_to_entry(e, domain, branch) for e in results[:top_k]]
    return []


async def retrieve_by_paths(branch_paths: list[str], top_k: int = 5) -> list[LTMEntry]:
    all_entries: list[LTMEntry] = []
    for path in branch_paths:
        parts = path.split("/", 1)
        if len(parts) != 2:
            continue
        domain, branch = parts
        data = load_branch(domain, branch)
        for e in data.get("entries", []):
            all_entries.append(_json_to_entry(e, domain, branch))
    all_entries.sort(key=lambda x: x.updated_at, reverse=True)
    return all_entries[:top_k]


async def delete_entry(entry_id: str, branch_path: str) -> bool:
    parts = branch_path.split("/", 1)
    if len(parts) != 2:
        return False
    domain, branch = parts
    return remove_entry(domain, branch, entry_id)


async def increment_access_count(entry_id: str, branch_path: str):
    parts = branch_path.split("/", 1)
    if len(parts) != 2:
        return
    domain, branch = parts
    increment_access(domain, branch, entry_id)


async def get_all_entries(limit: int = 200) -> list[LTMEntry]:
    from memory.memory_map import load_map, get_all_branch_paths

    map_data = load_map()
    paths = get_all_branch_paths(map_data)
    all_entries: list[LTMEntry] = []
    for path in paths:
        parts = path.split("/", 1)
        if len(parts) != 2:
            continue
        domain, branch = parts
        data = load_branch(domain, branch)
        for e in data.get("entries", []):
            all_entries.append(_json_to_entry(e, domain, branch))
    all_entries.sort(key=lambda x: x.updated_at, reverse=True)
    return all_entries[:limit]


def _json_to_entry(e: dict, domain: str, branch: str) -> LTMEntry:
    return LTMEntry(
        id=e.get("id", ""),
        content=e.get("content", ""),
        domain=domain,
        branch=branch,
        tags=e.get("tags", []),
        access_count=e.get("access_count", 0),
        created_at=e.get("created_at", ""),
        updated_at=e.get("updated_at", ""),
    )
