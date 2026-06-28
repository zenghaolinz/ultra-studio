import os
from typing import Any


ORDINALS = {
    "第一": 0, "第1": 0, "first": 0, "1st": 0,
    "第二": 1, "第2": 1, "second": 1, "2nd": 1,
    "第三": 2, "第3": 2, "third": 2, "3rd": 2,
    "第四": 3, "第4": 3, "fourth": 3, "4th": 3,
}


def _ordinal(text: str) -> int | None:
    lowered = text.lower()
    for token, index in ORDINALS.items():
        if token in lowered:
            return index
    return None


def _available_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            artifact for artifact in artifacts
            if artifact.get("status", "available") == "available"
            and os.path.isfile(str(artifact.get("path") or ""))
        ],
        key=lambda artifact: int(artifact.get("sequence") or 0),
    )


KIND_TOKENS = [
    ("image", ["图片", "图像", "照片", "image", "photo", "picture"]),
    ("document", ["文档", "pdf", "word", "docx", "表格", "spreadsheet", "document"]),
    ("code", ["代码", "脚本", "源码", "code", "script", "source file"]),
    ("audio", ["音频", "录音", "声音", "audio", "voice", "sound"]),
    ("video", ["视频", "影片", "动画", "video", "movie", "animation"]),
    ("model", ["3d模型", "三维模型", "模型文件", "3d model", "mesh"]),
    ("archive", ["压缩包", "归档", "zip", "archive"]),
]


def _requested_kinds(text: str) -> list[str]:
    lowered = text.lower()
    return [kind for kind, tokens in KIND_TOKENS if any(token in lowered for token in tokens)]


def _mentions_uploaded(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ["上传", "我传", "uploaded", "upload image"])


def _mentions_generated(text: str) -> bool:
    lowered = text.lower()
    explicit = any(token in lowered for token in [
        "之前生成", "上次生成", "刚生成", "生成的图",
        "previously generated", "generated image",
    ])
    shorthand_reference = "生成图" in lowered and any(
        token in lowered for token in ["把", "使用", "修改", "融合", "和", "与"]
    )
    return explicit or shorthand_reference


def resolve_artifact_references(
    content: str,
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = content or ""
    available = _available_artifacts(artifacts)
    if not available:
        return []

    mentions_uploaded = _mentions_uploaded(text)
    mentions_generated = _mentions_generated(text)
    requested_kinds = _requested_kinds(text)
    ordinal = _ordinal(text)

    if mentions_uploaded and mentions_generated:
        candidates = [
            item for item in available
            if not requested_kinds or item.get("kind") in requested_kinds
        ]
        uploaded = [item for item in candidates if item.get("source") == "uploaded"]
        generated = [item for item in candidates if item.get("source") == "generated"]
        return ([uploaded[-1]] if uploaded else []) + ([generated[-1]] if generated else [])

    source = "uploaded" if mentions_uploaded else "generated" if mentions_generated else None
    candidates = [
        item for item in available
        if source is None or item.get("source") == source
    ]
    lowered = text.lower()
    has_reference_cue = any(token in lowered for token in [
        "这", "该", "上面", "前面", "刚才", "之前", "上次", "附件",
        "this", "that", "above", "previous", "last", "attachment",
    ])
    if requested_kinds and source is None and ordinal is None and not has_reference_cue:
        return []

    if len(requested_kinds) > 1:
        resolved = []
        for kind in requested_kinds:
            matches = [item for item in candidates if item.get("kind") == kind]
            if matches:
                resolved.append(matches[-1])
        return sorted(resolved, key=lambda item: int(item.get("sequence") or 0))

    if requested_kinds:
        candidates = [item for item in candidates if item.get("kind") == requested_kinds[0]]
        if not candidates:
            return []
        if ordinal is not None:
            return [candidates[ordinal]] if ordinal < len(candidates) else []
        return [candidates[-1]]

    if source is not None:
        if not candidates:
            return []
        if ordinal is not None:
            return [candidates[ordinal]] if ordinal < len(candidates) else []
        return [candidates[-1]]

    if any(token in lowered for token in ["这两张", "两张图", "two images", "both images"]):
        images = [item for item in available if item.get("kind") == "image"]
        return images[-2:] if len(images) >= 2 else images

    reference_tokens = [
        "上面", "这张图", "这个图", "那张图", "前面", "刚才", "之前的图",
        "above image", "this image", "that image", "previous image",
    ]
    if ordinal is not None and any(token in lowered for token in ["文件", "附件", "图", "file", "attachment", "image", "photo"]):
        return [available[ordinal]] if ordinal < len(available) else []
    if any(token in lowered for token in reference_tokens):
        return [available[-1]]
    if any(token in lowered for token in ["这个文件", "该文件", "这个附件", "上面的文件", "this file", "this attachment"]):
        return [available[-1]]
    return []


def build_artifact_context(
    resolved: list[dict[str, Any]],
    artifacts: list[dict[str, Any]] | None = None,
) -> str:
    if not resolved:
        return ""
    lines = [
        "[Resolved Artifacts]",
        "Use these exact local paths for tool arguments. Do not invent or swap paths.",
    ]
    for artifact in resolved:
        path = str(artifact.get("path") or "").replace('"', '\\"')
        prompt = str(artifact.get("prompt") or "").replace('"', '\\"')
        lines.append(
            f'[Resolved Artifact id="{artifact.get("id", "")}" '
            f'source="{artifact.get("source", "")}" kind="{artifact.get("kind", "")}" '
            f'sequence="{artifact.get("sequence", "")}" path="{path}" prompt="{prompt}"]'
        )
    lines.append("[/Resolved Artifacts]")
    return "\n".join(lines)
