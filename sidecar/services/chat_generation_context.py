import os
import re

from db.sqlite import get_db
from memory import stm as memory_stm
from services.chat_paths import IMAGE_EXTENSIONS


ASSET_IMAGE_PATTERNS = [
    re.compile(r'活跃生成图片路径="([^"]+)"'),
    re.compile(r'活跃图像路径="([^"]+)"'),
    re.compile(r'预览图:?\s*`([^`]+)`'),
    re.compile(r'生成图片\s*:\s*`([^`]+)`'),
    re.compile(r'编辑后图片\s*:\s*`([^`]+)`'),
    re.compile(r'image_2d["\']?\s*[:=]\s*["\']([^"\']+)["\']'),
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
        await memory_stm.inject_system_context(
            conversation_id,
            f'[System Context: 活跃图像路径="{image_path}"]',
        )


async def find_latest_edit_source_image(conversation_id: str) -> str | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT content FROM stm_entries WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 40",
        (conversation_id,),
    )

    for (content,) in rows:
        if not content:
            continue
        for pattern in ASSET_IMAGE_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            path = os.path.normpath(match.group(1))
            if os.path.exists(path):
                return path
    return None


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
