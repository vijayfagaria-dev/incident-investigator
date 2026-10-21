import time
from collections.abc import Callable
from typing import Self

from pydantic import Field, model_validator

from investigator.domain.base import DomainModel
from investigator.domain.report import RunStats
from investigator.llm.messages import Usage


class BudgetLimits(DomainModel):
    model_calls: int = Field(default=60, gt=0)
    tool_calls: int = Field(default=40, ge=0)
    tokens: int = Field(default=400_000, gt=0)
    wall_clock_s: float = Field(default=900.0, gt=0)
    reserve_model_calls: int = Field(default=6, ge=0)
    """Model calls kept back for concluding: final answers and the report."""
    reserve_tokens: int = Field(default=60_000, ge=0)

    @model_validator(mode="after")
    def _reserve_fits(self) -> Self:
        if self.reserve_model_calls > self.model_calls or self.reserve_tokens > self.tokens:
            raise ValueError("the reserve cannot exceed the budget it is part of")
        return self


class BudgetExceeded(Exception):
    pass


class Budget:
    """Spending limits shared by everything in one run.

    Exploration (tool use) stops at the limits minus a reserve. The reserve lets agents
    still state what they found, and lets the run still produce a report.
    """

    def __init__(self, limits: BudgetLimits, clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = limits
        self._clock = clock
        self._started = clock()
        self._model_calls = 0
        self._tool_calls = 0
        self._tokens = 0

    def exploration_stop_reason(self) -> str | None:
        """Why exploration must stop now, or ``None`` if it may continue."""
        limits = self.limits
        if self._model_calls >= limits.model_calls - limits.reserve_model_calls:
            return "model call budget reached"
        if self._tokens >= limits.tokens - limits.reserve_tokens:
            return "token budget reached"
        if self._tool_calls >= limits.tool_calls:
            return "tool call budget reached"
        if self.elapsed_s() >= limits.wall_clock_s:
            return "time budget reached"
        return None

    def fully_spent(self) -> bool:
        """Whether even the reserve kept for concluding is gone."""
        return self._model_calls >= self.limits.model_calls or self._tokens >= self.limits.tokens

    def require_model_call(self, concluding: bool = False) -> None:
        """Raise ``BudgetExceeded`` unless a model call is allowed now."""
        if not concluding:
            if reason := self.exploration_stop_reason():
                raise BudgetExceeded(reason)
            return
        if self.fully_spent():
            raise BudgetExceeded("budget fully spent, including the reserve")

    def take_tool_call(self) -> bool:
        if self._tool_calls >= self.limits.tool_calls:
            return False
        self._tool_calls += 1
        return True

    def record_model_call(self, usage: Usage) -> None:
        self._model_calls += 1
        self._tokens += usage.total_tokens

    def elapsed_s(self) -> float:
        return self._clock() - self._started

    def stats(self, rounds: int) -> RunStats:
        """What the run has spent so far, as the report shows it."""
        return RunStats(
            rounds=rounds,
            model_calls=self._model_calls,
            tool_calls=self._tool_calls,
            tokens=self._tokens,
            elapsed_s=round(self.elapsed_s(), 2),
        )
