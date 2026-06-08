from pathlib import Path

from memory import manager as memory_mgr
from routes.direct_files import run_direct_text_file_create
from schemas import ChatRequest
from services.chat_confirmations import delete_then_create_prompt, extract_confirmed_delete


async def run_confirmed_delete_request(
    req: ChatRequest,
    client,
    model_name: str,
) -> tuple[dict, dict | None] | None:
    parsed = extract_confirmed_delete(req.content)
    if not parsed:
        return None

    target, continuation = parsed
    target_path = Path(target)
    recursive = target_path.exists() and target_path.is_dir()
    delete_result = memory_mgr.handle_delete_path(
        target,
        "auto",
        recursive,
        True,
        req.permission_mode,
    )
    create_result = None
    if delete_result.get("ok") and continuation:
        create_prompt = delete_then_create_prompt(target, continuation)
        create_result = await run_direct_text_file_create(
            req,
            client,
            model_name,
            force=True,
            prompt_override=create_prompt,
        )
    return delete_result, create_result
