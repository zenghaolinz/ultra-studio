import os
import re
from dataclasses import dataclass
from pathlib import Path

from db.sqlite import get_db
from memory import stm as memory_stm
from services.chat_paths import DOCUMENT_EXTENSIONS, GENERATED_TEXT_EXTENSIONS, IMAGE_EXTENSIONS


MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}

ARTIFACT_PATTERN = re.compile(
    r'\[Artifact:\s*kind="([^"]+)"\s+path="([^"]+)"'
    r'(?:\s+label="([^"]*)")?'
    r'(?:\s+prompt="([^"]*)")?\]',
    re.IGNORECASE,
)
IMAGE_ASSET_PATTERN = re.compile(r'\[Image Asset:\s*path="([^"]+)"(?:\s+prompt="([^"]*)")?\]', re.IGNORECASE)
BACKTICK_PATH_PATTERN = re.compile(r"`([^`]+)`")
WINDOWS_PATH_PATTERN = re.compile(r"([A-Za-z]:[\\/][^\s`\"'，。；;]+)")

PROMPT_PATTERNS = [
    re.compile(r"使用提示词[:：]?\s*`([^`]+)`"),
    re.compile(r'source_prompt["\']?\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'prompt["\']?\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE),
]

ORDINAL_TOKENS = {
    "第一": 0,
    "第1": 0,
    "1st": 0,
    "first": 0,
    "第二": 1,
    "第2": 1,
    "2nd": 1,
    "second": 1,
    "第三": 2,
    "第3": 2,
    "3rd": 2,
    "third": 2,
    "第四": 3,
    "第4": 3,
    "4th": 3,
    "fourth": 3,
}

KIND_HINTS = {
    "image": ["图片", "图像", "照片", "图", "image", "photo", "picture"],
    "document": ["文档", "pdf", "docx", "word", "document"],
    "code": ["代码", "脚本", "源码", "html", "css", "js", "ts", "python", "json", "code", "script"],
    "text": ["文本", "txt", "md", "markdown", "text"],
    "model": ["3d", "模型", "model", "glb", "gltf"],
    "video": ["视频", "影片", "video", "mp4", "mov"],
    "file": ["文件", "file"],
}

SEMANTIC_GROUPS = [
    ["黄色", "黄", "yellow"],
    ["白色", "白", "white"],
    ["黑色", "黑", "black"],
    ["棕色", "棕", "brown"],
    ["红色", "红", "red"],
    ["蓝色", "蓝", "blue"],
    ["绿色", "绿", "green"],
    ["狗", "小狗", "dog", "puppy"],
    ["猫", "小猫", "cat", "kitten"],
    ["兔", "兔子", "rabbit", "bunny"],
    ["html", ".html"],
    ["markdown", ".md", "md"],
    ["json", ".json"],
    ["python", ".py", "py"],
    ["word", ".docx", "docx"],
    ["pdf", ".pdf"],
]


@dataclass
class Artifact:
    kind: str
    path: str
    label: str = ""
    prompt: str = ""
    context: str = ""


def artifact_kind_for_path(path: str) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in MODEL_EXTENSIONS:
        return "model"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in {".pdf", ".docx"}:
        return "document"
    if ext in GENERATED_TEXT_EXTENSIONS:
        return "code" if ext in {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".rs"} else "text"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "file"


def _row_content(row) -> str:
    if isinstance(row, dict):
        return row.get("content") or ""
    if isinstance(row, (tuple, list)):
        return row[0] or ""
    return ""


def _extract_prompt(content: str) -> str:
    for pattern in PROMPT_PATTERNS:
        match = pattern.search(content or "")
        if match:
            return match.group(1).strip()
    return ""


def _normalize_existing_path(path_text: str) -> str | None:
    candidate = (path_text or "").strip().strip("`\"'")
    if not candidate:
        return None
    try:
        path = os.path.normpath(candidate)
    except (TypeError, ValueError):
        return None
    if os.path.splitext(path)[1].lower() not in (
        IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | GENERATED_TEXT_EXTENSIONS | MODEL_EXTENSIONS | VIDEO_EXTENSIONS
    ):
        return None
    if not os.path.exists(path):
        return None
    return path


def _dedupe(artifacts: list[Artifact]) -> list[Artifact]:
    unique = []
    seen = set()
    for artifact in artifacts:
        key = artifact.path.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(artifact)
    return unique


def extract_artifacts_from_content(content: str) -> list[Artifact]:
    text = content or ""
    prompt = _extract_prompt(text)
    artifacts: list[Artifact] = []

    for match in ARTIFACT_PATTERN.finditer(text):
        path = _normalize_existing_path(match.group(2))
        if not path:
            continue
        artifacts.append(
            Artifact(
                kind=(match.group(1) or artifact_kind_for_path(path)).lower(),
                path=path,
                label=match.group(3) or "",
                prompt=match.group(4) or prompt,
                context=text,
            )
        )

    for match in IMAGE_ASSET_PATTERN.finditer(text):
        path = _normalize_existing_path(match.group(1))
        if path:
            artifacts.append(Artifact(kind="image", path=path, prompt=match.group(2) or prompt, context=text))

    for pattern in (BACKTICK_PATH_PATTERN, WINDOWS_PATH_PATTERN):
        for match in pattern.finditer(text):
            path = _normalize_existing_path(match.group(1))
            if path:
                artifacts.append(Artifact(kind=artifact_kind_for_path(path), path=path, prompt=prompt, context=text))

    return _dedupe(artifacts)


def artifact_context_line(artifact: Artifact) -> str:
    path = artifact.path.replace('"', '\\"')
    label = artifact.label.replace('"', '\\"')
    prompt = artifact.prompt.replace('"', '\\"')
    parts = [f'[Artifact: kind="{artifact.kind}" path="{path}"']
    if label:
        parts.append(f'label="{label}"')
    if prompt:
        parts.append(f'prompt="{prompt}"')
    return " ".join(parts) + "]"


async def inject_artifacts_context(conversation_id: str, artifacts: list[Artifact]):
    payload = "\n".join(artifact_context_line(artifact) for artifact in _dedupe(artifacts))
    if payload:
        await memory_stm.inject_system_context(conversation_id, payload)


def _artifacts_from_result(result: dict, default_kind: str | None = None) -> list[Artifact]:
    if not isinstance(result, dict):
        return []
    artifacts: list[Artifact] = []
    prompt = str(result.get("source_prompt") or result.get("prompt") or "")
    path_fields = [
        "path",
        "image_path",
        "imagePath",
        "improved_image_path",
        "model_path",
        "modelPath",
        "video_path",
        "videoPath",
        "image_2d",
        "image2D",
        "front_path",
        "frontPath",
        "left_path",
        "leftPath",
        "back_path",
        "backPath",
        "source_image_path",
        "sourceImagePath",
        "image1_path",
        "image1Path",
        "image2_path",
        "image2Path",
        "backup_path",
    ]
    for field in path_fields:
        path = _normalize_existing_path(str(result.get(field) or ""))
        if path:
            artifacts.append(
                Artifact(kind=default_kind or artifact_kind_for_path(path), path=path, label=field, prompt=prompt)
            )
    for item in result.get("files") or []:
        if isinstance(item, dict):
            path = _normalize_existing_path(str(item.get("path") or ""))
            if path:
                artifacts.append(Artifact(kind=default_kind or artifact_kind_for_path(path), path=path, prompt=prompt))
    return _dedupe(artifacts)


async def inject_artifacts_from_result(conversation_id: str, result: dict, default_kind: str | None = None):
    await inject_artifacts_context(conversation_id, _artifacts_from_result(result, default_kind=default_kind))


async def list_recent_artifacts(
    conversation_id: str,
    kinds: set[str] | None = None,
    limit: int = 120,
) -> list[Artifact]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, limit),
    )
    artifacts: list[Artifact] = []
    seen = set()
    for row in rows:
        for artifact in extract_artifacts_from_content(_row_content(row)):
            if kinds and artifact.kind not in kinds:
                continue
            key = artifact.path.lower()
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(artifact)
    return artifacts


def _ordinal_index(text: str) -> int | None:
    lowered = (text or "").lower()
    for token, index in ORDINAL_TOKENS.items():
        if token.lower() in lowered:
            return index
    return None


def _requested_kinds(text: str) -> set[str]:
    lowered = (text or "").lower()
    kinds = set()
    for kind, tokens in KIND_HINTS.items():
        if any(token.lower() in lowered for token in tokens):
            kinds.add(kind)
    if "file" in kinds and len(kinds) == 1:
        kinds.update({"document", "code", "text", "model", "video", "image"})
    elif "file" in kinds:
        kinds.remove("file")
    return kinds


def _asset_match_score(artifact: Artifact, text: str) -> int:
    haystack = f"{artifact.kind}\n{artifact.label}\n{artifact.prompt}\n{artifact.context}\n{Path(artifact.path).name}\n{artifact.path}".lower()
    request = (text or "").lower()
    score = 0
    if artifact.kind in _requested_kinds(request):
        score += 2
    for group in SEMANTIC_GROUPS:
        if any(token.lower() in request for token in group) and any(token.lower() in haystack for token in group):
            score += 1
    for token in re.findall(r"[A-Za-z0-9_\-.]+", request):
        if len(token) >= 3 and token in haystack:
            score += 1
    return score


async def resolve_referenced_artifact(
    conversation_id: str,
    content: str,
    kinds: set[str] | None = None,
) -> Artifact | None:
    requested_kinds = kinds or _requested_kinds(content)
    artifacts = await list_recent_artifacts(conversation_id, kinds=requested_kinds or None)
    if not artifacts:
        return None

    index = _ordinal_index(content)
    if index is not None and index < len(artifacts):
        return artifacts[index]

    lowered = (content or "").lower()
    if any(token in lowered for token in ["最后", "最新", "刚才", "上一个", "previous", "latest", "last"]):
        return artifacts[-1]

    scored = [(artifact, _asset_match_score(artifact, content)) for artifact in artifacts]
    scored = [item for item in scored if item[1] > 0]
    if scored:
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[0][0]

    return artifacts[-1]
