import json
import re


TEXTUAL_TOOL_INVOKE_PATTERN = re.compile(
    r"<\s*\|\s*\|\s*DSML\s*\|\s*\|\s*invoke\s+name=\"([^\"]+)\"\s*>",
    re.IGNORECASE,
)

TEXTUAL_TOOL_PARAM_PATTERN = re.compile(
    r"<\s*\|\s*\|\s*DSML\s*\|\s*\|\s*parameter\s+name=\"([^\"]+)\"[^>]*>([\s\S]*?)</\s*\|\s*\|\s*DSML\s*\|\s*\|\s*parameter>",
    re.IGNORECASE,
)

TEXTUAL_TOOL_MARKER = "<| | DSML | |"
TEXTUAL_TOOL_MARKER_PATTERN = re.compile(
    r"<\s*/?\s*\|\s*\|\s*DSML\s*\|\s*\|",
    re.IGNORECASE,
)
TEXTUAL_TOOL_CALLS_END_PATTERN = re.compile(
    r"</\s*\|\s*\|\s*DSML\s*\|\s*\|\s*tool_calls\s*>",
    re.IGNORECASE,
)

SUPPORTED_TEXTUAL_TOOL_NAMES = {
    "edit_text_file",
    "web_search",
    "web_fetch",
    "read_document",
    "read_many_files",
    "list_directory",
    "search_files",
    "write_many_files",
}


def extract_textual_tool_calls(content: str) -> list[tuple[str, dict]]:
    text = (content or "").strip()
    marker_match = TEXTUAL_TOOL_MARKER_PATTERN.search(text)
    if not marker_match:
        return []
    prefix = text[: marker_match.start()].strip()
    if "```" in text or len(prefix) > 160:
        return []

    invokes = list(TEXTUAL_TOOL_INVOKE_PATTERN.finditer(content or ""))
    calls: list[tuple[str, dict]] = []
    for index, invoke in enumerate(invokes):
        tool_name = invoke.group(1).strip()
        block_end = invokes[index + 1].start() if index + 1 < len(invokes) else len(content or "")
        block = (content or "")[invoke.start():block_end]
        args = {
            match.group(1).strip(): match.group(2).strip()
            for match in TEXTUAL_TOOL_PARAM_PATTERN.finditer(block)
        }
        calls.append((tool_name, args))

    if not calls:
        return []
    if any(tool_name in SUPPORTED_TEXTUAL_TOOL_NAMES for tool_name, _ in calls):
        return calls
    if prefix and not any(word in prefix for word in ["替换", "修改", "修复", "执行", "现在", "调用", "搜索", "读取", "获取"]):
        return []
    return calls


def extract_textual_tool_call(content: str) -> tuple[str, dict] | None:
    calls = extract_textual_tool_calls(content)
    return calls[0] if calls else None


def parse_textual_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def parse_textual_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def parse_textual_optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def parse_textual_json(value: object, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default
