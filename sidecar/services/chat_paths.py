import os
import re
from difflib import SequenceMatcher
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOCUMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".rs",
    ".toml",
    ".ini",
    ".log",
    ".pdf",
    ".docx",
}

FOLDER_SUMMARY_EXTENSIONS = DOCUMENT_EXTENSIONS
GENERATED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".rs",
    ".toml",
    ".ini",
    ".log",
}

DOCX_PATH_PATTERN = re.compile(
    r"`([^`]+\.docx)`|([A-Za-z]:[\\/][^\s`\"'，。；;]+\.docx)",
    re.IGNORECASE,
)

TEXT_FILE_PATH_PATTERN = re.compile(
    r"`([^`]+\.(?:html?|css|jsx?|tsx?|py|txt|md|markdown|csv|json|jsonl|ya?ml|xml|rs|toml|ini|log))`"
    r"|([A-Za-z]:[\\/][^\s`\"'，。；;]+\.(?:html?|css|jsx?|tsx?|py|txt|md|markdown|csv|json|jsonl|ya?ml|xml|rs|toml|ini|log))",
    re.IGNORECASE,
)

LOCAL_PATH_PATTERN = re.compile(
    r"([A-Za-z]:[\\/][^\s`\"'，。；;]+|(?:Desktop|desktop|桌面)[\\/][^\s`\"'，。；;]+)"
)


def is_document_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in DOCUMENT_EXTENSIONS


def document_attachments(paths: list[str] | None) -> list[str]:
    return [path for path in paths or [] if is_document_path(path)]


def image_attachments(paths: list[str] | None) -> list[str]:
    return [
        path
        for path in paths or []
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]


def candidate_local_paths(content: str) -> list[str]:
    text = content or ""
    candidates: list[str] = []
    for pattern in [
        r"`([^`]+)`",
        r'"([^"]+)"',
        r"'([^']+)'",
        r"“([^”]+)”",
    ]:
        candidates.extend(match.strip() for match in re.findall(pattern, text) if match.strip())
    candidates.extend(match.group(1).strip() for match in LOCAL_PATH_PATTERN.finditer(text))

    seen = set()
    unique = []
    for item in candidates:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def resolve_local_path(path_text: str) -> Path:
    path = path_text.strip().strip("`\"'")
    lowered = path.lower().replace("\\", "/")
    if lowered == "desktop" or lowered == "桌面":
        return Path.home() / "Desktop"
    if lowered.startswith("desktop/") or lowered.startswith("桌面/"):
        _, rest = path.replace("\\", "/", 1).split("/", 1)
        return Path.home() / "Desktop" / rest
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def find_desktop_directory_by_mention(content: str) -> Path | None:
    text = content or ""
    lowered = text.lower()
    if "桌面" not in text and "desktop" not in lowered:
        return None

    desktop = Path.home() / "Desktop"
    if not desktop.exists() or not desktop.is_dir():
        return None

    matches: list[Path] = []
    compact_text = re.sub(r"\s+", "", lowered)
    try:
        children = list(desktop.iterdir())
    except OSError:
        return None

    for child in children:
        if not child.is_dir():
            continue
        name = child.name.lower()
        compact_name = re.sub(r"\s+", "", name)
        if name in lowered or compact_name in compact_text:
            matches.append(child)

    if not matches:
        return None
    return sorted(matches, key=lambda path: len(path.name), reverse=True)[0]


def nearby_path_suggestions(content: str, limit: int = 5) -> list[dict]:
    text = content or ""
    lowered = text.lower()
    roots = []
    if "桌面" in text or "desktop" in lowered:
        roots.append(Path.home() / "Desktop")
    roots.append(Path.cwd())

    seen_roots = set()
    items: list[tuple[float, Path]] = []
    compact_text = re.sub(r"\s+", "", lowered)
    for root in roots:
        try:
            root = root.resolve()
        except OSError:
            continue
        if str(root).lower() in seen_roots or not root.exists() or not root.is_dir():
            continue
        seen_roots.add(str(root).lower())
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name.lower()
            compact_name = re.sub(r"\s+", "", name)
            score = SequenceMatcher(None, compact_name, compact_text).ratio()
            if name in lowered or compact_name in compact_text:
                score += 1.0
            if child.is_dir():
                score += 0.08
            if score >= 0.18:
                items.append((score, child))

    items.sort(key=lambda item: item[0], reverse=True)
    suggestions = []
    seen_paths = set()
    for _, path in items:
        key = str(path).lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        suggestions.append({
            "name": path.name,
            "path": str(path),
            "type": "文件夹" if path.is_dir() else "文件",
        })
        if len(suggestions) >= limit:
            break
    return suggestions


def extract_directory_path(content: str) -> Path | None:
    for candidate in candidate_local_paths(content):
        try:
            path = resolve_local_path(candidate)
        except OSError:
            continue
        if path.exists() and path.is_dir():
            return path
    fuzzy_desktop = find_desktop_directory_by_mention(content)
    if fuzzy_desktop:
        return fuzzy_desktop
    return None


def format_path_resolution_card(query: str, suggestions: list[dict]) -> str:
    lines = [
        "[PATH_RESOLUTION_REQUIRED]",
        f"查询: {query}",
        "候选:",
    ]
    for item in suggestions:
        lines.append(f"- {item.get('type', '路径')}: `{item.get('path')}`")
    lines.append("[/PATH_RESOLUTION_REQUIRED]")
    return "\n".join(lines)
