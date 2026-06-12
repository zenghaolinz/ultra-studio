FORCE_SWITCH_KEYWORDS = {
    "切换到",
    "聊聊",
    "换个话题",
    "现在说",
    "不是说这个",
    "switch to",
    "talk about",
    "change topic",
    "let's discuss",
}


def should_force_switch(user_input: str) -> bool:
    return any(kw in user_input for kw in FORCE_SWITCH_KEYWORDS)
