import time

from tools.comfyui_manager import (
    LAUNCH_MODE_EXTERNAL,
    get_status,
    is_valid_comfyui_path,
    start_comfyui,
)


GENERATION_TOOL_NAMES = {
    "generate_image",
    "edit_image",
    "modify_image_with_flux",
    "generate_multiview_images",
    "generate_multiview_images_from_image",
    "generate_3d_text",
    "generate_3d_image",
    "generate_3d_fusion",
    "generate_3d_multiview",
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_from_generated_multiview",
    "modify_previous_3d",
}

GENERATION_ACTIONS = {
    "generate_image",
    "edit_image",
    "generate_multiview_images",
    "generate_3d_text",
    "generate_3d_image",
    "generate_3d_fusion",
    "generate_3d_multiview",
    "project_document_image",
    "project_document_3d",
    "attachment_document_image",
    "attachment_document_3d",
}

COMFY_STARTING_STATUS = "ComfyUI 启动中/连接中"
COMFY_MANUAL_START_STATUS = "请先启动 ComfyUI"


def is_generation_tool(name: str | None) -> bool:
    return name in GENERATION_TOOL_NAMES


def is_generation_action(name: str | None) -> bool:
    return name in GENERATION_ACTIONS


def _manual_start_message(status: dict) -> str:
    launch_mode = status.get("launch_mode")
    configured_path = status.get("configured_path") or ""
    if launch_mode == LAUNCH_MODE_EXTERNAL:
        return "当前选择的是 ComfyUI Desktop/外部模式。请先手动启动 ComfyUI Desktop，并确认 127.0.0.1:8188 可访问后再试。"
    if not configured_path:
        return "尚未配置 ComfyUI。请在设置中添加 ComfyUI Portable 目录，或选择 Desktop/外部模式并手动启动 ComfyUI。"
    if not is_valid_comfyui_path(configured_path):
        return f"ComfyUI 路径无效：{configured_path}。请在设置中选择包含 main.py 或 ComfyUI/main.py 的目录。"
    return "ComfyUI 未启动。请先启动 ComfyUI，或在设置中选择可由应用启动的 Portable 版本。"


def ensure_comfyui_ready(auto_start: bool = True, wait_seconds: int = 120) -> dict:
    status = get_status()
    if status.get("running") or status.get("ready"):
        return {"ok": True, "status": status, "started": False}

    launch_mode = status.get("launch_mode")
    configured_path = status.get("configured_path") or ""
    if launch_mode == LAUNCH_MODE_EXTERNAL or not configured_path or not is_valid_comfyui_path(configured_path):
        return {"ok": False, "status": status, "message": _manual_start_message(status), "manual_start_required": True}

    if not auto_start:
        return {"ok": False, "status": status, "message": _manual_start_message(status), "manual_start_required": True}

    started = start_comfyui()
    if not started:
        next_status = get_status()
        return {"ok": False, "status": next_status, "message": _manual_start_message(next_status), "manual_start_required": True}

    deadline = time.time() + max(1, wait_seconds)
    while time.time() < deadline:
        next_status = get_status()
        if next_status.get("running") or next_status.get("ready"):
            return {"ok": True, "status": next_status, "started": True}
        time.sleep(1)

    return {
        "ok": False,
        "status": get_status(),
        "message": "ComfyUI 启动超时。请检查 ComfyUI 窗口或 sidecar/logs/comfyui-process.log。",
        "manual_start_required": True,
    }


def error_result(message: str) -> dict:
    return {"status": "error", "message": message, "manual_start_required": True}
