from memory.schemas import ActivatedMemory

_activated: ActivatedMemory | None = None


def get_activated() -> ActivatedMemory | None:
    return _activated


def set_activated(memory: ActivatedMemory):
    global _activated
    _activated = memory


def clear_activated():
    global _activated
    _activated = None
