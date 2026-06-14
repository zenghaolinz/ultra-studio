THREE_D_TOOL_NAMES = {
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_fusion",
    "generate_3d_from_generated_multiview",
    "modify_previous_3d",
}


def _verification_status(tool_name: str, result: dict | None) -> tuple[int, bool]:
    if not isinstance(result, dict):
        return (0, False)
    if result.get("needs_confirmation") or result.get("manual_start_required"):
        return (2, True)
    if result.get("needs_read"):
        return (0, False)
    if result.get("ok") or result.get("status") in {"success", "queued"}:
        return (3, True)
    return (0, False)


def first_3d_result(tool_results: list[dict]) -> dict | None:
    for item in tool_results:
        if item.get("tool") in THREE_D_TOOL_NAMES:
            return item
    return None


def first_tool_result(tool_results: list[dict], tool_name: str) -> dict | None:
    for item in tool_results:
        if item.get("tool") == tool_name:
            return item
    return None


def requires_manual_comfy_start(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    payload = result.get("result") if "result" in result else result
    return isinstance(payload, dict) and bool(payload.get("manual_start_required"))


def any_requires_manual_comfy_start(items: list[dict]) -> bool:
    return any(requires_manual_comfy_start(item) for item in items)


def best_tool_result(tool_results: list[dict], tool_name: str) -> dict | None:
    matches = [item for item in tool_results if item.get("tool") == tool_name]
    if not matches:
        return None
    ranked = []
    for index, item in enumerate(matches):
        score, accepted = _verification_status(tool_name, item.get("result"))
        ranked.append((score, index, accepted, item))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if ranked[0][2]:
        return ranked[0][3]
    for item in reversed(matches):
        result = item.get("result")
        if isinstance(result, dict) and result.get("ok"):
            return item
    return matches[-1]


def result_output_paths(routed_result: dict | str | None) -> list[str]:
    if not isinstance(routed_result, dict):
        return []
    result = routed_result.get("result") if "result" in routed_result else routed_result
    if not isinstance(result, dict):
        return []
    keys = [
        "image_path",
        "improved_image_path",
        "model_path",
        "image_2d",
        "image_normal",
        "image_uv",
        "front_path",
        "left_path",
        "back_path",
        "path",
        "output_path",
    ]
    paths = []
    for key in keys:
        value = result.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    files = result.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
    deduped = []
    seen = set()
    for path in paths:
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped
