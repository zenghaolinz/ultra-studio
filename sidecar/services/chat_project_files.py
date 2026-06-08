import re
from difflib import SequenceMatcher
from pathlib import Path

from services.chat_paths import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS


def project_document_paths(project_path: str, content: str) -> list[str]:
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        iterator = root.rglob("*")
        scanned = 0
        for path in iterator:
            scanned += 1
            if scanned > 1200:
                break
            if len(candidates) > 80:
                break
            if not path.is_file() or path.suffix.lower() not in DOCUMENT_EXTENSIONS:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if "文本文档" in text and path.suffix.lower() == ".txt":
                score += 0.9
            if "新建" in text and "新建" in stem:
                score += 0.7
            if "要求" in text:
                score += 0.15
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return []
    if candidates[0][0] < 0.18 and len(candidates) > 1:
        return []
    if candidates[0][0] >= 1.0:
        return [str(candidates[0][1])]
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] >= 0.35:
        return [str(candidates[0][1])]
    return [str(path) for _, path in candidates[:3]]


def project_image_paths(project_path: str | None, content: str, limit: int = 5) -> list[str]:
    if not project_path:
        return []
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        scanned = 0
        for path in root.rglob("*"):
            scanned += 1
            if scanned > 1200:
                break
            if len(candidates) > 80:
                break
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = 0.2
            score += SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if any(word in text for word in ["文件夹", "项目", "目录", "folder"]):
                score += 0.25
            if any(word in text for word in ["图片", "图像", "照片", "png", "jpg", "jpeg", "image"]):
                score += 0.25
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    return [str(path) for _, path in candidates[:limit]]


def project_file_candidates(project_path: str | None, content: str, limit: int = 20) -> list[dict]:
    if not project_path:
        return []
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        return []

    allowed = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS
    text = (content or "").lower()
    compact_text = re.sub(r"\s+", "", text)
    candidates: list[tuple[float, Path]] = []
    try:
        scanned = 0
        for path in root.rglob("*"):
            scanned += 1
            if scanned > 1600:
                break
            if len(candidates) > 200:
                break
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            compact_name = re.sub(r"\s+", "", name)
            compact_stem = re.sub(r"\s+", "", stem)
            score = SequenceMatcher(None, compact_stem, compact_text).ratio()
            if name in text or stem in text or compact_name in compact_text or compact_stem in compact_text:
                score += 2.0
            if path.suffix.lower() in IMAGE_EXTENSIONS and any(word in text for word in ["图片", "图像", "照片", "image"]):
                score += 0.5
            if path.suffix.lower() in DOCUMENT_EXTENSIONS and any(word in text for word in ["文档", "文本", "docx", "pdf", "txt", "要求"]):
                score += 0.5
            candidates.append((score, path))
    except OSError:
        return []

    candidates.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    result = []
    for _, path in candidates[:limit]:
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            kind = "image"
        elif suffix in {".pdf", ".docx", ".txt", ".md", ".markdown"}:
            kind = "document"
        else:
            kind = "file"
        result.append({
            "name": path.name,
            "path": str(path),
            "kind": kind,
            "extension": suffix,
        })
    return result
