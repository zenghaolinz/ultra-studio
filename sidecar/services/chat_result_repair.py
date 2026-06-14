from routes.direct_files import (
    edit_text_result_can_fallback,
    is_text_file_edit_followup_intent,
    run_direct_text_file_create,
    run_direct_text_file_edit,
)
from schemas import ChatRequest
from services.chat_result_verifier import verify_tool_result


async def repair_text_edit_result(
    req: ChatRequest,
    client,
    model_name: str,
    provider_config,
    edit_text_result: dict | None,
    write_many_result: dict | None,
) -> tuple[dict | None, dict | None]:
    if not edit_text_result:
        return edit_text_result, None
    if _write_many_succeeded(write_many_result):
        return None, None

    result = edit_text_result.get("result")
    verification = verify_tool_result("edit_text_file", result)
    if not (verification.retryable or edit_text_result_can_fallback(result)):
        return edit_text_result, None
    if not is_text_file_edit_followup_intent(req.content):
        return edit_text_result, None

    repaired = await run_direct_text_file_edit(req, client, model_name, provider_config)
    repair_record = {
        "tool": "edit_text_file",
        "result": repaired or {"ok": False, "error": "repair did not produce an edit result"},
        "repair_of": result,
        "repair_reason": verification.reason,
    }
    if repaired and repaired.get("ok"):
        return {"tool": "edit_text_file", "result": repaired}, repair_record
    return edit_text_result, repair_record


async def repair_text_create_result(
    req: ChatRequest,
    client,
    model_name: str,
    provider_config,
    create_text_result: dict | None,
    *,
    force: bool = True,
    prompt_override: str | None = None,
) -> tuple[dict | None, dict | None]:
    if not create_text_result:
        return create_text_result, None

    tool_name, result, wrapped = _unwrap_tool_result(create_text_result, "create_text_file")
    verification = verify_tool_result(tool_name, result)
    if verification.accepted or verification.status == "needs_user":
        return create_text_result, None

    repaired = await run_direct_text_file_create(
        req,
        client,
        model_name,
        force=force,
        prompt_override=prompt_override,
        provider_config=provider_config,
    )
    repair_record = {
        "tool": "create_text_file",
        "result": repaired or {"ok": False, "error": "repair did not produce a create result"},
        "repair_of": result,
        "repair_reason": verification.reason,
    }
    if repaired and verify_tool_result("create_text_file", repaired).accepted:
        return _wrap_tool_result(tool_name, repaired, wrapped), repair_record
    return create_text_result, repair_record


def _unwrap_tool_result(tool_result: dict, default_tool: str) -> tuple[str, dict | None, bool]:
    if isinstance(tool_result.get("result"), dict):
        return str(tool_result.get("tool") or default_tool), tool_result["result"], True
    return default_tool, tool_result, False


def _wrap_tool_result(tool_name: str, result: dict, wrapped: bool) -> dict:
    if wrapped:
        return {"tool": tool_name, "result": result}
    return result


def _write_many_succeeded(write_many_result: dict | None) -> bool:
    if not write_many_result or not isinstance(write_many_result.get("result"), dict):
        return False
    return bool(write_many_result["result"].get("ok"))
