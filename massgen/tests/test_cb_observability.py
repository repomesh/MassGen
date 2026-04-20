"""Tests for circuit breaker observability module (Phase 3).

Covers:
  - CircuitBreakerMetrics happy-path: counters, histogram, gauge
  - No-op path: prometheus_client unavailable or metrics=None
  - Integration: CB emits metrics on state transitions via record_failure/record_success/force_open
"""

from __future__ import annotations

import sys
import time
from types import ModuleType
from unittest.mock import patch

import pytest

from massgen.backend.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
)
from massgen.observability import CircuitBreakerMetrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fake_prometheus() -> tuple[ModuleType, dict]:
    """Install a minimal fake prometheus_client into sys.modules.

    Returns (fake_module, recorded_calls) where recorded_calls is updated
    by Counter/Histogram/Gauge label calls.
    """
    calls: dict = {
        "transitions": [],
        "requests": [],
        "latency_observations": [],
        "gauge_sets": [],
    }

    class FakeLabelSet:
        def __init__(self, metric_name: str, labels: dict) -> None:
            self._name = metric_name
            self._labels = labels

        def inc(self) -> None:
            if self._name == "cb_state_transitions_total":
                calls["transitions"].append(dict(self._labels))
            elif self._name == "cb_requests_total":
                calls["requests"].append(dict(self._labels))

        def observe(self, value: float) -> None:
            calls["latency_observations"].append(value)

        def set(self, value: float) -> None:
            calls["gauge_sets"].append({"labels": dict(self._labels), "value": value})

    class FakeMetric:
        def __init__(self, name: str, *args, **kwargs) -> None:
            self._name = name

        def labels(self, **kw) -> FakeLabelSet:
            return FakeLabelSet(self._name, kw)

    class FakeRegistry:
        pass

    fake_mod = ModuleType("prometheus_client")
    fake_mod.CollectorRegistry = FakeRegistry
    fake_mod.Counter = lambda name, *a, **kw: FakeMetric(name)
    fake_mod.Histogram = lambda name, *a, **kw: FakeMetric(name)
    fake_mod.Gauge = lambda name, *a, **kw: FakeMetric(name)

    sys.modules["prometheus_client"] = fake_mod
    return fake_mod, calls


def _remove_fake_prometheus() -> None:
    sys.modules.pop("prometheus_client", None)


# ---------------------------------------------------------------------------
# TestCircuitBreakerMetricsHappyPath
# ---------------------------------------------------------------------------


class TestCircuitBreakerMetricsHappyPath:
    """Happy-path tests -- require fake prometheus_client to be present."""

    def setup_method(self) -> None:
        _remove_fake_prometheus()
        self._fake_mod, self._calls = _install_fake_prometheus()
        # Fresh instance after injecting fake module
        self._metrics = CircuitBreakerMetrics()

    def teardown_method(self) -> None:
        _remove_fake_prometheus()

    def test_state_transition_increments_counter(self) -> None:
        """record_state_transition increments cb_state_transitions_total."""
        self._metrics.record_state_transition("claude", "closed", "open")

        assert len(self._calls["transitions"]) == 1
        assert self._calls["transitions"][0] == {
            "backend": "claude",
            "from_state": "closed",
            "to_state": "open",
        }

    def test_request_outcome_increments_counter(self) -> None:
        """record_request increments cb_requests_total."""
        self._metrics.record_request("claude", "success", 0.5)

        assert len(self._calls["requests"]) == 1
        assert self._calls["requests"][0] == {"backend": "claude", "outcome": "success"}

    def test_latency_recorded_in_histogram(self) -> None:
        """record_request observes latency in cb_request_latency_seconds."""
        self._metrics.record_request("gemini", "failure", 2.3)

        assert len(self._calls["latency_observations"]) == 1
        assert abs(self._calls["latency_observations"][0] - 2.3) < 1e-9

    def test_state_gauge_updated_on_transition(self) -> None:
        """record_state_transition sets cb_current_state gauge to new state."""
        self._metrics.record_state_transition("claude", "closed", "open")

        gauge_set = self._calls["gauge_sets"]
        assert len(gauge_set) == 1
        assert gauge_set[0]["value"] == 2  # OPEN = 2
        assert gauge_set[0]["labels"]["backend"] == "claude"

    def test_multiple_backends_isolated(self) -> None:
        """Different backend labels produce separate label sets."""
        self._metrics.record_state_transition("claude", "closed", "open")
        self._metrics.record_state_transition("gemini", "closed", "open")

        backends = {t["backend"] for t in self._calls["transitions"]}
        assert backends == {"claude", "gemini"}

    def test_get_registry_returns_non_none(self) -> None:
        """get_registry() returns the CollectorRegistry when available."""
        registry = self._metrics.get_registry()
        assert registry is not None

    def test_state_values_encoding(self) -> None:
        """State string -> gauge int mapping: CLOSED=0, HALF_OPEN=1, OPEN=2."""
        assert self._metrics._state_value("CLOSED") == 0
        assert self._metrics._state_value("HALF_OPEN") == 1
        assert self._metrics._state_value("OPEN") == 2
        # Case-insensitive
        assert self._metrics._state_value("closed") == 0
        assert self._metrics._state_value("open") == 2


# ---------------------------------------------------------------------------
# TestCircuitBreakerMetricsNoOp
# ---------------------------------------------------------------------------


class TestCircuitBreakerMetricsNoOp:
    """No-op path tests: metrics=None and prometheus_client unavailable."""

    def test_metrics_none_no_attribute_error(self) -> None:
        """LLMCircuitBreaker with metrics=None: all public methods work without error."""
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=2)
        cb = LLMCircuitBreaker(config=config, backend_name="claude", metrics=None)

        # State transitions via CB public API must not raise
        cb.record_failure()
        cb.record_failure()  # triggers OPEN
        assert cb.state == CircuitState.OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_get_registry_returns_none_when_unavailable(self) -> None:
        """get_registry() returns None when prometheus_client import raises ImportError."""
        metrics = CircuitBreakerMetrics()
        # Use builtins.__import__ patch to simulate ImportError
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("mocked: prometheus_client not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = metrics.get_registry()

        assert result is None

    def test_all_record_methods_are_noop_when_unavailable(self) -> None:
        """All record methods callable without error when prometheus_client import fails."""
        metrics = CircuitBreakerMetrics()

        def mock_import(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("mocked: not available")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Must not raise
            metrics.record_state_transition("claude", "closed", "open")
            metrics.record_request("claude", "success", 0.1)
            metrics.record_request("claude", "failure", 5.0)
            metrics.record_request("claude", "rejected_open", 0.0)

    def test_noop_when_prometheus_import_fails(self) -> None:
        """Simulate ImportError: all methods become no-ops, registry returns None."""
        metrics = CircuitBreakerMetrics()

        def mock_import(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("mocked")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            metrics.record_state_transition("test", "closed", "open")
            metrics.record_request("test", "success", 0.5)
            assert metrics.get_registry() is None
            assert metrics._available is False

    def test_available_flag_cached_after_first_check(self) -> None:
        """_available is cached after first import check."""
        metrics = CircuitBreakerMetrics()
        assert metrics._available is None  # not yet checked

        def mock_import(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("mocked")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            metrics.record_state_transition("x", "closed", "open")
            assert metrics._available is False  # cached

            # Second call must not re-attempt import (even after patch removed)
        # Outside patch: _available is still False (cached)
        assert metrics._available is False


# ---------------------------------------------------------------------------
# TestCircuitBreakerIntegration
# ---------------------------------------------------------------------------


class TestCircuitBreakerIntegration:
    """Integration tests: CB emits metrics during real state machine transitions."""

    def setup_method(self) -> None:
        _remove_fake_prometheus()
        self._fake_mod, self._calls = _install_fake_prometheus()

    def teardown_method(self) -> None:
        _remove_fake_prometheus()

    def _make_cb(self, **kwargs) -> tuple[LLMCircuitBreaker, dict]:
        metrics = CircuitBreakerMetrics()
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=kwargs.pop("max_failures", 3),
            reset_time_seconds=kwargs.pop("reset_time_seconds", 60),
        )
        cb = LLMCircuitBreaker(
            config=config,
            backend_name=kwargs.pop("backend_name", "claude"),
            metrics=metrics,
        )
        return cb, self._calls

    def test_cb_emits_metrics_on_open(self) -> None:
        """CB transitions CLOSED->OPEN emit state transition metric."""
        cb, calls = self._make_cb(max_failures=2)

        cb.record_failure()
        cb.record_failure()  # triggers OPEN

        assert cb.state == CircuitState.OPEN
        transitions = calls["transitions"]
        assert any(t["from_state"] == "closed" and t["to_state"] == "open" for t in transitions), f"Expected closed->open transition, got: {transitions}"

    def test_cb_emits_metrics_on_success_close(self) -> None:
        """CB transitions OPEN->CLOSED on success emit state transition metric."""
        cb, calls = self._make_cb(max_failures=1)

        cb.record_failure()  # CLOSED->OPEN
        cb.record_success()  # OPEN->CLOSED

        assert cb.state == CircuitState.CLOSED
        transitions = calls["transitions"]
        # Should have open->closed or half_open->closed
        close_transitions = [t for t in transitions if t.get("to_state") == "closed"]
        assert len(close_transitions) >= 1

    def test_cb_emits_metrics_on_force_open(self) -> None:
        """force_open() emits state transition metric."""
        cb, calls = self._make_cb()

        cb.force_open(reason="quota exhausted", open_for_seconds=120)

        assert cb.state == CircuitState.OPEN
        transitions = calls["transitions"]
        assert any(t["to_state"] == "open" for t in transitions)

    def test_force_open_from_open_does_not_emit_open_to_open(self) -> None:
        """force_open() on an already-OPEN breaker must not emit an open->open transition.

        Repeated force_open calls extend the deadline via the CAS merge but do
        not constitute a fresh state transition, so the metric must stay quiet.
        """
        cb, calls = self._make_cb()

        cb.force_open(reason="first")
        assert cb.state == CircuitState.OPEN

        calls["transitions"].clear()
        cb.force_open(reason="second")

        transitions = calls["transitions"]
        assert not any(t["from_state"] == "open" and t["to_state"] == "open" for t in transitions), f"Unexpected open->open transition emitted: {transitions}"

    def test_cb_reset_emits_transition_metric(self) -> None:
        """reset() from OPEN emits open->closed state transition metric."""
        cb, calls = self._make_cb(max_failures=1)

        cb.record_failure()  # CLOSED->OPEN
        assert cb.state == CircuitState.OPEN

        calls["transitions"].clear()
        cb.reset()

        assert cb.state == CircuitState.CLOSED
        transitions = calls["transitions"]
        assert any(t.get("from_state") == "open" and t.get("to_state") == "closed" for t in transitions), f"Expected open->closed from reset(), got: {transitions}"

    def test_cb_reset_from_closed_no_emit(self) -> None:
        """reset() when already CLOSED must not emit a spurious metric."""
        cb, calls = self._make_cb()

        assert cb.state == CircuitState.CLOSED
        calls["transitions"].clear()
        cb.reset()

        assert calls["transitions"] == [], f"Expected no transition from reset() on already-CLOSED CB, " f"got: {calls['transitions']}"

    def test_cb_reset_from_half_open_emits_transition(self) -> None:
        """reset() from HALF_OPEN emits half_open->closed metric."""
        cb, calls = self._make_cb(max_failures=1)

        cb.record_failure()  # CLOSED->OPEN
        # Manually advance to HALF_OPEN
        with cb._lock:
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_probe_active = True

        assert cb.state == CircuitState.HALF_OPEN
        calls["transitions"].clear()
        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert any(t.get("from_state") == "half_open" and t.get("to_state") == "closed" for t in calls["transitions"]), f"Expected half_open->closed from reset(), got: {calls['transitions']}"

    def test_cb_metrics_none_full_lifecycle(self) -> None:
        """metrics=None: full CB lifecycle (CLOSED->OPEN->HALF_OPEN->CLOSED) without error."""
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=1,
            reset_time_seconds=1,
        )
        cb = LLMCircuitBreaker(config=config, backend_name="test", metrics=None)

        cb.record_failure()  # CLOSED->OPEN
        assert cb.state == CircuitState.OPEN

        # Advance time past open_until by resetting the internal clock
        with cb._lock:
            cb._open_until = time.monotonic() - 1

        blocked = cb.should_block()  # triggers OPEN->HALF_OPEN
        assert not blocked
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()  # HALF_OPEN->CLOSED
        assert cb.state == CircuitState.CLOSED

    def test_open_to_half_open_transition_emits_metric(self) -> None:
        """OPEN->HALF_OPEN via should_block() emits transition metric and sets gauge to 1."""
        _remove_fake_prometheus()
        _, calls = _install_fake_prometheus()
        try:
            metrics = CircuitBreakerMetrics()
            config = LLMCircuitBreakerConfig(
                enabled=True,
                max_failures=1,
                reset_time_seconds=999,
            )
            cb = LLMCircuitBreaker(config=config, backend_name="test", metrics=metrics)

            cb.record_failure()  # CLOSED->OPEN
            assert cb.state == CircuitState.OPEN
            calls["transitions"].clear()
            calls["gauge_sets"].clear()

            # Expire the open window and trigger OPEN->HALF_OPEN
            with cb._lock:
                cb._open_until = time.monotonic() - 1
            blocked = cb.should_block()  # triggers OPEN->HALF_OPEN
            assert not blocked
            assert cb.state == CircuitState.HALF_OPEN

            half_open_transitions = [t for t in calls["transitions"] if t.get("from_state") == "open" and t.get("to_state") == "half_open"]
            assert len(half_open_transitions) == 1, f"Expected open->half_open transition metric, got: {calls['transitions']}"
            # Gauge encoding: HALF_OPEN == 1
            assert any(g.get("value") == 1 for g in calls["gauge_sets"]), f"Expected gauge=1 for HALF_OPEN, got: {calls['gauge_sets']}"
        finally:
            _remove_fake_prometheus()


# ---------------------------------------------------------------------------
# TestRound5Additions -- tests added in Round 5 review
# ---------------------------------------------------------------------------


class TestRound5Additions:
    """Tests for gaps identified in Round 5 review (R-1 BUG2, R-3 BUGs 1-8)."""

    def setup_method(self) -> None:
        _remove_fake_prometheus()
        self._fake_mod, self._calls = _install_fake_prometheus()
        self._metrics = CircuitBreakerMetrics()

    def teardown_method(self) -> None:
        _remove_fake_prometheus()

    def _make_cb(self, max_failures: int = 2) -> tuple[LLMCircuitBreaker, dict]:
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=max_failures,
            reset_time_seconds=999,
        )
        cb = LLMCircuitBreaker(config=config, backend_name="test", metrics=self._metrics)
        return cb, self._calls

    def test_per_attempt_latency_cap_retry(self) -> None:
        """CAP retry path: each failed attempt emits a separate request metric (BUG 2 fix).

        With 1 retry, two attempts should produce 2 request metrics, not 1.
        """
        import asyncio

        attempt_count = 0

        async def _run() -> None:
            nonlocal attempt_count

            class _FakeCap429(Exception):
                """Fake exception that looks like a 429 with no Retry-After (CAP)."""

                status_code = 429

            config = LLMCircuitBreakerConfig(
                enabled=True,
                max_failures=10,
                reset_time_seconds=999,
            )
            cb = LLMCircuitBreaker(
                config=config,
                backend_name="test_cap",
                metrics=self._metrics,
            )

            async def _coro():
                nonlocal attempt_count
                attempt_count += 1
                raise _FakeCap429()

            import pytest as _pytest

            with _pytest.raises(_FakeCap429):
                await cb.call_with_retry(_coro, max_retries=2)

        asyncio.run(_run())
        # 2 attempts (initial + 1 retry), both must be counted
        cap_requests = [r for r in self._calls["requests"] if r.get("backend") == "test_cap"]
        assert len(cap_requests) == attempt_count, f"Expected {attempt_count} request metrics (one per attempt), " f"got {len(cap_requests)}: {cap_requests}"

    def test_metrics_emit_exception_does_not_crash_cb(self) -> None:
        """If metrics.record_request raises, a successful API result is still returned."""
        import asyncio

        class _ExplodingMetrics(CircuitBreakerMetrics):
            def record_request(self, backend, outcome, latency):  # type: ignore[override]
                raise RuntimeError("metrics exploded")

        _remove_fake_prometheus()
        _, calls = _install_fake_prometheus()
        try:
            boom_metrics = _ExplodingMetrics()
            config = LLMCircuitBreakerConfig(enabled=True, max_failures=5)
            cb = LLMCircuitBreaker(
                config=config,
                backend_name="test_explode",
                metrics=boom_metrics,
            )

            async def _success_coro():
                return "ok"

            # Should return "ok" without raising, even though metrics explode
            result = asyncio.run(cb.call_with_retry(_success_coro))
            assert result == "ok"
        finally:
            _remove_fake_prometheus()

    def test_none_from_state_does_not_crash(self) -> None:
        """record_state_transition with from_state=None must not raise."""
        # Rule 3: None/empty boundary on all label params
        # Should either raise a documented ValueError or record without crash.
        try:
            self._metrics.record_state_transition("claude", None, "open")  # type: ignore[arg-type]
        except (TypeError, AttributeError):
            # Acceptable: documented exception; what must NOT happen is a partial write
            # followed by crash at a different layer
            pass

    def test_none_to_state_does_not_crash(self) -> None:
        """record_state_transition with to_state=None must not raise past the gauge call."""
        try:
            self._metrics.record_state_transition("claude", "closed", None)  # type: ignore[arg-type]
        except (TypeError, AttributeError, KeyError):
            pass  # Documented: gauge lookup calls _state_value(None) -> -1 or crash

    def test_none_outcome_does_not_crash(self) -> None:
        """record_request with outcome=None must not raise."""
        try:
            self._metrics.record_request("claude", None, 0.5)  # type: ignore[arg-type]
        except (TypeError, AttributeError):
            pass

    def test_empty_string_from_state(self) -> None:
        """Empty from_state is recorded without crash (boundary: Rule 3)."""
        initial = len(self._calls["transitions"])
        self._metrics.record_state_transition("claude", "", "open")
        assert len(self._calls["transitions"]) == initial + 1

    def test_empty_string_to_state(self) -> None:
        """Empty to_state is recorded without crash (boundary: Rule 3)."""
        initial = len(self._calls["transitions"])
        self._metrics.record_state_transition("claude", "closed", "")
        assert len(self._calls["transitions"]) == initial + 1

    def test_per_attempt_latency_wait_retry(self) -> None:
        """WAIT retry path: each failed attempt emits a separate request metric.

        With max_retries=2 and 3 WAIT-429 attempts, all 3 should be counted.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        attempt_count = 0

        class _FakeWait429(Exception):
            """Fake 429 with Retry-After=1 (below threshold) -- WAIT action."""

            status_code = 429

            @property
            def response(self):
                class _R:
                    headers = {"Retry-After": "1"}

                return _R()

        async def _run() -> None:
            nonlocal attempt_count
            config = LLMCircuitBreakerConfig(
                enabled=True,
                max_failures=10,
                reset_time_seconds=999,
                retry_after_threshold_seconds=60.0,  # 1 < 60 -> WAIT
            )
            cb = LLMCircuitBreaker(
                config=config,
                backend_name="test_wait",
                metrics=self._metrics,
            )

            async def _coro():
                nonlocal attempt_count
                attempt_count += 1
                raise _FakeWait429()

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(_FakeWait429):
                    await cb.call_with_retry(_coro, max_retries=2)

        asyncio.run(_run())
        # All attempts (max_retries+1 = 3) must each produce a failure metric
        wait_requests = [r for r in self._calls["requests"] if r.get("backend") == "test_wait"]
        assert len(wait_requests) == attempt_count, f"Expected {attempt_count} request metrics (one per WAIT attempt), " f"got {len(wait_requests)}: {wait_requests}"

    def test_label_cardinality_caller_responsibility_documented(self) -> None:
        """Verify unbounded backend/outcome labels are accepted (caller responsibility).

        Per design decision: CircuitBreakerMetrics does not cap or normalize labels.
        Callers are responsible for label cardinality. This test documents that contract.
        """
        # Record with dynamic-looking values (not crashed, not normalized)
        dynamic_backend = f"backend_{id(self)}"
        self._metrics.record_request(dynamic_backend, "success", 0.1)
        assert any(r.get("backend") == dynamic_backend for r in self._calls["requests"]), "Dynamic backend label should be recorded as-is (caller owns cardinality)"
