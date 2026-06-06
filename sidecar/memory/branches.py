import json
from memory.memory_map import load_map, save_map, get_all_branch_paths
from memory.json_store import load_branch


class LTMManager:
    def __init__(self):
        pass

    async def store_memory(
        self,
        content: str,
        branch_path: str = "个人/偏好与习惯",
        tags: list[str] | None = None,
    ) -> str:
        from memory.ltm import store_memory as _store

        return await _store(content=content, branch_path=branch_path, tags=tags)

    async def search_similar(
        self, query: str, branch_path: str = "", top_k: int = 5
    ) -> list[dict]:
        from memory.ltm import search_similar as _search

        results = await _search(query_text=query, branch_path=branch_path, top_k=top_k)
        return [
            {
                "id": e.id,
                "content": e.content,
                "tags": e.tags,
                "branchPath": e.branch_path,
                "createdAt": e.created_at,
            }
            for e in results
        ]


async def create_branch(domain: str, name: str, description: str = "") -> str:
    map_data = load_map()
    if domain not in map_data:
        map_data[domain] = {"description": description or domain, "branches": [name]}
    else:
        if name not in map_data[domain]["branches"]:
            map_data[domain]["branches"].append(name)
    save_map(map_data)

    from memory.json_store import _ensure_branch_file

    _ensure_branch_file(domain, name)

    return f"{domain}/{name}"


async def list_branches() -> list[dict]:
    map_data = load_map()
    result = []
    for domain, info in map_data.items():
        for branch in info.get("branches", []):
            data = load_branch(domain, branch)
            result.append(
                {
                    "id": f"{domain}/{branch}",
                    "name": branch,
                    "domain": domain,
                    "description": info.get("description", ""),
                    "parentId": None,
                    "entryCount": len(data.get("entries", [])),
                }
            )
    return result
