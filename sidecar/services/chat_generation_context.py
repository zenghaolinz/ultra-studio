import os
import re
from dataclasses import dataclass

from db.sqlite import get_db
from memory import stm as memory_stm
from services.chat_paths import IMAGE_EXTENSIONS


ASSET_IMAGE_PATTERNS = [
    re.compile(r'\[Image Asset:\s*path="([^"]+)"(?:\s+prompt="([^"]*)")?\]'),
    re.compile(r'活跃生成图片路径="([^"]+)"'),
    re.compile(r'活跃图像路径="([^"]+)"'),
    re.compile(r'预览图:?\s*`([^`]+)`'),
    re.compile(r'生成图片\s*:\s*`([^`]+)`'),
    re.compile(r'编辑后图片\s*:\s*`([^`]+)`'),
    re.compile(r'image_2d["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
]

PROMPT_PATTERNS = [
    re.compile(r'使用提示词:\s*`([^`]+)`'),
    re.compile(r'source_prompt["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    re.compile(r'prompt["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
]

MULTIVIEW_CONTEXT_PATTERNS = {
    "front": [
        re.compile(r'活跃三视图正面="([^"]+)"'),
        re.compile(r'正面:\s*`([^`]+)`'),
        re.compile(r'front_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
    "left": [
        re.compile(r'活跃三视图左侧="([^"]+)"'),
        re.compile(r'左侧:\s*`([^`]+)`'),
        re.compile(r'left_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
    "back": [
        re.compile(r'活跃三视图背面="([^"]+)"'),
        re.compile(r'背面:\s*`([^`]+)`'),
        re.compile(r'back_path["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
    ],
}


@dataclass
class ImageAsset:
    path: str
    prompt: str = ""
    context: str = ""


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


def _extract_image_assets_from_content(content: str) -> list[ImageAsset]:
    prompt = _extract_prompt(content)
    assets = []
    seen = set()
    for pattern in ASSET_IMAGE_PATTERNS:
        for match in pattern.finditer(content or ""):
            path = os.path.normpath(match.group(1))
            if path.lower() in seen or not os.path.exists(path):
                continue
            seen.add(path.lower())
            inline_prompt = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else ""
            assets.append(ImageAsset(path=path, prompt=inline_prompt or prompt, context=content or ""))
    return assets


async def inject_request_image_context(conversation_id: str, image_paths: list[str] | None):
    paths = [
        os.path.normpath(path)
        for path in image_paths or []
        if path and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]
    if not paths:
        return
    await memory_stm.inject_system_context(
        conversation_id,
        "\n".join(f'[System Context: 活跃图像路径="{path}"]' for path in paths[:4]),
    )


async def inject_image_context(conversation_id: str, result: dict):
    if result.get("status") != "success":
        return
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if front and left and back:
        await memory_stm.inject_system_context(
            conversation_id,
            "\n".join([
                f'[System Context: 活跃三视图正面="{front}"]',
                f'[System Context: 活跃三视图左侧="{left}"]',
                f'[System Context: 活跃三视图背面="{back}"]',
            ]),
        )
        return
    image_path = result.get("image_path") or result.get("imagePath") or result.get("improved_image_path")
    if image_path:
        prompt = (result.get("source_prompt") or result.get("prompt") or "").replace('"', '\\"')
        await memory_stm.inject_system_context(
            conversation_id,
            "\n".join(
                [
                    f'[System Context: 活跃图像路径="{image_path}"]',
                    f'[Image Asset: path="{image_path}" prompt="{prompt}"]',
                ]
            ),
        )


async def find_latest_edit_source_image(conversation_id: str) -> str | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 40",
        (conversation_id,),
    )

    for row in rows:
        content = _row_content(row)
        if not content:
            continue
        assets = _extract_image_assets_from_content(content)
        if assets:
            return assets[0].path
    return None


async def list_recent_image_assets(conversation_id: str, limit: int = 80) -> list[ImageAsset]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, limit),
    )
    assets = []
    seen = set()
    for row in rows:
        for asset in _extract_image_assets_from_content(_row_content(row)):
            key = asset.path.lower()
            if key in seen:
                continue
            seen.add(key)
            assets.append(asset)
    return assets


def _ordinal_index(text: str) -> int | None:
    ordinal_map = {
        "第一": 0,
        "第1": 0,
        "1st": 0,
        "第二": 1,
        "第2": 1,
        "2nd": 1,
        "第三": 2,
        "第3": 2,
        "3rd": 2,
        "第四": 3,
        "第4": 3,
        "4th": 3,
    }
    lowered = (text or "").lower()
    for token, index in ordinal_map.items():
        if token.lower() in lowered:
            return index
    return None


def _asset_match_score(asset: ImageAsset, text: str) -> int:
    haystack = f"{asset.prompt}\n{asset.context}\n{asset.path}".lower()
    request = (text or "").lower()
    groups = [
        ["黄色", "yellow"],
        ["白色", "white"],
        ["黑色", "black"],
        ["棕色", "brown"],
        ["红色", "red"],
        ["蓝色", "blue"],
        ["绿色", "green"],
        ["狗", "小狗", "dog", "puppy"],
        ["猫", "小猫", "cat", "kitten"],
        ["兔", "兔子", "rabbit", "bunny"],
    ]
    score = 0
    for words in groups:
        if any(word in request for word in words) and any(word in haystack for word in words):
            score += 1
    return score


async def resolve_referenced_image_asset(conversation_id: str, content: str) -> str | None:
    assets = await list_recent_image_assets(conversation_id)
    if not assets:
        return None

    index = _ordinal_index(content)
    if index is not None and index < len(assets):
        return assets[index].path

    scored = [(asset, _asset_match_score(asset, content)) for asset in assets]
    scored = [item for item in scored if item[1] > 0]
    if scored:
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[0][0].path

    return assets[-1].path


async def find_latest_multiview_paths(conversation_id: str) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 60",
        (conversation_id,),
    )
    found = {"front": "", "left": "", "back": ""}
    for row in rows:
        content = row["content"] or ""
        for key, patterns in MULTIVIEW_CONTEXT_PATTERNS.items():
            if found[key]:
                continue
            for pattern in patterns:
                match = pattern.search(content)
                if not match:
                    continue
                path = os.path.normpath(match.group(1))
                if os.path.exists(path):
                    found[key] = path
                    break
        if all(found.values()):
            return found
    return None


async def inject_3d_context(conversation_id: str, result: dict):
    parts = []
    image_path = (
        result.get("source_image_path")
        or result.get("sourceImagePath")
        or result.get("image_2d")
        or result.get("image2D")
    )
    model_path = result.get("model_path") or result.get("modelPath")
    source1 = result.get("image1_path") or result.get("image1Path")
    source2 = result.get("image2_path") or result.get("image2Path")
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if image_path:
        parts.append(f'[System Context: 活跃生成图片路径="{image_path}"]')
    if model_path:
        parts.append(f'[System Context: 活跃模型路径="{model_path}"]')
    if source1:
        parts.append(f'[System Context: 活跃融合源图1="{source1}"]')
    if source2:
        parts.append(f'[System Context: 活跃融合源图2="{source2}"]')
    if front and left and back:
        parts.append(f'[System Context: 活跃三视图正面="{front}"]')
        parts.append(f'[System Context: 活跃三视图左侧="{left}"]')
        parts.append(f'[System Context: 活跃三视图背面="{back}"]')
    if parts:
        await memory_stm.inject_system_context(conversation_id, "\n".join(parts))
