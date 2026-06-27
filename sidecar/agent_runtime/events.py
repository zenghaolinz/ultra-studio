import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunMetrics:
    clock: Callable[[], float] = time.perf_counter
    _started_at: float = field(init=False)
    _model_started_at: float | None = field(default=None, init=False)
    _provider_signal_at: float | None = field(default=None, init=False)
    _visible_token_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock()

    def mark_model_started(self) -> None:
        if self._model_started_at is None:
            self._model_started_at = self.clock()

    def mark_provider_signal(self) -> None:
        if self._provider_signal_at is None:
            self._provider_signal_at = self.clock()

    def mark_visible_token(self) -> None:
        if self._visible_token_at is None:
            self._visible_token_at = self.clock()

    def finish(self, *, model_turns: int, tool_calls: int) -> dict[str, int | float | None]:
        finished_at = self.clock()
        return {
            "modelStartMs": self._elapsed_ms(self._started_at, self._model_started_at),
            "providerTtftMs": self._elapsed_ms(self._model_started_at, self._provider_signal_at),
            "applicationTtftMs": self._elapsed_ms(self._started_at, self._visible_token_at),
            "totalMs": self._elapsed_ms(self._started_at, finished_at),
            "modelTurns": model_turns,
            "toolCalls": tool_calls,
        }

    @staticmethod
    def _elapsed_ms(start: float | None, end: float | None) -> float | None:
        if start is None or end is None:
            return None
        return round((end - start) * 1000, 3)


class RunEventEmitter:
    def __init__(
        self,
        *,
        run_id: str,
        conversation_id: str,
        metrics: RunMetrics | None = None,
        wall_clock: Callable[[], str] = utc_iso,
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.metrics = metrics or RunMetrics()
        self._wall_clock = wall_clock
        self._sequence = 0

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sequence += 1
        return {
            "runId": self.run_id,
            "conversationId": self.conversation_id,
            "type": event_type,
            "sequence": self._sequence,
            "timestamp": self._wall_clock(),
            "data": data or {},
        }
