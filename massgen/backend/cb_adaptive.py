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

        Applies ``new = (1 - alpha) * old + alpha * sample`` where
        sample is 1.0 for a failure and 0.0 for a success. The result
        is clamped to [0.0, 1.0] to guard against floating-point drift.

        Args:
            is_failure: True if the request failed, False if it succeeded.
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

    def _compute_effective_max(self, rate: float) -> int:
        """Map an error-rate sample to the effective failure threshold.

        Pure function: does not read live state. Callers that need
        point-in-time consistency with other fields (see ``snapshot``)
        capture the rate under ``self._lock`` and pass it here.

        Args:
            rate: Error-rate EWMA value, expected in [0.0, 1.0].

        Returns:
            Clamped threshold int in
            [min_effective_max_failures, max_effective_max_failures].
        """
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

    def _compute_effective_reset(self, latency: float) -> float:
        """Clamp a latency sample to the configured reset-time bounds.

        Pure function, same capture-and-pass contract as
        ``_compute_effective_max``.

        Args:
            latency: Recovery-latency EWMA value in seconds.

        Returns:
            Clamped value in
            [min_effective_reset_seconds, max_effective_reset_seconds].
        """
        return max(
            self._cfg.min_effective_reset_seconds,
            min(self._cfg.max_effective_reset_seconds, latency),
        )

    def effective_max_failures(self) -> int:
        """Return the effective failure threshold given current EWMA error rate.

        Returns:
            Clamped threshold int. See ``_compute_effective_max`` for the
            branch logic (high/low/middle zones).
        """
        with self._lock:
            rate = self._error_rate_ewma
        return self._compute_effective_max(rate)

    def effective_reset_time(self) -> float:
        """Return the effective reset time based on recovery latency EWMA.

        Returns:
            Clamped value in
            [min_effective_reset_seconds, max_effective_reset_seconds].
        """
        with self._lock:
            latency = self._recovery_latency_ewma
        return self._compute_effective_reset(latency)

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

        All live fields are captured under a single lock acquisition so
        returned values are point-in-time consistent. Derived fields
        (effective_max_failures, effective_reset_time) are computed from
        the captured rate/latency via pure helpers, not re-read from the
        live EWMA.

        Returns:
            Dict with keys: error_rate_ewma (float), recovery_latency_ewma
            (float), effective_max_failures (int), effective_reset_time
            (float), open_at (float | None).
        """
        with self._lock:
            rate = self._error_rate_ewma
            latency = self._recovery_latency_ewma
            open_at = self._open_at
        return {
            "error_rate_ewma": rate,
            "recovery_latency_ewma": latency,
            "effective_max_failures": self._compute_effective_max(rate),
            "effective_reset_time": self._compute_effective_reset(latency),
            "open_at": open_at,
        }
