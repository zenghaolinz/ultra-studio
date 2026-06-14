import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


DEFAULT_CONTEXT_WINDOW = 32_000
LOCAL_DEFAULT_CONTEXT_WINDOW = 8_192
MIN_CONTEXT_WINDOW = 4_096
RESPONSE_RESERVE_TOKENS = 2_048
TOOL_RESERVE_TOKENS = 2_048


@dataclass(frozen=True)
class ModelContextSpec:
    provider: str
    model_name: str
    context_window: int
    source: str


@dataclass(frozen=True)
class ContextFitResult:
    messages: list[dict]
    spec: ModelContextSpec
    budget: int
    before_tokens: int
    after_tokens: int
    compressed: bool


def infer_context_window(provider: str, model_name: str) -> int:
    provider_key = (provider or "").lower()
    model = (model_name or "").lower()

    if any(token in model for token in ["gpt-4.1", "gpt-4.5"]):
        return 1_000_000
    if any(token in model for token in ["gpt-4o", "gpt-4-turbo", "o1", "o3", "o4"]):
        return 128_000
    if "gpt-3.5" in model:
        return 16_384

    if provider_key == "deepseek" or "deepseek" in model:
        if any(token in model for token in ["v3", "r1", "reasoner", "v4"]):
            return 64_000
        return 32_000

    if provider_key == "qwen" or "qwen" in model or "qwq" in model:
        if any(token in model for token in ["long", "max", "plus", "turbo"]):
            return 128_000
        return 32_000

    if provider_key == "glm" or "glm" in model:
        return 128_000 if any(token in model for token in ["long", "4", "4.5"]) else 32_000

    if provider_key in {"ollama", "llama_cpp", "lmstudio", "local"}:
        match = re.search(r"(\d+)\s*k", model)
        if match:
            return max(MIN_CONTEXT_WINDOW, int(match.group(1)) * 1024)
        return LOCAL_DEFAULT_CONTEXT_WINDOW

    return DEFAULT_CONTEXT_WINDOW


def context_spec_from_provider_config(provider_config: Any) -> ModelContextSpec:
    provider = str(provider_config[0] if provider_config and len(provider_config) > 0 else "")
    model_name = str(provider_config[1] if provider_config and len(provider_config) > 1 else "")
    configured = 0
    if provider_config and len(provider_config) > 4:
        try:
            configured = int(provider_config[4] or 0)
        except (TypeError, ValueError):
            configured = 0
    if configured >= MIN_CONTEXT_WINDOW:
        return ModelContextSpec(provider, model_name, configured, "configured")
    return ModelContextSpec(provider, model_name, infer_context_window(provider, model_name), "inferred")


def estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        ascii_chars = sum(1 for char in value if ord(char) < 128)
        non_ascii_chars = len(value) - ascii_chars
        return max(1, (ascii_chars + 3) // 4 + non_ascii_chars)
    if isinstance(value, list):
        total = 0
        for item in value:
            if isinstance(item, dict) and item.get("type") == "image_url":
                total += 1024
            else:
                total += estimate_tokens(item)
        return total
    if isinstance(value, dict):
        return estimate_tokens(json.dumps(value, ensure_ascii=False))
    return estimate_tokens(str(value))


def estimate_messages_tokens(messages: list[dict]) -> int:
    return sum(4 + estimate_tokens(message.get("role", "")) + estimate_tokens(message.get("content")) for message in messages)


def estimate_tools_tokens(tools: list[dict] | None) -> int:
    if not tools:
        return 0
    return min(TOOL_RESERVE_TOKENS, estimate_tokens(json.dumps(tools, ensure_ascii=False)))


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, dict) and item.get("type") == "image_url":
                parts.append("[image attachment]")
        return "\n".join(parts)
    return str(content or "")


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 32:
        return text[:max_chars]
    head = max_chars // 2
    tail = max_chars - head - 24
    return f"{text[:head]}\n...[compressed]...\n{text[-tail:]}"


def _summary_message(dropped: list[dict], token_budget: int) -> dict:
    max_chars = max(400, token_budget * 3)
    lines = [
        "[Compressed conversation context]",
        "Older messages were compressed to stay within the selected model context window. Keep these facts in mind but prefer newer messages when conflicts exist.",
    ]
    per_message_chars = max(120, min(700, max_chars // max(1, len(dropped))))
    for message in dropped:
        role = message.get("role", "unknown")
        text = re.sub(r"\s+", " ", _message_text(message)).strip()
        if not text:
            continue
        lines.append(f"- {role}: {_truncate_text(text, per_message_chars)}")
    return {"role": "system", "content": _truncate_text("\n".join(lines), max_chars)}


def fit_messages_to_context(
    messages: list[dict],
    provider_config: Any,
    tools: list[dict] | None = None,
    response_reserve_tokens: int = RESPONSE_RESERVE_TOKENS,
) -> list[dict]:
    return fit_messages_to_context_with_stats(
        messages,
        provider_config,
        tools=tools,
        response_reserve_tokens=response_reserve_tokens,
    ).messages


def fit_messages_to_context_with_stats(
    messages: list[dict],
    provider_config: Any,
    tools: list[dict] | None = None,
    response_reserve_tokens: int = RESPONSE_RESERVE_TOKENS,
) -> ContextFitResult:
    spec = context_spec_from_provider_config(provider_config)
    tool_tokens = estimate_tools_tokens(tools)
    budget = max(MIN_CONTEXT_WINDOW // 2, spec.context_window - response_reserve_tokens - tool_tokens)
    copied = deepcopy(messages)
    before_tokens = estimate_messages_tokens(copied)
    if before_tokens <= budget:
        return ContextFitResult(copied, spec, budget, before_tokens, before_tokens, False)

    if len(copied) <= 2:
        fitted = _trim_large_messages(copied, budget)
        after_tokens = estimate_messages_tokens(fitted)
        _log_context_fit(spec, budget, before_tokens, after_tokens, True)
        return ContextFitResult(fitted, spec, budget, before_tokens, after_tokens, True)

    system_messages = [message for message in copied if message.get("role") == "system"]
    non_system = [message for message in copied if message.get("role") != "system"]
    latest = non_system[-1:] if non_system else []
    history = non_system[:-1]

    kept: list[dict] = []
    dropped: list[dict] = []
    base = system_messages + latest
    remaining_budget = max(512, budget - estimate_messages_tokens(base))
    for message in reversed(history):
        cost = estimate_messages_tokens([message])
        if cost <= remaining_budget:
            kept.insert(0, message)
            remaining_budget -= cost
        else:
            dropped.insert(0, message)

    fitted = system_messages[:1]
    if dropped:
        summary_budget = max(256, min(2048, budget // 8))
        fitted.append(_summary_message(dropped, summary_budget))
    fitted.extend(system_messages[1:])
    fitted.extend(kept)
    fitted.extend(latest)
    if estimate_messages_tokens(fitted) <= budget:
        after_tokens = estimate_messages_tokens(fitted)
        _log_context_fit(spec, budget, before_tokens, after_tokens, True)
        return ContextFitResult(fitted, spec, budget, before_tokens, after_tokens, True)
    fitted = _trim_large_messages(fitted, budget)
    after_tokens = estimate_messages_tokens(fitted)
    _log_context_fit(spec, budget, before_tokens, after_tokens, True)
    return ContextFitResult(fitted, spec, budget, before_tokens, after_tokens, True)


def _log_context_fit(
    spec: ModelContextSpec,
    budget: int,
    before_tokens: int,
    after_tokens: int,
    compressed: bool,
):
    if not compressed:
        return
    print(
        "[context] compressed "
        f"provider={spec.provider or '-'} "
        f"model={spec.model_name or '-'} "
        f"window={spec.context_window} "
        f"source={spec.source} "
        f"budget={budget} "
        f"tokens={before_tokens}->{after_tokens}"
    )


def _trim_large_messages(messages: list[dict], budget: int) -> list[dict]:
    fitted = deepcopy(messages)
    while estimate_messages_tokens(fitted) > budget and len(fitted) > 1:
        removed = False
        for index, message in enumerate(fitted[:-1]):
            if message.get("role") != "system":
                del fitted[index]
                removed = True
                break
        if not removed:
            break

    if estimate_messages_tokens(fitted) <= budget:
        return fitted

    for message in fitted:
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _truncate_text(content, max(1000, budget * 3 // max(1, len(fitted))))
    return fitted
