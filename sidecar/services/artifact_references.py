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


def _available_images(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            artifact for artifact in artifacts
            if artifact.get("kind") == "image"
            and artifact.get("status", "available") == "available"
            and os.path.isfile(str(artifact.get("path") or ""))
        ],
        key=lambda artifact: int(artifact.get("sequence") or 0),
    )


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
    images = _available_images(artifacts)
    if not images:
        return []

    mentions_uploaded = _mentions_uploaded(text)
    mentions_generated = _mentions_generated(text)
    ordinal = _ordinal(text)

    if mentions_uploaded and mentions_generated:
        uploaded = [item for item in images if item.get("source") == "uploaded"]
        generated = [item for item in images if item.get("source") == "generated"]
        return ([uploaded[-1]] if uploaded else []) + ([generated[-1]] if generated else [])

    if mentions_uploaded or mentions_generated:
        source = "uploaded" if mentions_uploaded else "generated"
        candidates = [item for item in images if item.get("source") == source]
        if not candidates:
            return []
        if ordinal is not None:
            return [candidates[ordinal]] if ordinal < len(candidates) else []
        return [candidates[-1]]

    lowered = text.lower()
    if any(token in lowered for token in ["这两张", "两张图", "two images", "both images"]):
        return images[-2:] if len(images) >= 2 else images

    reference_tokens = [
        "上面", "这张图", "这个图", "那张图", "前面", "刚才", "之前的图",
        "above image", "this image", "that image", "previous image",
    ]
    if ordinal is not None and any(token in lowered for token in ["图", "image", "photo"]):
        return [images[ordinal]] if ordinal < len(images) else []
    if any(token in lowered for token in reference_tokens):
        return [images[-1]]
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
