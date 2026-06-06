from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tools.comfyui_manager import (
    get_status,
    list_comfyui_profiles,
    save_comfyui_profile,
    select_comfyui_profile,
    start_comfyui,
    stop_comfyui,
)

router = APIRouter()


class ComfyUiProfileSave(BaseModel):
    id: str | None = None
    name: str
    path: str
    select: bool = True


class ComfyUiProfileSelect(BaseModel):
    id: str


@router.get("/status")
async def comfyui_status():
    try:
        return get_status()
    except Exception as e:
        return {"error": str(e)}


@router.get("/profiles")
async def comfyui_profiles():
    return {"profiles": list_comfyui_profiles(), "status": get_status()}


@router.post("/profiles")
async def save_profile(req: ComfyUiProfileSave):
    profile = save_comfyui_profile(req.name, req.path, req.id, req.select)
    return {"profile": profile, "profiles": list_comfyui_profiles(), "status": get_status()}


@router.put("/profiles/select")
async def select_profile(req: ComfyUiProfileSelect):
    profile = select_comfyui_profile(req.id)
    if not profile:
        raise HTTPException(status_code=404, detail="ComfyUI profile not found")
    return {"profile": profile, "profiles": list_comfyui_profiles(), "status": get_status()}


@router.post("/start")
async def comfyui_start():
    try:
        ok = start_comfyui()
        return {"started": ok, **get_status()}
    except Exception as e:
        return {"error": str(e), **get_status()}


@router.post("/stop")
async def comfyui_stop():
    try:
        stop_comfyui()
        return {"stopped": True, **get_status()}
    except Exception as e:
        return {"error": str(e), **get_status()}
