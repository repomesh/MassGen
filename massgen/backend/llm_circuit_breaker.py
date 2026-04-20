"""
LLM API Circuit Breaker with 429 classification.

Provides circuit breaker protection for LLM API calls with intelligent
handling of HTTP 429 responses based on Retry-After header analysis.

429 classification:
  WAIT -- Retry-After present and <= threshold: wait and retry (soft failure)
  STOP -- Retry-After present and > threshold: open CB immediately (quota exhaustion)
  CAP  -- No Retry-After: concurrency limit signal, backoff + retry (hard failure)

Public interface: should_block(), record_failure(), record_success() (single-endpoint).
"""

from __future__ import annotations

import asyncio
import enum
import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..logger_config import log_backend_activity
from .cb_store import DEFAULT_CIRCUIT_BREAKER_STATE

if TYPE_CHECKING:
    from massgen.observability.prometheus import CircuitBreakerMetrics

# ---------------------------------------------------------------------------
# 429 classification
# ---------------------------------------------------------------------------


class RateLimitAction(enum.Enum):
    """Classification of a 429 response."""

    WAIT = "wait"  # Retry-After <= threshold -- wait then retry
    STOP = "stop"  # Retry-After > threshold -- open CB, no retry
    CAP = "cap"  # No Retry-After -- backoff retry, record failure


# ---------------------------------------------------------------------------
# Circuit breaker states
# ---------------------------------------------------------------------------


class CircuitState(enum.Enum):
    """Standard three-state circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LLMCircuitBreakerConfig:
    """Configuration for the LLM circuit breaker."""

    enabled: bool = False  # opt-in, default preserves existing behavior
    max_failures: int = 5
    reset_time_seconds: int = 60
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 300.0
    retry_after_threshold_seconds: float = 120.0
    retryable_status_codes: list[int] = field(
        default_factory=lambda: [500, 502, 503, 529],
    )

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_failures < 1:
            raise ValueError(f"max_failures must be >= 1, got {self.max_failures}")
        if self.reset_time_seconds < 1:
            raise ValueError(
                f"reset_time_seconds must be >= 1, got {self.reset_time_seconds}",
            )
        if self.backoff_multiplier < 1.0:
            raise ValueError(
                f"backoff_multiplier must be >= 1.0, got {self.backoff_multiplier}",
            )
        if self.max_backoff_seconds < 1.0:
            raise ValueError(
                f"max_backoff_seconds must be >= 1.0, got {self.max_backoff_seconds}",
            )
        if self.retry_after_threshold_seconds < 0:
            raise ValueError(
                "retry_after_threshold_seconds must be >= 0, " f"got {self.retry_after_threshold_seconds}",
            )


# ---------------------------------------------------------------------------
# 429 classifier
# ---------------------------------------------------------------------------


def classify_429(
    retry_after_value: float | None,
    threshold: float,
) -> RateLimitAction:
    """Classify a 429 response based on Retry-After header.

    Args:
        retry_after_value: Parsed Retry-After in seconds, or None if absent.
        threshold: Maximum Retry-After to treat as WAIT (seconds).

    Returns:
        RateLimitAction indicating how to handle the 429.
    """
    if retry_after_value is None:
        return RateLimitAction.CAP
    if retry_after_value <= threshold:
        return RateLimitAction.WAIT
    return RateLimitAction.STOP


def extract_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After seconds from an Anthropic API exception.

    Checks response headers for 'retry-after' (case-insensitive).

    Returns:
        Seconds to wait, or None if header is absent or unparseable.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None

    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    # Case-insensitive lookup: SDK may return "Retry-After" or "retry-after"
    raw = None
    if hasattr(headers, "get"):
        for key in ("retry-after", "Retry-After"):
            raw = headers.get(key)
            if raw is not None:
                break
    if raw is None:
        return None

    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def extract_status_code(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception.

    Checks exc.status_code (anthropic SDK pattern) and exc.response.status_code.
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        return int(status)

    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if status is not None:
            return int(status)

    return None


# ---------------------------------------------------------------------------
# LLM Circuit Breaker
# ---------------------------------------------------------------------------


class LLMCircuitBreaker:
    """Circuit breaker for LLM API calls with 429 classification.

    Thread-safe via a lock. State machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    Public interface (similar to MCPCircuitBreaker but single-endpoint):
      - should_block()    -- check if requests should be blocked
      - record_failure()  -- record a failed API call
      - record_success()  -- record a successful API call

    Unlike MCPCircuitBreaker, this class tracks a single endpoint (no server_name key).
    """

    def __init__(
        self,
        config: LLMCircuitBreakerConfig | None = None,
        backend_name: str = "claude",
        metrics: CircuitBreakerMetrics | None = None,
        store: Any = None,
    ) -> None:
        self.config = config or LLMCircuitBreakerConfig()
        self.backend_name = backend_name
        self._metrics = metrics
        self._store: Any = store
        self._lock = threading.Lock()

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._open_until = 0.0  # monotonic deadline for OPEN state
        self._half_open_probe_active = False

    # -- Public interface ---------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state (read-only snapshot)."""
        if self._store is not None:
            return CircuitState(self._store.get_state(self.backend_name)["state"])
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Current failure count (read-only snapshot)."""
        if self._store is not None:
            return int(self._store.get_state(self.backend_name)["failure_count"])
        with self._lock:
            return self._failure_count

    def should_block(self) -> bool:
        """Check whether new requests should be blocked.

        Returns:
            True if the circuit is OPEN and reset time has not elapsed.
            In HALF_OPEN, allows exactly one probe request.
        """
        blocked, _ = self._should_block_with_claim()
        return blocked

    def _should_block_with_claim(self) -> tuple[bool, bool]:
        """Internal variant of should_block that also reports probe ownership.

        Returns:
            (should_block, claimed_probe). ``claimed_probe`` is True iff this
            call transitioned OPEN->HALF_OPEN or claimed the HALF_OPEN probe
            slot. Always False when should_block is True.
        """
        if not self.config.enabled:
            return False, False

        if self._store is not None:
            state = self._store.get_state(self.backend_name)
            circuit_state = CircuitState(state["state"])

            if circuit_state == CircuitState.CLOSED:
                return False, False

            if circuit_state == CircuitState.OPEN and time.time() < float(state["open_until"]):
                return True, False

            if circuit_state == CircuitState.HALF_OPEN and state["half_open_probe_active"]:
                return True, False

            # OPEN (elapsed) or HALF_OPEN (probe not claimed): single atomic op
            won, _new_state, transition = self._store.try_transition_and_claim_probe(
                self.backend_name,
                time.time(),
                float(self.config.reset_time_seconds),
            )
            if not won:
                return True, False

            if transition == "open->half_open":
                self._log("Circuit breaker half-open, allowing probe request")
                if self._metrics is not None:
                    self._safe_emit(
                        self._metrics.record_state_transition,
                        self.backend_name,
                        "open",
                        "half_open",
                    )
            return False, True

        _emit_transition: tuple[str, str] | None = None
        claimed_probe_local = False
        with self._lock:
            if self._state == CircuitState.CLOSED:
                should_block = False

            elif self._state == CircuitState.OPEN:
                now = time.monotonic()
                if now >= self._open_until:
                    # Transition to HALF_OPEN -- allow one probe
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_probe_active = True
                    self._log("Circuit breaker half-open, allowing probe request")
                    _emit_transition = ("open", "half_open")
                    should_block = False
                    claimed_probe_local = True
                else:
                    should_block = True

            else:
                # HALF_OPEN
                if self._half_open_probe_active:
                    # Probe already dispatched; block additional requests
                    should_block = True
                else:
                    # No probe active -- allow one
                    self._half_open_probe_active = True
                    should_block = False
                    claimed_probe_local = True

        if _emit_transition and self._metrics is not None:
            self._safe_emit(
                self._metrics.record_state_transition,
                self.backend_name,
                *_emit_transition,
            )
        return should_block, claimed_probe_local

    def record_failure(
        self,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record a failed API call. Increments failure counter.

        If max_failures is reached, transitions to OPEN.
        In HALF_OPEN, any failure transitions back to OPEN.
        """
        if not self.config.enabled:
            return

        if self._store is not None:
            new_state = self._store.atomic_record_failure(
                self.backend_name,
                self.config.max_failures,
                float(self.config.reset_time_seconds),
            )
            failure_count = int(new_state["failure_count"])
            new_state_str = new_state["state"]

            if new_state_str == CircuitState.OPEN.value:
                prev_was_half_open = bool(new_state.get("_prev_was_half_open", False))
                prev_label = str(new_state.get("_prev_state", "closed"))
                if prev_was_half_open:
                    self._log(
                        "Probe failed, circuit breaker re-opened",
                        failure_count=failure_count,
                        error_type=error_type,
                    )
                    if self._metrics is not None:
                        self._safe_emit(
                            self._metrics.record_state_transition,
                            self.backend_name,
                            "half_open",
                            "open",
                        )
                else:
                    self._log(
                        "Circuit breaker opened",
                        failure_count=failure_count,
                        error_type=error_type,
                    )
                    if self._metrics is not None:
                        self._safe_emit(
                            self._metrics.record_state_transition,
                            self.backend_name,
                            prev_label,  # now from _prev_state, never stale
                            "open",
                        )
            else:
                self._log(
                    "Failure recorded",
                    failure_count=failure_count,
                    max_failures=self.config.max_failures,
                    error_type=error_type,
                )
            return

        _transition_args: tuple[str, str, str] | None = None
        with self._lock:
            self._failure_count += 1
            now = time.monotonic()
            self._last_failure_time = now
            prev_state = self._state

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._open_until = now + self.config.reset_time_seconds
                self._half_open_probe_active = False
                self._log(
                    "Probe failed, circuit breaker re-opened",
                    failure_count=self._failure_count,
                    error_type=error_type,
                )
                if self._metrics is not None:
                    _transition_args = (self.backend_name, "half_open", "open")

            elif self._failure_count >= self.config.max_failures:
                self._state = CircuitState.OPEN
                self._open_until = now + self.config.reset_time_seconds
                self._log(
                    "Circuit breaker opened",
                    failure_count=self._failure_count,
                    error_type=error_type,
                )
                if self._metrics is not None:
                    _transition_args = (self.backend_name, prev_state.value, "open")
            else:
                self._log(
                    "Failure recorded",
                    failure_count=self._failure_count,
                    max_failures=self.config.max_failures,
                    error_type=error_type,
                )

        if _transition_args is not None and self._metrics is not None:
            self._safe_emit(
                self._metrics.record_state_transition,
                *_transition_args,
            )

    def record_success(self) -> None:
        """Record a successful API call. Resets failure counter and closes circuit."""
        if not self.config.enabled:
            return

        if self._store is not None:
            new_state = self._store.atomic_record_success(self.backend_name)
            prev_state_str = str(new_state.get("_prev_state", new_state["state"]))

            if prev_state_str != CircuitState.CLOSED.value and new_state["state"] == CircuitState.CLOSED.value:
                self._log(
                    "Circuit breaker closed after success",
                    previous_state=prev_state_str,
                )
                if self._metrics is not None:
                    self._safe_emit(
                        self._metrics.record_state_transition,
                        self.backend_name,
                        prev_state_str,
                        "closed",
                    )
            return

        _transition_args: tuple[str, str, str] | None = None
        with self._lock:
            prev_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_probe_active = False

            if prev_state != CircuitState.CLOSED:
                self._log(
                    "Circuit breaker closed after success",
                    previous_state=prev_state.value,
                )
                if self._metrics is not None:
                    _transition_args = (self.backend_name, prev_state.value, "closed")

        if _transition_args is not None and self._metrics is not None:
            self._safe_emit(
                self._metrics.record_state_transition,
                *_transition_args,
            )

    def force_open(self, reason: str = "", open_for_seconds: float = 0) -> None:
        """Force the circuit to OPEN state (e.g. on 429 STOP).

        Args:
            reason: Human-readable reason for logging.
            open_for_seconds: Minimum seconds to keep OPEN. If > reset_time_seconds,
                overrides the default. Used to honor Retry-After from 429 STOP.
        """
        if not self.config.enabled:
            return

        if self._store is not None:
            now = time.time()
            duration = max(self.config.reset_time_seconds, open_for_seconds)
            computed_open_until = now + duration
            prev_state_value = CircuitState.CLOSED.value
            _MAX_CAS_ATTEMPTS = 5
            for _attempt in range(_MAX_CAS_ATTEMPTS):
                current = self._store.get_state(self.backend_name)
                prev_state_value = current.get("state", CircuitState.CLOSED.value)
                # Preserve longer open_until and more recent failure time
                # if a concurrent force_open has already written a later value.
                merged_open_until = max(computed_open_until, float(current.get("open_until", 0)))
                merged_last_failure = max(now, float(current.get("last_failure_time", 0)))
                updates = {
                    "state": CircuitState.OPEN.value,
                    "last_failure_time": merged_last_failure,
                    "open_until": merged_open_until,
                    "half_open_probe_active": False,
                }
                applied = self._store.cas_state(self.backend_name, prev_state_value, updates)
                if applied:
                    break
                # CAS conflict -- retry with refreshed state
            else:
                # All CAS attempts exhausted. Blind set_state risks overwriting a
                # fresher open_until written by a concurrent writer. Log a warning
                # and rely on the circuit to self-heal via the next record_failure.
                self._log(
                    "force_open: CAS exhausted after 5 attempts; skipping fallback set_state",
                    open_for_seconds=duration,
                )
            self._log(
                f"Circuit breaker force-opened: {reason}",
                open_for_seconds=duration,
            )
            if self._metrics is not None:
                self._safe_emit(
                    self._metrics.record_state_transition,
                    self.backend_name,
                    prev_state_value,
                    "open",
                )
            return

        _transition_args: tuple[str, str, str] | None = None
        with self._lock:
            now = time.monotonic()
            prev_state = self._state
            self._state = CircuitState.OPEN
            self._last_failure_time = now
            duration = max(self.config.reset_time_seconds, open_for_seconds)
            self._open_until = now + duration
            self._half_open_probe_active = False
            self._log(f"Circuit breaker force-opened: {reason}", open_for_seconds=duration)
            if self._metrics is not None:
                _transition_args = (self.backend_name, prev_state.value, "open")

        if _transition_args is not None and self._metrics is not None:
            self._safe_emit(
                self._metrics.record_state_transition,
                *_transition_args,
            )

    def reset(self) -> None:
        """Reset circuit breaker to initial CLOSED state."""
        if self._store is not None:
            prev_state_value = self._store.get_state(self.backend_name).get(
                "state",
                CircuitState.CLOSED.value,
            )
            self._store.set_state(
                self.backend_name,
                dict(DEFAULT_CIRCUIT_BREAKER_STATE),
            )
            if self._metrics is not None and prev_state_value != CircuitState.CLOSED.value:
                self._safe_emit(
                    self._metrics.record_state_transition,
                    self.backend_name,
                    prev_state_value,
                    "closed",
                )
            return

        _transition_args: tuple[str, str, str] | None = None
        with self._lock:
            prev_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._open_until = 0.0
            self._half_open_probe_active = False
            if self._metrics is not None and prev_state != CircuitState.CLOSED:
                _transition_args = (self.backend_name, prev_state.value, "closed")

        if _transition_args is not None and self._metrics is not None:
            self._safe_emit(
                self._metrics.record_state_transition,
                *_transition_args,
            )

    # -- 429-aware retry wrapper --------------------------------------------

    async def call_with_retry(
        self,
        coro_factory: Any,  # Callable[[], Awaitable[T]]
        *,
        max_retries: int = 3,
        agent_id: str | None = None,
    ) -> Any:
        """Execute an async API call with circuit breaker protection and 429 handling.

        Args:
            coro_factory: Zero-arg callable that returns an awaitable for the API call.
            max_retries: Maximum number of retry attempts for retryable errors.
            agent_id: Optional agent ID for logging.

        Returns:
            The result of the API call.

        Raises:
            The original exception if not retryable, CB is open, or retries exhausted.
        """
        if not self.config.enabled:
            return await coro_factory()

        _initial_blocked, _initial_claimed = self._should_block_with_claim()
        if _initial_blocked:
            # Note: state is read after the gate check for the error message
            # and metric label. Under high concurrency, the state may transition
            # between the gate and this read (e.g. OPEN->HALF_OPEN). The outcome
            # label is best-effort; the rejection decision itself is authoritative.
            if self._store is not None:
                state_label = self.state.value
            else:
                with self._lock:
                    state_label = self._state.value
            outcome = "rejected_open" if state_label == "open" else "rejected_half_open"
            if self._metrics is not None:
                self._safe_emit(self._metrics.record_request, self.backend_name, outcome, 0.0)
            raise CircuitBreakerOpenError(
                f"Circuit breaker is {state_label} for {self.backend_name}",
            )

        last_exc: Exception | None = None
        delay = 1.0  # initial backoff for CAP / retryable errors
        _owns_probe = _initial_claimed

        try:
            for attempt in range(1, max_retries + 1):
                # Re-check CB state at start of each attempt
                if attempt > 1:
                    _retry_blocked, _retry_claimed = self._should_block_with_claim()
                    if _retry_claimed:
                        _owns_probe = True
                    if _retry_blocked:
                        if self._store is not None:
                            state_label = self.state.value
                        else:
                            with self._lock:
                                state_label = self._state.value
                        outcome = "rejected_open" if state_label == "open" else "rejected_half_open"
                        if self._metrics is not None:
                            self._safe_emit(self._metrics.record_request, self.backend_name, outcome, 0.0)
                        raise CircuitBreakerOpenError(
                            f"Circuit breaker became {state_label} during retries " f"for {self.backend_name}",
                        )

                _t0 = time.perf_counter()
                try:
                    result = await coro_factory()
                    _latency = time.perf_counter() - _t0
                    self.record_success()
                    if self._metrics is not None:
                        self._safe_emit(self._metrics.record_request, self.backend_name, "success", _latency)
                    return result

                except Exception as exc:
                    _latency = time.perf_counter() - _t0
                    last_exc = exc
                    status_code = extract_status_code(exc)

                    # --- 429 handling with classification ---
                    if status_code == 429:
                        retry_after = extract_retry_after(exc)
                        action = classify_429(
                            retry_after,
                            self.config.retry_after_threshold_seconds,
                        )

                        if action == RateLimitAction.STOP:
                            # Quota exhaustion -- open CB for full Retry-After window
                            self.force_open(
                                f"429 STOP: Retry-After={retry_after}s > " "threshold=" f"{self.config.retry_after_threshold_seconds}s",
                                open_for_seconds=retry_after or 0,
                            )
                            if self._metrics is not None:
                                self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                            raise

                        if action == RateLimitAction.WAIT:
                            # Short wait -- record per-attempt latency then retry
                            if self._metrics is not None:
                                self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                            if attempt >= max_retries:
                                raise
                            wait_seconds = retry_after if retry_after is not None else 1.0
                            self._log(
                                "429 WAIT: retrying after Retry-After",
                                retry_after=wait_seconds,
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            await asyncio.sleep(wait_seconds)
                            continue

                        # CAP -- no Retry-After, backoff + record failure
                        self.record_failure(
                            error_type="429_cap",
                            error_message=str(exc)[:200],
                        )
                        if attempt < max_retries:
                            jittered = delay * random.uniform(0.8, 1.2)  # noqa: S311
                            self._log(
                                "429 CAP: backoff retry",
                                delay=round(jittered, 2),
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            # Emit per-attempt failure metric before retry sleep (BUG 2 fix)
                            if self._metrics is not None:
                                self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                            await asyncio.sleep(jittered)
                            delay = min(
                                delay * self.config.backoff_multiplier,
                                self.config.max_backoff_seconds,
                            )
                            continue
                        if self._metrics is not None:
                            self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                        raise

                    # --- Other retryable status codes ---
                    if status_code in self.config.retryable_status_codes:
                        self.record_failure(
                            error_type=f"http_{status_code}",
                            error_message=str(exc)[:200],
                        )
                        _retry_blocked2, _retry_claimed2 = self._should_block_with_claim()
                        if _retry_claimed2:
                            _owns_probe = True
                        if attempt < max_retries and not _retry_blocked2:
                            jittered = delay * random.uniform(0.8, 1.2)  # noqa: S311
                            self._log(
                                f"Retryable error (HTTP {status_code}), backing off",
                                delay=round(jittered, 2),
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            # Emit per-attempt failure metric before retry sleep (BUG 2 fix)
                            if self._metrics is not None:
                                self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                            await asyncio.sleep(jittered)
                            delay = min(
                                delay * self.config.backoff_multiplier,
                                self.config.max_backoff_seconds,
                            )
                            continue
                        if self._metrics is not None:
                            self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                        raise

                    # --- Non-retryable error ---
                    if self._metrics is not None:
                        self._safe_emit(self._metrics.record_request, self.backend_name, "failure", _latency)
                    raise

            # Defensive fallback
            if last_exc:
                raise last_exc
            raise RuntimeError("call_with_retry ended without result or exception")

        except BaseException:
            # Ensure HALF_OPEN probe flag is cleared on any terminal exit
            # to prevent wedging the CB in a permanently blocked state.
            _transition_args: tuple[str, str, str] | None = None
            if _owns_probe:
                if self._store is not None:
                    # Use CAS to avoid overwriting a longer open_until written
                    # concurrently (e.g. force_open from another coroutine).
                    _probe_now = time.time()
                    _probe_open_until = _probe_now + self.config.reset_time_seconds
                    _probe_applied = self._store.cas_state(
                        self.backend_name,
                        CircuitState.HALF_OPEN.value,
                        {
                            "state": CircuitState.OPEN.value,
                            "open_until": _probe_open_until,
                            "half_open_probe_active": False,
                        },
                    )
                    if _probe_applied:
                        self._log(
                            "Probe terminated abnormally, circuit breaker re-opened",
                        )
                        if self._metrics is not None:
                            self._safe_emit(
                                self._metrics.record_state_transition,
                                self.backend_name,
                                "half_open",
                                "open",
                            )
                else:
                    with self._lock:
                        if self._state == CircuitState.HALF_OPEN and self._half_open_probe_active:
                            self._state = CircuitState.OPEN
                            self._open_until = time.monotonic() + self.config.reset_time_seconds
                            self._half_open_probe_active = False
                            self._log("Probe terminated abnormally, circuit breaker re-opened")
                            if self._metrics is not None:
                                _transition_args = (self.backend_name, "half_open", "open")
                    if _transition_args is not None and self._metrics is not None:
                        self._safe_emit(
                            self._metrics.record_state_transition,
                            *_transition_args,
                        )
            raise

    # -- Internal helpers ---------------------------------------------------

    def _safe_emit(self, method: Any, *args: Any) -> None:
        """Call a metrics method, swallowing all exceptions.

        Observability failures must never affect circuit breaker behavior or
        cause a successful API response to be treated as a failure.
        """
        try:
            method(*args)
        except Exception:  # noqa: BLE001
            pass

    def _log(self, message: str, **details: Any) -> None:
        """Log via structured backend activity logger."""
        log_details: dict[str, Any] = {k: v for k, v in details.items() if v is not None}
        log_backend_activity(
            self.backend_name,
            message,
            log_details if log_details else None,
            agent_id=details.get("agent_id"),
        )

    def __repr__(self) -> str:
        if self._store is not None:
            state = self.state.value
            failures = self.failure_count
            return f"LLMCircuitBreaker(state={state}, " f"failures={failures}/{self.config.max_failures}, " f"backend={self.backend_name!r})"
        with self._lock:
            state = self._state.value
            failures = self._failure_count
        return f"LLMCircuitBreaker(state={state}, " f"failures={failures}/{self.config.max_failures}, " f"backend={self.backend_name!r})"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and blocking requests."""
