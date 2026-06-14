from routes.direct_files import (
    edit_text_result_can_fallback,
    is_text_file_edit_followup_intent,
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


def _write_many_succeeded(write_many_result: dict | None) -> bool:
    if not write_many_result or not isinstance(write_many_result.get("result"), dict):
        return False
    return bool(write_many_result["result"].get("ok"))
