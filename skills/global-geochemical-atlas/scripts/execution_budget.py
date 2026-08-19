#!/usr/bin/env python3
"""Monotonic execution budgets for evidence-first research runs.

The competition harness limit is 900 seconds.  The task planner reserves
three minutes of that envelope for Agent setup and result hand-off, while the
direct research controller retains an explicitly selected 12-hour ceiling for
operator-authorized studies.  Time is a safety boundary, not a substitute for
the delivery gates.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable


OFFICIAL_TASK_LIMIT_SECONDS = 15 * 60.0
OFFICIAL_HARNESS_RESERVE_SECONDS = 3 * 60.0
EXTENDED_RESEARCH_LIMIT_SECONDS = 12 * 60 * 60.0
DEFAULT_INTERNAL_BUDGET_SECONDS = 30 * 60.0
MAX_INTERNAL_BUDGET_SECONDS = EXTENDED_RESEARCH_LIMIT_SECONDS


class ExecutionBudgetError(RuntimeError):
    """Raised when no safe child-process budget remains."""


class ExecutionBudget:
    """A deadline that can only decrease and is shared by every execution stage."""

    def __init__(
        self,
        total_seconds: float = DEFAULT_INTERNAL_BUDGET_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(total_seconds, bool)
            or not isinstance(total_seconds, (int, float))
            or not math.isfinite(float(total_seconds))
            or not 1 <= float(total_seconds) <= MAX_INTERNAL_BUDGET_SECONDS
        ):
            raise ExecutionBudgetError(
                f"total execution budget must be between 1 and {MAX_INTERNAL_BUDGET_SECONDS:g} seconds"
            )
        self._clock = clock
        self.total_seconds = float(total_seconds)
        self.started_at = clock()
        self.deadline = self.started_at + self.total_seconds

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def child_timeout(
        self,
        stage: str,
        *,
        cap_seconds: float | None = None,
        reserve_seconds: float = 0.0,
        minimum_seconds: float = 0.05,
    ) -> float:
        if reserve_seconds < 0 or minimum_seconds <= 0:
            raise ExecutionBudgetError(
                "deadline reserve must be non-negative and minimum must be positive"
            )
        available = self.remaining_seconds - reserve_seconds
        if cap_seconds is not None:
            if cap_seconds <= 0 or not math.isfinite(cap_seconds):
                raise ExecutionBudgetError(
                    f"{stage} timeout cap must be positive and finite"
                )
            available = min(available, cap_seconds)
        if available < minimum_seconds:
            raise ExecutionBudgetError(
                f"global execution budget exhausted before {stage}; "
                f"remaining={self.remaining_seconds:.3f}s reserve={reserve_seconds:.3f}s"
            )
        return available
