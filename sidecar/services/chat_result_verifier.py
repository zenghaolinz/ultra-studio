import os
from dataclasses import dataclass

from services.chat_tool_results import THREE_D_TOOL_NAMES


@dataclass(frozen=True)
class VerificationResult:
    status: str
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.status in {"accepted", "pending", "needs_user"}

    @property
    def retryable(self) -> bool:
        return self.status == "retryable"


def verify_tool_result(tool_name: str, result) -> VerificationResult:
    if not isinstance(result, dict):
        if result:
            return VerificationResult("accepted")
        return VerificationResult("failed", "empty result")

    if result.get("needs_confirmation") or result.get("needs_path"):
        return VerificationResult("needs_user", "waiting for user input")
    if result.get("manual_start_required"):
        return VerificationResult("needs_user", "waiting for ComfyUI startup")
    if result.get("needs_read"):
        return VerificationResult("retryable", result.get("error") or "read source file before editing")

    if tool_name in {"generate_image", "edit_image", "modify_image_with_flux", "generate_multiview_images_from_image"}:
        return _verify_media_result(result, ["image_path", "imagePath", "improved_image_path", "front_path", "frontPath"])
    if tool_name == "generate_video":
        return _verify_media_result(result, ["video_path", "videoPath"])
    if tool_name in THREE_D_TOOL_NAMES:
        return _verify_media_result(result, ["model_path", "modelPath", "image_2d", "image2D"])

    if tool_name in {"create_text_file", "write_many_files"}:
        return _verify_written_files(result)
    if tool_name == "edit_text_file":
        return _verify_text_edit(result)
    if tool_name in {"create_docx_document", "edit_docx_document", "create_docx", "edit_docx"}:
        return _verify_single_path_result(result)
    if tool_name == "read_document":
        return _verify_read_document(result)
    if tool_name == "read_many_files":
        return _verify_read_many_files(result)
    if tool_name == "delete_file":
        return _verify_ok_result(result)
    if tool_name in {"run_command", "run_project_check"}:
        return _verify_ok_or_confirmation(result)

    if "ok" in result:
        return _verify_ok_result(result)
    if result.get("status") == "error":
        return VerificationResult("failed", result.get("message") or "tool returned error")
    return VerificationResult("accepted")


def verify_routed_result(routed_result: dict | str | None) -> VerificationResult:
    if routed_result is None:
        return VerificationResult("failed", "no routed result")
    if isinstance(routed_result, str):
        return VerificationResult("accepted" if routed_result.strip() else "failed", "empty text result")
    if "tool" in routed_result:
        return verify_tool_result(str(routed_result.get("tool") or ""), routed_result.get("result"))
    if routed_result.get("document_count") is not None or routed_result.get("needs_path"):
        return _verify_ok_or_confirmation(routed_result)
    if routed_result.get("path") and routed_result.get("ok") is not None:
        return _verify_single_path_result(routed_result)
    return VerificationResult("accepted")


def _verify_media_result(result: dict, path_keys: list[str]) -> VerificationResult:
    status = result.get("status")
    task_id = result.get("task_id") or result.get("taskId")
    if status == "queued" and task_id:
        return VerificationResult("pending", "queued generation task")
    if status == "error":
        return VerificationResult("retryable" if result.get("retryable") else "failed", result.get("message") or "media task failed")
    if status == "success":
        for key in path_keys:
            value = result.get(key)
            if isinstance(value, str) and value:
                if os.path.exists(value) or status == "success":
                    return VerificationResult("accepted")
        return VerificationResult("failed", "success result missing output path")
    if task_id:
        return VerificationResult("pending", "generation task returned task id")
    return VerificationResult("failed", "media result missing status/task id")


def _verify_written_files(result: dict) -> VerificationResult:
    if not result.get("ok") and not result.get("files"):
        return VerificationResult("retryable" if result.get("needs_read") else "failed", result.get("error") or "write failed")
    files = result.get("files")
    if isinstance(files, list) and files:
        for item in files:
            path = item.get("path") if isinstance(item, dict) else ""
            if not path or not os.path.exists(path):
                return VerificationResult("failed", f"written file missing: {path or '<empty>'}")
        return VerificationResult("accepted")
    path = result.get("path")
    if isinstance(path, str) and path and os.path.exists(path):
        return VerificationResult("accepted")
    return VerificationResult("failed", "write result missing file path")


def _verify_text_edit(result: dict) -> VerificationResult:
    if result.get("needs_read"):
        return VerificationResult("retryable", result.get("error") or "target file must be read first")
    if not result.get("ok"):
        return VerificationResult("retryable" if _looks_retryable_error(result.get("error")) else "failed", result.get("error") or "edit failed")
    path = result.get("path")
    if isinstance(path, str) and path and not os.path.exists(path):
        return VerificationResult("failed", f"edited file missing: {path}")
    return VerificationResult("accepted")


def _verify_single_path_result(result: dict) -> VerificationResult:
    if not result.get("ok"):
        return VerificationResult("failed", result.get("error") or "operation failed")
    path = result.get("path")
    if isinstance(path, str) and path and os.path.exists(path):
        return VerificationResult("accepted")
    return VerificationResult("failed", "result path missing or does not exist")


def _verify_read_document(result: dict) -> VerificationResult:
    if not result.get("ok"):
        return VerificationResult("failed", result.get("error") or "read failed")
    if result.get("content") or result.get("text"):
        return VerificationResult("accepted")
    return VerificationResult("failed", "read result has no content")


def _verify_read_many_files(result: dict) -> VerificationResult:
    if not result.get("ok") and not result.get("files"):
        return VerificationResult("failed", result.get("error") or "read many failed")
    files = result.get("files")
    if isinstance(files, list) and files:
        return VerificationResult("accepted")
    return VerificationResult("failed", "read many result has no files")


def _verify_ok_or_confirmation(result: dict) -> VerificationResult:
    if result.get("needs_confirmation"):
        return VerificationResult("needs_user", "waiting for confirmation")
    return _verify_ok_result(result)


def _verify_ok_result(result: dict) -> VerificationResult:
    if result.get("ok"):
        return VerificationResult("accepted")
    return VerificationResult("failed", result.get("error") or result.get("message") or "operation failed")


def _looks_retryable_error(error) -> bool:
    text = str(error or "")
    return any(token in text for token in ["未找到", "not found", "needs_read", "读取", "read"])
