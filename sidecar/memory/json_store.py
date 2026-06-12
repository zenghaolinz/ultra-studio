import json
import uuid
import os
import datetime

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "memory")


def _branch_path(domain: str, branch: str) -> str:
    return os.path.join(MEMORY_DIR, domain, f"{branch}.json")


def _ensure_branch_file(domain: str, branch: str):
    path = _branch_path(domain, branch)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "path": f"{domain}/{branch}",
            "updated_at": datetime.datetime.utcnow().isoformat(),
            "entries": [],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_branch(domain: str, branch: str) -> dict:
    path = _branch_path(domain, branch)
    if not os.path.exists(path):
        _ensure_branch_file(domain, branch)
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_branch(domain: str, branch: str, data: dict):
    path = _branch_path(domain, branch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["updated_at"] = datetime.datetime.utcnow().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_entry(
    domain: str, branch: str, content: str, tags: list[str] | None = None
) -> str:
    data = load_branch(domain, branch)
    entry_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    entry = {
        "id": entry_id,
        "content": content,
        "tags": tags or [],
        "created_at": now,
        "updated_at": now,
        "access_count": 0,
    }
    data["entries"].append(entry)
    save_branch(domain, branch, data)
    return entry_id


def remove_entry(domain: str, branch: str, entry_id: str) -> bool:
    data = load_branch(domain, branch)
    original_len = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]
    if len(data["entries"]) < original_len:
        save_branch(domain, branch, data)
        return True
    return False


def update_entry(
    domain: str,
    branch: str,
    entry_id: str,
    content: str | None = None,
    tags: list[str] | None = None,
) -> dict | None:
    data = load_branch(domain, branch)
    for entry in data["entries"]:
        if entry["id"] == entry_id:
            if content is not None:
                entry["content"] = content
            if tags is not None:
                entry["tags"] = tags
            entry["updated_at"] = datetime.datetime.utcnow().isoformat()
            save_branch(domain, branch, data)
            return entry
    return None


def list_entries(
    domain: str, branch: str, limit: int = 50, offset: int = 0
) -> list[dict]:
    data = load_branch(domain, branch)
    entries = data.get("entries", [])
    return entries[offset : offset + limit]


def search_entries(domain: str, branch: str, keyword: str) -> list[dict]:
    data = load_branch(domain, branch)
    keyword_lower = keyword.lower()
    results = []
    for entry in data.get("entries", []):
        if keyword_lower in entry.get("content", "").lower():
            results.append(entry)
            continue
        for tag in entry.get("tags", []):
            if keyword_lower in tag.lower():
                results.append(entry)
                break
    return results


def count_entries(branch_path: str) -> int:
    parts = branch_path.split("/")
    if len(parts) != 2:
        return 0
    domain, branch = parts
    path = _branch_path(domain, branch)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data.get("entries", []))
    except Exception:
        return 0


def increment_access(domain: str, branch: str, entry_id: str):
    data = load_branch(domain, branch)
    for entry in data.get("entries", []):
        if entry.get("id") == entry_id:
            entry["access_count"] = entry.get("access_count", 0) + 1
            entry["updated_at"] = datetime.datetime.utcnow().isoformat()
            save_branch(domain, branch, data)
            return
