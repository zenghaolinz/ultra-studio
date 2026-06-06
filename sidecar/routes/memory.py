import json
from fastapi import APIRouter
from memory import ltm
from memory.memory_map import load_map, get_all_branch_paths
from memory.json_store import load_branch, search_entries
from schemas import MemoryBranchCreate, MemoryRememberRequest

router = APIRouter()


@router.get("/branches")
async def list_branches():
    from memory.branches import list_branches as _list

    return await _list()


@router.post("/branches")
async def create_branch(req: MemoryBranchCreate):
    from memory.branches import create_branch as _create

    path = await _create(name=req.name, description=req.description, domain=req.domain)
    return {"id": path, "name": req.name, "description": req.description}


@router.post("/remember")
async def remember_explicitly(req: MemoryRememberRequest):
    entry_id = await ltm.store_memory(
        content=req.content,
        branch_path=req.branch_path,
        tags=req.tags,
    )
    return {
        "ok": True,
        "id": entry_id,
        "content": req.content,
        "branchPath": req.branch_path,
        "tags": req.tags,
    }


@router.get("/map")
async def get_memory_map():
    map_data = load_map()
    return map_data


@router.get("/stm/{conversation_id}")
async def get_stm_entries(conversation_id: str):
    from db.sqlite import get_db

    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, conversation_id, role, content, created_at FROM stm_entries WHERE conversation_id = ? ORDER BY created_at",
        (conversation_id,),
    )
    return [
        {
            "id": r[0],
            "conversationId": r[1],
            "role": r[2],
            "content": r[3],
            "createdAt": r[4],
        }
        for r in rows
    ]


@router.get("/ltm")
async def list_ltm_entries(
    domain: str | None = None, branch: str | None = None, limit: int = 200
):
    if domain and branch:
        data = load_branch(domain, branch)
        return data.get("entries", [])[:limit]
    from memory.ltm import get_all_entries

    entries = await get_all_entries(limit)
    return [
        {
            "id": e.id,
            "content": e.content,
            "domain": e.domain,
            "branch": e.branch,
            "branchPath": e.branch_path,
            "tags": e.tags,
            "accessCount": e.access_count,
            "createdAt": e.created_at,
            "updatedAt": e.updated_at,
        }
        for e in entries
    ]


@router.get("/ltm/{domain}/{branch}")
async def get_ltm_branch(domain: str, branch: str):
    data = load_branch(domain, branch)
    return data


@router.get("/ltm/{domain}/{branch}/search")
async def search_ltm_entries(domain: str, branch: str, q: str = ""):
    results = search_entries(domain, branch, q)
    return results


@router.delete("/ltm/{domain}/{branch}/{entry_id}")
async def delete_ltm_entry(domain: str, branch: str, entry_id: str):
    from memory.json_store import remove_entry

    success = remove_entry(domain, branch, entry_id)
    return {"ok": success}


@router.put("/ltm/{domain}/{branch}/{entry_id}")
async def update_ltm_entry(domain: str, branch: str, entry_id: str, body: dict):
    from memory.json_store import update_entry

    content = body.get("content")
    tags = body.get("tags")
    result = update_entry(domain, branch, entry_id, content=content, tags=tags)
    if result is None:
        return {"ok": False, "error": "Entry not found"}
    return {"ok": True, "entry": result}
