from memory.schemas import LTMEntry
from memory.json_store import load_branch
from memory.memory_map import load_map, get_all_branch_paths


def recall_branch(branch_path: str) -> list[dict]:
    parts = branch_path.split("/", 1)
    if len(parts) != 2:
        return []
    domain, branch = parts
    data = load_branch(domain, branch)
    return data.get("entries", [])


async def get_all_memories(limit: int = 200) -> list[LTMEntry]:
    from memory.ltm import get_all_entries

    return await get_all_entries(limit)


def get_memory_map() -> dict:
    return load_map()


def get_memory_stats() -> dict:
    from memory.memory_map import get_branch_stats

    return get_branch_stats()
