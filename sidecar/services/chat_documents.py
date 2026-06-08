from pathlib import Path

from memory import manager as memory_mgr
from services.chat_paths import FOLDER_SUMMARY_EXTENSIONS


def folder_documents(folder: Path, recursive: bool = False, limit: int = 12) -> list[Path]:
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    docs = []
    for item in iterator:
        if len(docs) >= limit:
            break
        if not item.is_file():
            continue
        if item.suffix.lower() in FOLDER_SUMMARY_EXTENSIONS:
            docs.append(item)
    return docs


def read_document_attachments(paths: list[str], max_chars: int = 16000) -> list[str]:
    sections: list[str] = []
    for path in paths[:4]:
        result = memory_mgr.handle_read_document(path, max_chars)
        if not result.get("ok"):
            sections.append(f"[{path}]\n读取失败: {result.get('error', 'unknown error')}")
            continue
        sections.append(f"[{result.get('name') or path}]\n{result.get('content', '')}")
    return sections
