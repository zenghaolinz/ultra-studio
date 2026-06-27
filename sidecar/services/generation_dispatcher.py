import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from services.generation_tasks import claim_generation_task, update_generation_task

Handler = Callable[[Any], Awaitable[Any]]


def _handler_for(task_type: str):
    from routes import asset_3d

    return {
        "text_to_3d": (asset_3d.ThreeDTextRequest, asset_3d.generate_3d_text),
        "image_to_3d": (asset_3d.ThreeDImageRequest, asset_3d.generate_3d_image),
        "fusion_to_3d": (asset_3d.ThreeDFusionRequest, asset_3d.generate_3d_fusion),
        "multiview_to_3d": (asset_3d.ThreeDMultiviewRequest, asset_3d.generate_3d_multiview),
        "improve_image": (asset_3d.ImproveImageRequest, asset_3d.improve_image),
        "generate_image": (asset_3d.GenerateImageRequest, asset_3d.generate_image),
        "generate_multiview_images": (asset_3d.GenerateMultiviewImagesRequest, asset_3d.generate_multiview_images),
        "generate_video": (asset_3d.GenerateVideoRequest, asset_3d.generate_video),
        "showcase_materials": (asset_3d.ShowcaseMaterialRequest, asset_3d.create_showcase_materials),
    }.get(task_type)


async def dispatch_generation_task(task: dict[str, Any]) -> None:
    try:
        handler_spec = _handler_for(task["taskType"])
        if not handler_spec:
            raise ValueError(f"Unsupported retry task type: {task['taskType']}")
        request_type, handler = handler_spec
        request = request_type.model_validate(task["requestPayload"])
        with claim_generation_task(task["id"]):
            await handler(request)
    except Exception as exc:
        await update_generation_task(task["id"], "error", {}, str(exc))


def schedule_generation_task(task: dict[str, Any]) -> None:
    asyncio.create_task(dispatch_generation_task(task))
