import os
import json
import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from db.sqlite import get_db
from tools.comfy_client import (
    run_pipeline,
    run_multiview_pipeline,
    improve_image_with_flux2klein,
    generate_multiview_images_with_flux,
    generate_image_with_flux,
    list_flux_image_loras,
    generate_video_with_wan,
    get_output_dir,
)

router = APIRouter(prefix="/api/3d", tags=["3d"])
executor = ThreadPoolExecutor(max_workers=2)


async def _create_task(
    task_type: str,
    prompt: str = "",
    quality_mode: str = "",
    input_paths: list[str] | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    await db.execute(
        """
        INSERT INTO generation_tasks
        (id, task_type, status, prompt, quality_mode, input_paths, output_paths, error, created_at, updated_at)
        VALUES (?, ?, 'running', ?, ?, ?, '{}', '', ?, ?)
        """,
        (
            task_id,
            task_type,
            prompt or "",
            quality_mode or "",
            json.dumps(input_paths or [], ensure_ascii=False),
            now,
            now,
        ),
    )
    await db.commit()
    return task_id


async def _update_task(
    task_id: str | None,
    status: str,
    output_paths: dict | None = None,
    error: str = "",
) -> None:
    if not task_id:
        return
    db = await get_db()
    current = await db.execute_fetchall(
        "SELECT status FROM generation_tasks WHERE id = ?",
        (task_id,),
    )
    if current and current[0]["status"] == "cancelled" and status != "cancelled":
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    completed_at = now if status in {"success", "error", "cancelled"} else None
    await db.execute(
        """
        UPDATE generation_tasks
        SET status = ?, output_paths = ?, error = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            status,
            json.dumps(output_paths or {}, ensure_ascii=False),
            error or "",
            now,
            completed_at,
            task_id,
        ),
    )
    await db.commit()


async def _cancel_running_tasks() -> None:
    db = await get_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    await db.execute(
        """
        UPDATE generation_tasks
        SET status = 'cancelled',
            error = 'User cancelled generation',
            updated_at = ?,
            completed_at = ?
        WHERE status = 'running'
        """,
        (now, now),
    )
    await db.commit()


def _task_row_to_dict(row) -> dict:
    try:
        input_paths = json.loads(row["input_paths"] or "[]")
    except Exception:
        input_paths = []
    try:
        output_paths = json.loads(row["output_paths"] or "{}")
    except Exception:
        output_paths = {}
    return {
        "id": row["id"],
        "taskType": row["task_type"],
        "status": row["status"],
        "prompt": row["prompt"] or "",
        "qualityMode": row["quality_mode"] or "",
        "inputPaths": input_paths,
        "outputPaths": output_paths,
        "error": row["error"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


@router.get("/tasks")
async def list_generation_tasks(limit: int = 30):
    db = await get_db()
    safe_limit = max(1, min(limit, 100))
    rows = await db.execute_fetchall(
        """
        SELECT id, task_type, status, prompt, quality_mode, input_paths, output_paths, error,
               created_at, updated_at, completed_at
        FROM generation_tasks
        ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    return [_task_row_to_dict(row) for row in rows]


def _make_sse_stream(mode, quality_mode, prompt, img1, img2=None):
    async def event_stream():
        task_type = {
            "Text to 3D": "text_to_3d",
            "Image to 3D": "image_to_3d",
            "Dual Image Fusion": "fusion_to_3d",
            "Hy3D MultiView": "multiview_to_3d",
        }.get(mode, "3d")
        task_id = await _create_task(
            task_type,
            prompt,
            quality_mode,
            [path for path in [img1, img2] if path],
        )
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def callback(data):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception:
                pass

        future = loop.run_in_executor(
            executor,
            lambda: run_pipeline(mode, quality_mode, prompt, img1, img2, callback),
        )
        last_heartbeat = time.time()

        while True:
            if future.done():
                while not queue.empty():
                    item = queue.get_nowait()
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                break

            try:
                data = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                if time.time() - last_heartbeat >= 15:
                    last_heartbeat = time.time()
                    yield f"data: {json.dumps({'type': 'status', 'description': '仍在生成中，模型加载或节点执行可能需要较长时间...'}, ensure_ascii=False)}\n\n"
                continue

        try:
            result_2d, result_normal, result_uv, model_path = future.result()
            status = "success" if model_path else "error"
            output_paths = {
                "modelPath": model_path,
                "image2D": result_2d,
                "imageNormal": result_normal,
                "imageUV": result_uv,
            }
            await _update_task(
                task_id,
                status,
                output_paths,
                "" if model_path else "Model file not found",
            )
            yield f"data: {json.dumps({
                'type': 'result',
                'taskId': task_id,
                'status': status,
                'modelPath': model_path,
                'image2D': result_2d,
                'imageNormal': result_normal,
                'imageUV': result_uv,
                'image1Path': img1,
                'image2Path': img2,
                'message': 'Generation completed' if model_path else 'Model file not found',
            }, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            await _update_task(task_id, "error", {}, str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _make_multiview_sse_stream(image_paths: list[str], quality_mode: str):
    async def event_stream():
        normalized_paths = _normalize_multiview_paths(image_paths)
        task_id = await _create_task(
            "multiview_to_3d",
            "Hy3D 多视角生成",
            quality_mode,
            [path for path in normalized_paths if path],
        )
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def callback(data):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception:
                pass

        future = loop.run_in_executor(
            executor,
            lambda: run_multiview_pipeline(normalized_paths, quality_mode, callback),
        )
        last_heartbeat = time.time()

        while True:
            if future.done():
                while not queue.empty():
                    item = queue.get_nowait()
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                break

            try:
                data = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                if time.time() - last_heartbeat >= 15:
                    last_heartbeat = time.time()
                    yield f"data: {json.dumps({'type': 'status', 'description': 'Hy3D 多视角仍在生成中，模型采样或纹理烘焙可能需要较长时间...'}, ensure_ascii=False)}\n\n"
                continue

        try:
            result_2d, result_normal, result_uv, model_path = future.result()
            status = "success" if model_path else "error"
            output_paths = {
                "modelPath": model_path,
                "image2D": result_2d,
                "imageNormal": result_normal,
                "imageUV": result_uv,
            }
            await _update_task(
                task_id,
                status,
                output_paths,
                "" if model_path else "Model file not found",
            )
            yield f"data: {json.dumps({
                'type': 'result',
                'taskId': task_id,
                'status': status,
                'modelPath': model_path,
                'image2D': result_2d,
                'imageNormal': result_normal,
                'imageUV': result_uv,
                'image1Path': normalized_paths[0] if len(normalized_paths) > 0 else None,
                'image2Path': normalized_paths[1] if len(normalized_paths) > 1 else None,
                'message': 'Hy3D multiview generation completed' if model_path else 'Model file not found',
            }, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            await _update_task(task_id, "error", {}, str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ThreeDTextRequest(BaseModel):
    prompt: str
    quality_mode: str = "fast"


class ThreeDImageRequest(BaseModel):
    image_path: str
    quality_mode: str = "fast"


class ThreeDFusionRequest(BaseModel):
    image1_path: str
    image2_path: str
    prompt: str
    quality_mode: str = "fast"


class ThreeDMultiviewRequest(BaseModel):
    image_paths: list[str]
    quality_mode: str = "fast"


def _normalize_multiview_paths(image_paths: list[str]) -> list[str]:
    paths = list(image_paths or [])
    if len(paths) == 3:
        paths = [paths[0], paths[1], "", paths[2]]
    while len(paths) < 4:
        paths.append("")
    return paths[:4]


def _validate_multiview_paths(image_paths: list[str]) -> list[str]:
    paths = _normalize_multiview_paths(image_paths)
    required = {
        "Front": paths[0],
        "Left": paths[1],
        "Back": paths[3],
    }
    for label, path in required.items():
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"{label} image file not found")
    if paths[2] and not os.path.exists(paths[2]):
        raise HTTPException(status_code=400, detail="Right image file not found")
    return paths


class ImproveImageRequest(BaseModel):
    image_path: str
    improvement_prompt: str
    quality_mode: str = "fast"
    image_lora_id: str | None = None


class GenerateImageRequest(BaseModel):
    prompt: str
    quality_mode: str = "fast"
    image_lora_id: str | None = None


class GenerateMultiviewImagesRequest(BaseModel):
    image_path: str
    prompt: str = ""
    quality_mode: str = "fast"


class GenerateVideoRequest(BaseModel):
    image_path: str | None = None
    prompt: str
    quality_mode: str = "quality"
    duration_seconds: int = 4
    width: int = 1024
    height: int = 576
    standard_model: str = "5b"
    lora_acceleration: bool = False


class ShowcaseMaterialRequest(BaseModel):
    title: str = "Ultra Studio 3D Asset"
    prompt: str = ""
    model_path: str | None = None
    image_path: str | None = None
    scene: str | None = None


@router.post("/generate/text")
async def generate_3d_text(req: ThreeDTextRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    task_id = await _create_task("text_to_3d", req.prompt, req.quality_mode, [])
    try:
        loop = asyncio.get_event_loop()
        result_2d, result_normal, result_uv, model_path = await loop.run_in_executor(
            executor,
            lambda: run_pipeline(
                mode="Text to 3D",
                quality=req.quality_mode,
                prompt=req.prompt,
                img1=None,
            ),
        )
        output_paths = {
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
        }
        await _update_task(task_id, "success" if model_path else "error", output_paths, "" if model_path else "Model file not found")
        return JSONResponse({
            "taskId": task_id,
            "status": "success" if model_path else "error",
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
            "message": "Text-to-3D completed" if model_path else "Model file not found",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/image")
async def generate_3d_image(req: ThreeDImageRequest):
    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=400, detail="Image file not found")
    task_id = await _create_task("image_to_3d", "", req.quality_mode, [req.image_path])
    try:
        loop = asyncio.get_event_loop()
        result_2d, result_normal, result_uv, model_path = await loop.run_in_executor(
            executor,
            lambda: run_pipeline(
                mode="Image to 3D",
                quality=req.quality_mode,
                prompt="",
                img1=req.image_path,
            ),
        )
        output_paths = {
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
        }
        await _update_task(task_id, "success" if model_path else "error", output_paths, "" if model_path else "Model file not found")
        return JSONResponse({
            "taskId": task_id,
            "status": "success" if model_path else "error",
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
            "message": "Image-to-3D completed" if model_path else "Model file not found",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/fusion")
async def generate_3d_fusion(req: ThreeDFusionRequest):
    if not os.path.exists(req.image1_path):
        raise HTTPException(status_code=400, detail="Image 1 not found")
    if not os.path.exists(req.image2_path):
        raise HTTPException(status_code=400, detail="Image 2 not found")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    task_id = await _create_task("fusion_to_3d", req.prompt, req.quality_mode, [req.image1_path, req.image2_path])
    try:
        loop = asyncio.get_event_loop()
        result_2d, result_normal, result_uv, model_path = await loop.run_in_executor(
            executor,
            lambda: run_pipeline(
                mode="Dual Image Fusion",
                quality=req.quality_mode,
                prompt=req.prompt,
                img1=req.image1_path,
                img2=req.image2_path,
            ),
        )
        output_paths = {
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
        }
        await _update_task(task_id, "success" if model_path else "error", output_paths, "" if model_path else "Model file not found")
        return JSONResponse({
            "taskId": task_id,
            "status": "success" if model_path else "error",
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
            "image1Path": req.image1_path,
            "image2Path": req.image2_path,
            "message": "Fusion completed" if model_path else "Model file not found",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/multiview")
async def generate_3d_multiview(req: ThreeDMultiviewRequest):
    image_paths = _validate_multiview_paths(req.image_paths)
    task_id = await _create_task("multiview_to_3d", "Hy3D 多视角生成", req.quality_mode, [path for path in image_paths if path])
    try:
        loop = asyncio.get_event_loop()
        result_2d, result_normal, result_uv, model_path = await loop.run_in_executor(
            executor,
            lambda: run_multiview_pipeline(image_paths, req.quality_mode),
        )
        output_paths = {
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
        }
        await _update_task(task_id, "success" if model_path else "error", output_paths, "" if model_path else "Model file not found")
        return JSONResponse({
            "taskId": task_id,
            "status": "success" if model_path else "error",
            "modelPath": model_path,
            "image2D": result_2d,
            "imageNormal": result_normal,
            "imageUV": result_uv,
            "image1Path": image_paths[0],
            "image2Path": image_paths[1],
            "message": "Hy3D multiview completed" if model_path else "Model file not found",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/improve-image")
async def improve_image(req: ImproveImageRequest):
    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=400, detail="Image file not found")
    task_id = await _create_task("improve_image", req.improvement_prompt, req.quality_mode, [req.image_path])
    try:
        loop = asyncio.get_event_loop()
        improved_path = await loop.run_in_executor(
            executor,
            lambda: improve_image_with_flux2klein(
                req.image_path,
                req.improvement_prompt,
                req.quality_mode,
                req.image_lora_id,
            ),
        )
        await _update_task(task_id, "success", {"imagePath": improved_path}, "")
        return JSONResponse({
            "taskId": task_id,
            "status": "success",
            "modelPath": improved_path,
            "imagePath": improved_path,
            "message": "Image improved successfully",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-image")
async def generate_image(req: GenerateImageRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    task_id = await _create_task("generate_image", req.prompt, req.quality_mode, [])
    try:
        loop = asyncio.get_event_loop()
        image_path = await loop.run_in_executor(
            executor,
            lambda: generate_image_with_flux(req.prompt, req.quality_mode, image_lora_id=req.image_lora_id),
        )
        await _update_task(task_id, "success", {"imagePath": image_path}, "")
        return JSONResponse({
            "taskId": task_id,
            "status": "success",
            "imagePath": image_path,
            "message": "Image generation completed",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/image-loras")
async def image_loras(quality_mode: str = "fast"):
    return JSONResponse(list_flux_image_loras(quality_mode))


@router.post("/generate-multiview-images")
async def generate_multiview_images(req: GenerateMultiviewImagesRequest):
    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=400, detail="Source image file not found")
    task_id = await _create_task(
        "generate_multiview_images",
        req.prompt,
        req.quality_mode,
        [req.image_path],
    )
    try:
        loop = asyncio.get_event_loop()
        views = await loop.run_in_executor(
            executor,
            lambda: generate_multiview_images_with_flux(req.image_path, req.prompt, req.quality_mode),
        )
        await _update_task(task_id, "success", views, "")
        return JSONResponse({
            "taskId": task_id,
            "status": "success",
            "frontPath": views.get("front"),
            "leftPath": views.get("left"),
            "backPath": views.get("back"),
            "message": "Multiview images generated",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-video")
async def generate_video(req: GenerateVideoRequest):
    if req.image_path and not os.path.exists(req.image_path):
        raise HTTPException(status_code=400, detail="Source image file not found")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    task_id = await _create_task(
        "generate_video",
        req.prompt,
        req.quality_mode,
        [req.image_path] if req.image_path else [],
    )
    try:
        duration = max(1, min(int(req.duration_seconds or 4), 5))
        width = max(256, min(int(req.width or 1024), 1280))
        height = max(256, min(int(req.height or 576), 1280))
        loop = asyncio.get_event_loop()
        video_path = await loop.run_in_executor(
            executor,
            lambda: generate_video_with_wan(
                req.image_path,
                req.prompt,
                req.quality_mode,
                duration_seconds=duration,
                width=width,
                height=height,
                lora_acceleration=req.lora_acceleration,
                standard_model=req.standard_model,
            ),
        )
        await _update_task(task_id, "success", {"videoPath": video_path}, "")
        return JSONResponse({
            "taskId": task_id,
            "status": "success",
            "videoPath": video_path,
            "message": "Video generation completed",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/showcase-materials")
async def create_showcase_materials(req: ShowcaseMaterialRequest):
    task_id = await _create_task(
        "showcase_materials",
        req.prompt,
        "",
        [path for path in [req.model_path, req.image_path] if path],
    )
    try:
        project_dir = os.environ.get("ULTRA_STUDIO_PROJECT_DIR") or os.getcwd()
        output_dir = os.path.join(project_dir, "docs", "showcase")
        os.makedirs(output_dir, exist_ok=True)
        safe_title = "".join(ch for ch in req.title if ch not in r'\/:*?"<>|').strip() or "Ultra Studio 3D Asset"
        output_path = os.path.join(output_dir, f"{safe_title}_展示材料.md")
        lines = [
            f"# {safe_title}",
            "",
            "## 作品定位",
            req.scene or "面向 AI+应用开发与软件技能赛道的本地 3D 资产生成与管理工作流。",
            "",
            "## 生成需求",
            req.prompt or "未填写生成提示词。",
            "",
            "## 产物清单",
            f"- 3D 模型: `{req.model_path or '尚未生成'}`",
            f"- 源图/预览图: `{req.image_path or '尚未生成'}`",
            "",
            "## 技术亮点",
            "- Agent 对话理解用户需求，并将任务分流到文本、图像、3D 与文档工具。",
            "- Flux 负责概念图生成与迭代修改，Hunyuan3D 负责网格与纹理生成。",
            "- ComfyUI 状态、日志和本地资源调度信息在界面内可见，便于比赛现场排障。",
            "- 结果以可预览资产卡返回，支持继续修改、导出和整理展示材料。",
            "",
            "## 演示步骤",
            "1. 选择应用场景模板，自动补全提示词。",
            "2. 先生成概念图，确认视觉方向。",
            "3. 将概念图转为 3D 模型，查看聊天框/工作台内预览。",
            "4. 一键生成展示材料，用于答辩介绍与作品归档。",
        ]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        await _update_task(task_id, "success", {"path": output_path}, "")
        return JSONResponse({
            "taskId": task_id,
            "status": "success",
            "path": output_path,
            "message": "Showcase materials created",
        })
    except Exception as e:
        await _update_task(task_id, "error", {}, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/text/stream")
async def generate_3d_text_stream(req: ThreeDTextRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    return _make_sse_stream("Text to 3D", req.quality_mode, req.prompt, None)


@router.post("/generate/image/stream")
async def generate_3d_image_stream(req: ThreeDImageRequest):
    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=400, detail="Image file not found")
    return _make_sse_stream("Image to 3D", req.quality_mode, "", req.image_path)


@router.post("/generate/fusion/stream")
async def generate_3d_fusion_stream(req: ThreeDFusionRequest):
    if not os.path.exists(req.image1_path):
        raise HTTPException(status_code=400, detail="Image 1 not found")
    if not os.path.exists(req.image2_path):
        raise HTTPException(status_code=400, detail="Image 2 not found")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    return _make_sse_stream("Dual Image Fusion", req.quality_mode, req.prompt, req.image1_path, req.image2_path)


@router.post("/generate/multiview/stream")
async def generate_3d_multiview_stream(req: ThreeDMultiviewRequest):
    image_paths = _validate_multiview_paths(req.image_paths)
    return _make_multiview_sse_stream(image_paths, req.quality_mode)


@router.post("/generate/cancel")
async def cancel_generation():
    import urllib.request
    interrupt_error = None
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/interrupt", timeout=5)
    except Exception as e:
        interrupt_error = str(e)

    await _cancel_running_tasks()
    response = {
        "status": "cancelled",
        "message": "Generation cancelled"
        if interrupt_error is None
        else "Generation marked cancelled; ComfyUI interrupt unavailable",
    }
    if interrupt_error is not None:
        response["interruptError"] = interrupt_error
    return JSONResponse(response)


@router.get("/output/{filename:path}")
async def serve_output_file(filename: str):
    output_dir = get_output_dir()
    if not output_dir:
        raise HTTPException(status_code=500, detail="ComfyUI output directory not configured")

    base_dir = Path(output_dir).resolve()
    candidates = [
        (base_dir / filename).resolve(),
        (base_dir / "3D" / filename).resolve(),
    ]

    file_path: Path | None = None
    for candidate in candidates:
        if candidate == base_dir or base_dir not in candidate.parents:
            continue
        if candidate.exists() and candidate.is_file():
            file_path = candidate
            break

    if file_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(file_path))
