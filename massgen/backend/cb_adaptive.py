"""Adaptive thresholds for LLM circuit breakers (Phase 5).

Tracks rolling 429/failure rate via EWMA and observed recovery latency,
and exposes effective_max_failures() and effective_reset_time() that the
circuit breaker consults instead of static config values.

Opt-in: adaptive=False in AdaptiveConfig preserves fixed-threshold behavior.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .llm_circuit_breaker import LLMCircuitBreakerConfig


@dataclass
class AdaptiveConfig:
    """Configuration for the adaptive threshold controller.

    All fields have defaults so existing CB configs need no changes.
    Set enabled=True to activate adaptive thresholds.
    """

    enabled: bool = False
    ewma_alpha: float = 0.1
    low_error_rate: float = 0.1
    high_error_rate: float = 0.9
    min_effective_max_failures: int = 2
    max_effective_max_failures: int = 20
    min_effective_reset_seconds: float = 10.0
    max_effective_reset_seconds: float = 600.0
    recovery_sample_weight: float = 0.3
    initial_recovery_latency_seconds: float | None = None

    def __post_init__(self) -> None:
        """Validate all configuration fields."""
        if not (0 < self.ewma_alpha <= 1):
            raise ValueError(
                f"ewma_alpha must be in (0, 1], got {self.ewma_alpha}",
            )
        if not (0 <= self.low_error_rate < self.high_error_rate <= 1):
            raise ValueError(
                f"low_error_rate ({self.low_error_rate}) must satisfy 0 <= low < high <= 1, " f"high_error_rate={self.high_error_rate}",
            )
        if self.min_effective_max_failures < 1:
            raise ValueError(
                f"min_effective_max_failures must be >= 1, got {self.min_effective_max_failures}",
            )
        if self.max_effective_max_failures < self.min_effective_max_failures:
            raise ValueError(
                f"max_effective_max_failures ({self.max_effective_max_failures}) must be " f">= min_effective_max_failures ({self.min_effective_max_failures})",
            )
        if self.min_effective_reset_seconds < 0.1:
            raise ValueError(
                f"min_effective_reset_seconds must be >= 0.1, got {self.min_effective_reset_seconds}",
            )
        if self.max_effective_reset_seconds < self.min_effective_reset_seconds:
            raise ValueError(
                f"max_effective_reset_seconds ({self.max_effective_reset_seconds}) must be " f">= min_effective_reset_seconds ({self.min_effective_reset_seconds})",
            )
        if not (0 < self.recovery_sample_weight <= 1):
            raise ValueError(
                f"recovery_sample_weight must be in (0, 1], got {self.recovery_sample_weight}",
            )
        if self.initial_recovery_latency_seconds is not None:
            if not math.isfinite(self.initial_recovery_latency_seconds):
                raise ValueError(
                    "initial_recovery_latency_seconds must be finite, " f"got {self.initial_recovery_latency_seconds}",
                )
            if self.initial_recovery_latency_seconds < 0:
                raise ValueError(
                    "initial_recovery_latency_seconds must be >= 0, " f"got {self.initial_recovery_latency_seconds}",
                )


class AdaptiveController:
    """EWMA-based adaptive thresholds.

    Thread-safe: all mutating methods acquire self._lock (threading.Lock).
    Pure Python math, zero external dependencies.
    """

    def __init__(
        self,
        base_config: LLMCircuitBreakerConfig,
        adaptive_config: AdaptiveConfig,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._base = base_config
        self._cfg = adaptive_config
        self._error_rate_ewma: float = 0.0
        self._recovery_latency_ewma: float = adaptive_config.initial_recovery_latency_seconds if adaptive_config.initial_recovery_latency_seconds is not None else float(base_config.reset_time_seconds)
        self._open_at: float | None = None
        self._lock = threading.Lock()
        self._clock: Callable[[], float] = clock or time.monotonic

    def record_outcome(self, is_failure: bool) -> None:
        """Update failure-rate EWMA with a single request outcome.

        True = failure, False = success.
        EWMA: new = (1 - alpha) * old + alpha * sample.
        Result is clamped to [0.0, 1.0] to guard against floating-point drift.
        """
        sample = 1.0 if bool(is_failure) else 0.0
        alpha = self._cfg.ewma_alpha
        with self._lock:
            new_rate = (1.0 - alpha) * self._error_rate_ewma + alpha * sample
            if not math.isfinite(new_rate):
                new_rate = self._error_rate_ewma
            self._error_rate_ewma = max(0.0, min(1.0, new_rate))

    def record_open(self) -> None:
        """Mark that the CB transitioned to OPEN -- starts recovery timer.

        Idempotent: if _open_at is already set, overwrite (latest OPEN wins).
        Clock is captured before acquiring the lock to minimize lock hold time.
        """
        now = self._clock()
        with self._lock:
            self._open_at = now

    def record_close(self) -> None:
        """Mark that the CB transitioned back to CLOSED after recovery.

        If _open_at was set, clears _open_at unconditionally and updates
        recovery_latency_ewma only when the computed sample is finite.
        If _open_at was None, no-op.

        Defensive: negative latency due to clock skew is clamped to 0.
        Clock is captured before acquiring the lock to minimize lock hold time.
        """
        now = self._clock()
        with self._lock:
            if self._open_at is None:
                return
            raw_latency = now - self._open_at
            latency = max(0.0, raw_latency)
            self._open_at = None
            w = self._cfg.recovery_sample_weight
            new_latency = (1.0 - w) * self._recovery_latency_ewma + w * latency
            if not math.isfinite(new_latency):
                return
            self._recovery_latency_ewma = new_latency

    def effective_max_failures(self) -> int:
        """Return the effective failure threshold given current EWMA error rate.

        Logic:
          - rate >= high_error_rate: base // 2, clamped to [min, max]
          - rate <= low_error_rate:  base * 2, clamped to [min, max]
          - otherwise:               base,     clamped to [min, max]

        Always returns an int >= 1.
        """
        with self._lock:
            rate = self._error_rate_ewma
        base = self._base.max_failures
        if rate >= self._cfg.high_error_rate:
            candidate = max(1, base // 2)
        elif rate <= self._cfg.low_error_rate:
            candidate = base * 2
        else:
            candidate = base
        return max(
            self._cfg.min_effective_max_failures,
            min(self._cfg.max_effective_max_failures, candidate),
        )

    def effective_reset_time(self) -> float:
        """Return the effective reset time based on recovery latency EWMA.

        Clamps recovery_latency_ewma to
        [min_effective_reset_seconds, max_effective_reset_seconds].
        """
        with self._lock:
            latency = self._recovery_latency_ewma
        return max(
            self._cfg.min_effective_reset_seconds,
            min(self._cfg.max_effective_reset_seconds, latency),
        )

    def reset_open_timer(self) -> None:
        """Clear _open_at without recording a latency sample.

        Used when the circuit breaker is administratively reset
        (not a natural recovery) to avoid poisoning the recovery EWMA
        with an arbitrary stale-timer delta on the next close.
        """
        with self._lock:
            self._open_at = None

    def snapshot(self) -> dict[str, Any]:
        """Return an observable snapshot for metrics and logs.

        Computed atomically under a single lock acquisition so returned
        values are point-in-time consistent.
        """
        with self._lock:
            rate = self._error_rate_ewma
            latency = self._recovery_latency_ewma
            open_at = self._open_at
        # Compute effective values from the captured rate/latency snapshot
        # (not from the live ewma fields) for point-in-time consistency.
        base = self._base.max_failures
        if rate >= self._cfg.high_error_rate:
            candidate = max(1, base // 2)
        elif rate <= self._cfg.low_error_rate:
            candidate = base * 2
        else:
            candidate = base
        effective_max = max(
            self._cfg.min_effective_max_failures,
            min(self._cfg.max_effective_max_failures, candidate),
        )
        effective_reset = max(
            self._cfg.min_effective_reset_seconds,
            min(self._cfg.max_effective_reset_seconds, latency),
        )
        return {
            "error_rate_ewma": rate,
            "recovery_latency_ewma": latency,
            "effective_max_failures": effective_max,
            "effective_reset_time": effective_reset,
            "open_at": open_at,
        }
