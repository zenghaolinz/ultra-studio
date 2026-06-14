import base64
import os

from services.model_context import fit_messages_to_context


def image_url_part(path: str) -> dict | None:
    norm_path = os.path.normpath(path)
    if not os.path.exists(norm_path):
        return None
    ext = os.path.splitext(norm_path)[1].lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext)
    if not mime:
        return None
    try:
        with open(norm_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    except OSError:
        return None


async def build_visual_edit_prompt(
    client,
    model_name: str,
    source_path: str,
    user_request: str,
    capabilities: dict,
    provider_config=None,
) -> str:
    if not capabilities.get("supports_vision"):
        return user_request
    image_part = image_url_part(source_path)
    if not image_part:
        return user_request
    system_hint = (
        "你是图片编辑提示词生成器。请先理解输入图片内容，再结合用户要求，"
        "输出一条可直接交给图像编辑/重绘工作流的简洁提示词。"
        "必须保留原图主体、构图和风格，只修改用户要求的部分。只输出提示词本身。"
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=fit_messages_to_context([
                {"role": "system", "content": system_hint},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"用户要求：{user_request}"},
                        image_part,
                    ],
                },
            ], provider_config or ("", model_name, "", "", None)),
        )
        prompt = (response.choices[0].message.content or "").strip()
        return prompt or user_request
    except Exception as e:
        print(f"[router] visual prompt failed: {e}")
        return user_request
