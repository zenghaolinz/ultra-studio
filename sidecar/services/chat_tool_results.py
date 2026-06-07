THREE_D_TOOL_NAMES = {
    "generate_3d_from_text",
    "generate_3d_from_image",
    "generate_3d_fusion",
    "generate_3d_from_generated_multiview",
    "modify_previous_3d",
}


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
