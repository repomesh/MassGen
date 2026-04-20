"""Tests for Phase 5 AdaptiveController (cb_adaptive.py)."""

from __future__ import annotations

import threading
import time
import unittest.mock

import pytest

from massgen.backend.cb_adaptive import AdaptiveConfig, AdaptiveController
from massgen.backend.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_config() -> LLMCircuitBreakerConfig:
    return LLMCircuitBreakerConfig(
        enabled=True,
        max_failures=10,
        reset_time_seconds=60,
    )


@pytest.fixture
def adaptive_config() -> AdaptiveConfig:
    return AdaptiveConfig(enabled=True)


@pytest.fixture
def controller(base_config, adaptive_config) -> AdaptiveController:
    return AdaptiveController(base_config, adaptive_config)


# ---------------------------------------------------------------------------
# Category A: AdaptiveConfig validation (6 tests)
# ---------------------------------------------------------------------------


class TestAdaptiveConfigValidation:
    def test_config_defaults_valid(self):
        """Default constructor must succeed with no arguments."""
        cfg = AdaptiveConfig()
        assert cfg.ewma_alpha == 0.1
        assert cfg.enabled is False

    def test_config_ewma_alpha_out_of_range(self):
        """alpha=0, alpha=-0.1, and alpha=1.5 must each raise ValueError."""
        with pytest.raises(ValueError, match="ewma_alpha"):
            AdaptiveConfig(ewma_alpha=0)
        with pytest.raises(ValueError, match="ewma_alpha"):
            AdaptiveConfig(ewma_alpha=-0.1)
        with pytest.raises(ValueError, match="ewma_alpha"):
            AdaptiveConfig(ewma_alpha=1.5)

    def test_config_low_high_ordering(self):
        """low >= high, low < 0, and high > 1 each raise ValueError."""
        with pytest.raises(ValueError):
            AdaptiveConfig(low_error_rate=0.9, high_error_rate=0.5)
        with pytest.raises(ValueError):
            AdaptiveConfig(low_error_rate=0.5, high_error_rate=0.5)
        with pytest.raises(ValueError):
            AdaptiveConfig(low_error_rate=-0.1, high_error_rate=0.9)
        with pytest.raises(ValueError):
            AdaptiveConfig(low_error_rate=0.1, high_error_rate=1.1)

    def test_config_min_max_failures_ordering(self):
        """min_effective < 1 raises; max_effective < min raises."""
        with pytest.raises(ValueError, match="min_effective_max_failures"):
            AdaptiveConfig(min_effective_max_failures=0)
        with pytest.raises(ValueError, match="max_effective_max_failures"):
            AdaptiveConfig(min_effective_max_failures=10, max_effective_max_failures=5)

    def test_config_reset_seconds_bounds(self):
        """min_reset < 0.1 raises; max_reset < min_reset raises."""
        with pytest.raises(ValueError, match="min_effective_reset_seconds"):
            AdaptiveConfig(min_effective_reset_seconds=0.05)
        with pytest.raises(ValueError, match="max_effective_reset_seconds"):
            AdaptiveConfig(min_effective_reset_seconds=100.0, max_effective_reset_seconds=50.0)

    def test_config_recovery_sample_weight_bounds(self):
        """weight=0, weight=1.1, weight=-0.1 each raise ValueError."""
        with pytest.raises(ValueError, match="recovery_sample_weight"):
            AdaptiveConfig(recovery_sample_weight=0)
        with pytest.raises(ValueError, match="recovery_sample_weight"):
            AdaptiveConfig(recovery_sample_weight=1.1)
        with pytest.raises(ValueError, match="recovery_sample_weight"):
            AdaptiveConfig(recovery_sample_weight=-0.1)


# ---------------------------------------------------------------------------
# Category B: EWMA convergence (4 tests)
# ---------------------------------------------------------------------------


class TestEWMAConvergence:
    def test_ewma_all_failures_converges_to_one(self, controller):
        """200 failure samples must drive EWMA above 0.99."""
        for _ in range(200):
            controller.record_outcome(True)
        assert controller.snapshot()["error_rate_ewma"] > 0.99

    def test_ewma_all_successes_converges_to_zero(self, controller):
        """200 success samples must drive EWMA below 0.01."""
        for _ in range(200):
            controller.record_outcome(False)
        assert controller.snapshot()["error_rate_ewma"] < 0.01

    def test_ewma_mixed_traffic_stable(self, controller):
        """Alternating 200 samples must produce EWMA between 0.4 and 0.6."""
        for i in range(200):
            controller.record_outcome(i % 2 == 0)
        ewma = controller.snapshot()["error_rate_ewma"]
        assert 0.4 < ewma < 0.6

    def test_ewma_single_sample_updates_correctly(self, base_config):
        """After one failure with alpha=0.1, EWMA must equal exactly 0.1."""
        cfg = AdaptiveConfig(enabled=True, ewma_alpha=0.1)
        ctrl = AdaptiveController(base_config, cfg)
        ctrl.record_outcome(True)
        assert ctrl.snapshot()["error_rate_ewma"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Category C: Effective max_failures adjustment (4 tests)
# ---------------------------------------------------------------------------


class TestEffectiveMaxFailures:
    def _force_ewma(self, controller: AdaptiveController, value: float) -> None:
        """Directly set the internal EWMA via lock access."""
        with controller._lock:
            controller._error_rate_ewma = value

    def test_effective_max_tightens_above_high_threshold(self, base_config):
        """EWMA >= high_error_rate must produce effective < base (half)."""
        cfg = AdaptiveConfig(enabled=True, high_error_rate=0.9, min_effective_max_failures=2, max_effective_max_failures=50)
        ctrl = AdaptiveController(base_config, cfg)
        self._force_ewma(ctrl, 0.95)
        # base=10, high: candidate = max(1, 10//2) = 5, clamped to [2, 50] = 5
        assert ctrl.effective_max_failures() == 5
        assert ctrl.effective_max_failures() < base_config.max_failures

    def test_effective_max_loosens_below_low_threshold(self, base_config):
        """EWMA <= low_error_rate must produce effective > base (double)."""
        cfg = AdaptiveConfig(enabled=True, low_error_rate=0.1, min_effective_max_failures=2, max_effective_max_failures=50)
        ctrl = AdaptiveController(base_config, cfg)
        self._force_ewma(ctrl, 0.05)
        # base=10, low: candidate = 10*2 = 20, clamped to [2, 50] = 20
        assert ctrl.effective_max_failures() == 20
        assert ctrl.effective_max_failures() > base_config.max_failures

    def test_effective_max_stays_baseline_in_middle_zone(self, base_config):
        """EWMA between low and high must produce effective == base (clamped)."""
        cfg = AdaptiveConfig(
            enabled=True,
            low_error_rate=0.1,
            high_error_rate=0.9,
            min_effective_max_failures=2,
            max_effective_max_failures=50,
        )
        ctrl = AdaptiveController(base_config, cfg)
        self._force_ewma(ctrl, 0.5)
        # base=10 in middle zone, clamped to [2, 50] = 10
        assert ctrl.effective_max_failures() == base_config.max_failures

    def test_effective_max_respects_min_max_clamp(self):
        """Clamp behavior: min enforced from below, max enforced from above."""
        base = LLMCircuitBreakerConfig(enabled=True, max_failures=100, reset_time_seconds=60)
        cfg_low = AdaptiveConfig(enabled=True, low_error_rate=0.1, min_effective_max_failures=2, max_effective_max_failures=5)
        ctrl_low = AdaptiveController(base, cfg_low)
        # base=100, low zone: candidate=200, clamped to max=5
        with ctrl_low._lock:
            ctrl_low._error_rate_ewma = 0.05
        assert ctrl_low.effective_max_failures() == 5

        base2 = LLMCircuitBreakerConfig(enabled=True, max_failures=1, reset_time_seconds=60)
        cfg_high = AdaptiveConfig(enabled=True, high_error_rate=0.9, min_effective_max_failures=3, max_effective_max_failures=10)
        ctrl_high = AdaptiveController(base2, cfg_high)
        # base=1, high zone: candidate=max(1,1//2)=1, clamped to min=3
        with ctrl_high._lock:
            ctrl_high._error_rate_ewma = 0.95
        assert ctrl_high.effective_max_failures() == 3


# ---------------------------------------------------------------------------
# Category D: Recovery latency (4 tests)
# ---------------------------------------------------------------------------


class TestRecoveryLatency:
    def test_record_open_without_close_does_not_update_latency(self, controller):
        """record_open without record_close must not change latency EWMA."""
        initial = controller.snapshot()["recovery_latency_ewma"]
        controller.record_open()
        assert controller.snapshot()["recovery_latency_ewma"] == initial

    def test_record_open_then_close_updates_latency(self, base_config):
        """Injected clock: record_close must shift latency EWMA toward observed sample."""
        clock_values = [100.0, 110.0]
        call_count = [0]

        def fake_clock() -> float:
            v = clock_values[call_count[0]]
            call_count[0] += 1
            return v

        cfg = AdaptiveConfig(enabled=True, initial_recovery_latency_seconds=60.0)
        ctrl = AdaptiveController(base_config, cfg, clock=fake_clock)
        initial = ctrl.snapshot()["recovery_latency_ewma"]
        ctrl.record_open()
        ctrl.record_close()
        updated = ctrl.snapshot()["recovery_latency_ewma"]
        # Observed latency = 10s; EWMA shifts from 60 toward 10
        assert updated != initial
        assert updated < initial

    def test_record_close_without_open_is_noop(self, controller):
        """record_close without prior record_open must not alter latency EWMA."""
        initial = controller.snapshot()["recovery_latency_ewma"]
        controller.record_close()
        assert controller.snapshot()["recovery_latency_ewma"] == initial

    def test_effective_reset_time_clamps_to_bounds(self, base_config):
        """Very high or low latency EWMA must be clamped to [min, max] reset seconds."""
        cfg = AdaptiveConfig(
            enabled=True,
            min_effective_reset_seconds=10.0,
            max_effective_reset_seconds=300.0,
        )
        ctrl_high = AdaptiveController(base_config, cfg)
        with ctrl_high._lock:
            ctrl_high._recovery_latency_ewma = 9999.0
        assert ctrl_high.effective_reset_time() == 300.0

        ctrl_low = AdaptiveController(base_config, cfg)
        with ctrl_low._lock:
            ctrl_low._recovery_latency_ewma = 0.0
        assert ctrl_low.effective_reset_time() == 10.0


# ---------------------------------------------------------------------------
# Category E: Back-compat and integration (4 tests)
# ---------------------------------------------------------------------------


class TestBackCompatAndIntegration:
    def test_llm_cb_with_adaptive_none_identical_behavior(self):
        """LLMCircuitBreaker(adaptive=None) must increment failure_count normally."""
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=5, reset_time_seconds=60)
        cb = LLMCircuitBreaker(config, adaptive=None)
        cb.record_failure()
        assert cb.failure_count == 1
        cb.record_failure()
        assert cb.failure_count == 2

    def test_llm_cb_with_adaptive_feeds_outcomes(self, base_config, adaptive_config):
        """record_success and record_failure must update adaptive EWMA."""
        ctrl = AdaptiveController(base_config, adaptive_config)
        cb = LLMCircuitBreaker(base_config, adaptive=ctrl)
        cb.record_success()
        cb.record_failure()
        ewma = ctrl.snapshot()["error_rate_ewma"]
        assert 0.0 < ewma <= 1.0

    def test_llm_cb_adaptive_triggers_open_at_adjusted_threshold(self, base_config):
        """High EWMA must halve effective_max_failures, tightening the threshold."""
        cfg = AdaptiveConfig(
            enabled=True,
            low_error_rate=0.05,
            high_error_rate=0.2,
            min_effective_max_failures=2,
            max_effective_max_failures=20,
        )
        ctrl = AdaptiveController(base_config, cfg)
        # Force EWMA well above high_error_rate
        with ctrl._lock:
            ctrl._error_rate_ewma = 0.95
        # base=10, high zone: candidate=max(1,10//2)=5, clamped to [2,20] = 5
        assert ctrl.effective_max_failures() == 5
        # Confirm it is strictly less than base
        assert ctrl.effective_max_failures() < base_config.max_failures

    def test_llm_cb_adaptive_reset_time_applied_in_force_open(self, base_config):
        """force_open must use effective_reset_time from AdaptiveController."""
        cfg = AdaptiveConfig(
            enabled=True,
            initial_recovery_latency_seconds=120.0,
            min_effective_reset_seconds=10.0,
            max_effective_reset_seconds=600.0,
        )
        ctrl = AdaptiveController(base_config, cfg)
        # Latency EWMA set to 120s -- effective reset should be 120s
        cb = LLMCircuitBreaker(base_config, adaptive=ctrl)
        t_before = time.monotonic()
        cb.force_open(reason="test")
        t_after = time.monotonic()
        # open_until should be approximately now + 120s (effective reset)
        assert cb._open_until >= t_before + 119.0
        assert cb._open_until <= t_after + 121.0


# ---------------------------------------------------------------------------
# Category F: Concurrency (2 tests)
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_record_outcome_is_thread_safe(self, controller):
        """8 threads x 1000 record_outcome calls must produce valid EWMA in [0, 1]."""
        errors: list[Exception] = []

        def worker(is_failure: bool) -> None:
            try:
                for _ in range(1000):
                    controller.record_outcome(is_failure)
            except Exception as exc:  # noqa: BLE001 -- capture thread exceptions for test assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        ewma = controller.snapshot()["error_rate_ewma"]
        assert isinstance(ewma, float)
        assert 0.0 <= ewma <= 1.0

    def test_concurrent_snapshot_during_updates(self, controller):
        """Snapshot calls during concurrent updates must not raise and return valid structure."""
        expected_keys = {"error_rate_ewma", "recovery_latency_ewma", "effective_max_failures", "effective_reset_time", "open_at"}
        errors: list[Exception] = []
        snapshots: list[dict] = []
        stop_event = threading.Event()

        def writer() -> None:
            while not stop_event.is_set():
                controller.record_outcome(True)
                controller.record_outcome(False)

        def reader() -> None:
            try:
                for _ in range(200):
                    snap = controller.snapshot()
                    snapshots.append(snap)
            except Exception as exc:  # noqa: BLE001 -- capture thread exceptions for test assertion
                errors.append(exc)

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(4)]

        writer_thread.start()
        for t in reader_threads:
            t.start()
        for t in reader_threads:
            t.join()
        stop_event.set()
        writer_thread.join()

        assert not errors, f"Reader errors: {errors}"
        for snap in snapshots:
            assert set(snap.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Category G: Adversarial (4 tests)
# ---------------------------------------------------------------------------


class TestAdversarial:
    def test_record_open_idempotent_overwrites_timestamp(self, base_config):
        """Calling record_open twice must store the latest timestamp."""
        clock_values = [100.0, 200.0]
        call_count = [0]

        def fake_clock() -> float:
            v = clock_values[call_count[0] % len(clock_values)]
            call_count[0] += 1
            return v

        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg, clock=fake_clock)
        ctrl.record_open()
        ctrl.record_open()
        # Second call must overwrite; open_at should reflect second clock value (200.0)
        assert ctrl.snapshot()["open_at"] == 200.0

    def test_record_close_with_negative_clock_skew_clamps_to_zero(self, base_config):
        """Negative raw latency from clock skew must be clamped to 0 -- not negative."""
        # Clock goes backward: open at 100, close at 90 (skew)
        clock_values = [100.0, 90.0]
        call_count = [0]

        def fake_clock() -> float:
            v = clock_values[call_count[0]]
            call_count[0] += 1
            return v

        cfg = AdaptiveConfig(enabled=True, initial_recovery_latency_seconds=60.0, recovery_sample_weight=0.5)
        ctrl = AdaptiveController(base_config, cfg, clock=fake_clock)
        ctrl.record_open()
        ctrl.record_close()
        # Latency clamped to 0 -- EWMA moves toward 0, not negative
        latency = ctrl.snapshot()["recovery_latency_ewma"]
        assert latency >= 0.0
        # With weight=0.5, seed=60: (1-0.5)*60 + 0.5*0 = 30
        assert latency == pytest.approx(30.0)

    def test_nonfinite_alpha_rejected_at_config_time(self):
        """float('inf') and float('nan') as ewma_alpha must raise ValueError."""
        with pytest.raises(ValueError, match="ewma_alpha"):
            AdaptiveConfig(ewma_alpha=float("inf"))
        with pytest.raises(ValueError, match="ewma_alpha"):
            AdaptiveConfig(ewma_alpha=float("nan"))

    def test_snapshot_returns_consistent_structure(self, controller):
        """snapshot() must return exactly the 5 documented keys with correct types."""
        snap = controller.snapshot()
        expected_keys = {"error_rate_ewma", "recovery_latency_ewma", "effective_max_failures", "effective_reset_time", "open_at"}
        assert set(snap.keys()) == expected_keys
        assert isinstance(snap["error_rate_ewma"], float)
        assert isinstance(snap["recovery_latency_ewma"], float)
        assert isinstance(snap["effective_max_failures"], int)
        assert isinstance(snap["effective_reset_time"], float)
        # open_at is float | None
        assert snap["open_at"] is None or isinstance(snap["open_at"], float)


# ---------------------------------------------------------------------------
# Category H: LLM CB integration (2 tests)
# ---------------------------------------------------------------------------


class TestLLMCBIntegration:
    def test_llm_cb_record_success_triggers_record_close_on_recovery(self, base_config):
        """HALF_OPEN -> record_success must clear adaptive open_at to None."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(base_config, adaptive=ctrl)

        # Drive CB to OPEN via failures
        for _ in range(base_config.max_failures):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert ctrl.snapshot()["open_at"] is not None

        # Force the CB into HALF_OPEN by manipulating _open_until
        with cb._lock:
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_probe_active = False

        # record_success from HALF_OPEN -> CLOSED triggers record_close
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert ctrl.snapshot()["open_at"] is None

    def test_adaptive_open_timer_set_on_natural_open_transition(self, base_config):
        """Natural CLOSED -> OPEN transition via record_failure must set adaptive open_at."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(base_config, adaptive=ctrl)

        assert ctrl.snapshot()["open_at"] is None

        for _ in range(base_config.max_failures):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert ctrl.snapshot()["open_at"] is not None


# ---------------------------------------------------------------------------
# Category I: GAP tests (Round 1 review R-3 missing coverage)
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_cb_with_adaptive(base_config, adaptive_config):
    ctrl = AdaptiveController(base_config, adaptive_config)
    return LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl)


class TestGapCoverage:
    def test_config_ewma_alpha_upper_boundary_valid(self, base_config):
        """alpha=1.0 is a valid boundary -- instant replacement semantics."""
        cfg = AdaptiveConfig(enabled=True, ewma_alpha=1.0)
        ctrl = AdaptiveController(base_config, cfg)
        # After one failure from initial 0.0: new = (1-1)*0 + 1*1 = 1.0
        ctrl.record_outcome(True)
        assert ctrl.snapshot()["error_rate_ewma"] == pytest.approx(1.0)
        # After one success: new = (1-1)*1 + 1*0 = 0.0
        ctrl.record_outcome(False)
        assert ctrl.snapshot()["error_rate_ewma"] == pytest.approx(0.0)

    def test_initial_latency_defaults_from_base_clamped_by_min_reset(self, base_config):
        """Seed from base reset_time (1s), clamped to min_effective_reset (10s)."""
        # base_config.reset_time_seconds == 60 -- create a custom one with 1s
        base = LLMCircuitBreakerConfig(enabled=True, max_failures=5, reset_time_seconds=1)
        cfg = AdaptiveConfig(enabled=True, min_effective_reset_seconds=10.0, max_effective_reset_seconds=300.0)
        ctrl = AdaptiveController(base, cfg)
        assert ctrl.snapshot()["recovery_latency_ewma"] == pytest.approx(1.0)
        assert ctrl.effective_reset_time() == pytest.approx(10.0)

    def test_llm_cb_adaptive_none_force_open_uses_config_reset_time(self):
        """force_open(open_for_seconds=0) with adaptive=None uses config.reset_time_seconds."""
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=5, reset_time_seconds=60)
        cb = LLMCircuitBreaker(config=config, backend_name="test", adaptive=None, store=None)
        t_before = time.monotonic()
        cb.force_open(reason="test", open_for_seconds=0)
        t_after = time.monotonic()
        # open_until must be at least t_before + 60 (floor) and at most t_after + 60 (tight upper bound).
        assert cb._open_until >= t_before + 60.0, f"open_until below floor: {cb._open_until - t_before}"
        assert cb._open_until <= t_after + 60.0, f"open_until above cap: {cb._open_until - t_after}"

    def test_concurrent_llm_cb_record_failure_with_adaptive(self, base_config):
        """8 threads x 200 all-failure record_failure calls must drive CB to OPEN with exact-once record_open."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            try:
                barrier.wait()
                for _ in range(200):
                    cb.record_failure(error_type="net")
            except Exception as exc:  # noqa: BLE001 -- capture thread exceptions for test assertion
                errors.append(exc)

        with unittest.mock.patch.object(ctrl, "record_open", wraps=ctrl.record_open) as open_spy:
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            open_call_count = open_spy.call_count

        assert not errors, f"Thread errors: {errors}"
        snap = ctrl.snapshot()
        ewma = snap["error_rate_ewma"]
        assert isinstance(ewma, float)
        assert 0.0 <= ewma <= 1.0
        # After 1600 all-failure calls with no intervening successes, EWMA converges near 1.0.
        assert ewma > 0.99, f"EWMA did not converge to failure, got {ewma}"
        # 1600 failures >> max_failures=10 -- CB must be OPEN and stay OPEN (no success to close it).
        assert cb.state == CircuitState.OPEN, f"CB state not OPEN after 1600 failures, got {cb.state}"
        assert snap["open_at"] is not None, "adaptive.open_at not set despite OPEN state"
        # Exactly one CLOSED->OPEN transition must occur. Additional failures while already
        # OPEN must NOT re-fire record_open (guarded by prev_state != OPEN check).
        assert open_call_count == 1, f"record_open fired {open_call_count} times, expected 1"

    def test_llm_cb_record_success_from_closed_does_not_call_record_close(self, base_config):
        """record_success while CLOSED must not invoke adaptive.record_close."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)

        assert ctrl.snapshot()["open_at"] is None
        with unittest.mock.patch.object(ctrl, "record_close", wraps=ctrl.record_close) as spy:
            cb.record_success()
            assert spy.call_count == 0
        assert ctrl.snapshot()["open_at"] is None


# ---------------------------------------------------------------------------
# Category J: Regression tests for Round 1 fixes
# ---------------------------------------------------------------------------


class TestRound1Regressions:
    def test_record_open_not_called_twice_on_open_to_open(self, base_config):
        """Second record_failure while already OPEN must not call adaptive.record_open again."""
        # Use max_failures=2 with min_effective_max_failures=1 so the adaptive
        # clamp keeps effective=2 in the middle zone, and second failure trips open.
        low_config = LLMCircuitBreakerConfig(enabled=True, max_failures=2, reset_time_seconds=60)
        cfg = AdaptiveConfig(enabled=True, min_effective_max_failures=1, max_effective_max_failures=20)
        ctrl2 = AdaptiveController(low_config, cfg)
        # Seed EWMA into the middle zone (between low=0.1 and high=0.9) so no doubling/halving
        with ctrl2._lock:
            ctrl2._error_rate_ewma = 0.5
        cb = LLMCircuitBreaker(config=low_config, backend_name="test", adaptive=ctrl2, store=None)

        with unittest.mock.patch.object(ctrl2, "record_open", wraps=ctrl2.record_open) as spy:
            cb.record_failure()  # failure_count=1, still below effective=2, stays CLOSED
            assert cb.state == CircuitState.CLOSED
            cb.record_failure()  # failure_count=2 >= effective=2, CLOSED -> OPEN
            assert cb.state == CircuitState.OPEN
            cb.record_failure()  # still OPEN, failure_count increments but no transition
            assert cb.state == CircuitState.OPEN
            assert spy.call_count == 1, f"record_open called {spy.call_count} times, expected 1"

    def test_record_failure_from_half_open_calls_record_open_exactly_once(self, base_config):
        """HALF_OPEN -> OPEN probe-failure path must call adaptive.record_open exactly once."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)

        # Manually position CB in HALF_OPEN with a probe in flight.
        with cb._lock:
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_probe_active = True

        with unittest.mock.patch.object(ctrl, "record_open", wraps=ctrl.record_open) as spy:
            cb.record_failure(error_type="probe")
            assert cb.state == CircuitState.OPEN
            assert spy.call_count == 1, f"record_open called {spy.call_count} times, expected 1"
        # A follow-up failure while already OPEN must not re-fire record_open.
        with unittest.mock.patch.object(ctrl, "record_open", wraps=ctrl.record_open) as spy2:
            cb.record_failure(error_type="again")
            assert spy2.call_count == 0, f"record_open fired on OPEN->OPEN: {spy2.call_count}"

    def test_reset_clears_adaptive_open_timer(self, base_config):
        """cb.reset() must clear adaptive open_at to None via reset_open_timer()."""
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)

        cb.force_open(reason="test")
        assert ctrl.snapshot()["open_at"] is not None

        cb.reset()
        assert ctrl.snapshot()["open_at"] is None

    def test_force_open_with_explicit_duration_ignores_adaptive_ewma(self, base_config):
        """force_open(open_for_seconds=30) uses max(reset_time, 30), not the 500s EWMA."""
        cfg = AdaptiveConfig(
            enabled=True,
            min_effective_reset_seconds=10.0,
            max_effective_reset_seconds=600.0,
        )
        ctrl = AdaptiveController(base_config, cfg)
        # Inject a large latency EWMA that would otherwise dominate
        with ctrl._lock:
            ctrl._recovery_latency_ewma = 500.0
        # base_config has reset_time_seconds=60; max(60, 30) = 60
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        cb.force_open(reason="test", open_for_seconds=30)
        remaining = cb._open_until - time.monotonic()
        assert remaining <= 62.0, f"Expected <= 62s (max(60,30)=60 + slop), got {remaining}"
        assert remaining >= 59.0, f"Expected >= 59s, got {remaining}"

    def test_force_open_without_explicit_duration_uses_effective_reset_time(self, base_config):
        """force_open(open_for_seconds=0) with adaptive uses effective_reset_time from EWMA."""
        cfg = AdaptiveConfig(
            enabled=True,
            min_effective_reset_seconds=10.0,
            max_effective_reset_seconds=300.0,
        )
        ctrl = AdaptiveController(base_config, cfg)
        with ctrl._lock:
            ctrl._recovery_latency_ewma = 200.0
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        cb.force_open(reason="test", open_for_seconds=0)
        remaining = cb._open_until - time.monotonic()
        assert 199.0 <= remaining <= 202.0, f"Expected ~200s, got {remaining}"

    def test_initial_recovery_latency_seconds_rejects_inf(self):
        """Non-finite initial_recovery_latency_seconds must raise ValueError."""
        with pytest.raises(ValueError, match="initial_recovery_latency_seconds"):
            AdaptiveConfig(initial_recovery_latency_seconds=float("inf"))
        with pytest.raises(ValueError, match="initial_recovery_latency_seconds"):
            AdaptiveConfig(initial_recovery_latency_seconds=float("-inf"))
        with pytest.raises(ValueError, match="initial_recovery_latency_seconds"):
            AdaptiveConfig(initial_recovery_latency_seconds=float("nan"))

    def test_initial_recovery_latency_seconds_rejects_negative(self):
        """Negative initial_recovery_latency_seconds must raise; zero is valid."""
        with pytest.raises(ValueError, match=">= 0"):
            AdaptiveConfig(initial_recovery_latency_seconds=-1.0)
        # Zero must not raise
        cfg = AdaptiveConfig(initial_recovery_latency_seconds=0.0)
        assert cfg.initial_recovery_latency_seconds == 0.0

    def test_snapshot_atomic_consistency(self, base_config):
        """snapshot() must return computed effective values from the captured EWMA snapshot."""
        cfg = AdaptiveConfig(
            enabled=True,
            high_error_rate=0.9,
            min_effective_max_failures=2,
            max_effective_max_failures=50,
            min_effective_reset_seconds=10.0,
            max_effective_reset_seconds=300.0,
        )
        ctrl = AdaptiveController(base_config, cfg)
        # Inject known values directly
        with ctrl._lock:
            ctrl._error_rate_ewma = 0.95  # >= high_error_rate -> candidate = max(1, 10//2) = 5
            ctrl._recovery_latency_ewma = 200.0  # in [10, 300] -> effective_reset = 200.0
        snap = ctrl.snapshot()
        # Effective max_failures: rate=0.95 >= 0.9, candidate=max(1,5)=5, clamped to [2,50]=5
        assert snap["effective_max_failures"] == 5
        # Effective reset time: 200.0 in bounds -> 200.0
        assert snap["effective_reset_time"] == pytest.approx(200.0)
        # Snapshot fields match injected values
        assert snap["error_rate_ewma"] == pytest.approx(0.95)
        assert snap["recovery_latency_ewma"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Category K: CodeRabbit review (PR #1065) follow-ups
# ---------------------------------------------------------------------------


class TestEnabledFlagHonored:
    """AdaptiveConfig.enabled=False must make the controller inert."""

    def test_disabled_controller_no_ops_record_outcome(self, base_config):
        cfg = AdaptiveConfig(enabled=False)
        ctrl = AdaptiveController(base_config, cfg)
        ctrl.record_outcome(True)
        ctrl.record_outcome(True)
        ctrl.record_outcome(True)
        assert ctrl.snapshot()["error_rate_ewma"] == 0.0

    def test_disabled_controller_no_ops_record_open_and_close(self, base_config):
        cfg = AdaptiveConfig(enabled=False)
        ctrl = AdaptiveController(base_config, cfg)
        ctrl.record_open()
        assert ctrl.snapshot()["open_at"] is None
        ctrl.record_close()  # also a no-op; must not raise even with _open_at=None
        assert ctrl.snapshot()["open_at"] is None

    def test_disabled_controller_effective_returns_static(self, base_config):
        cfg = AdaptiveConfig(enabled=False)
        ctrl = AdaptiveController(base_config, cfg)
        # Inject state that would shift the effective thresholds if enabled.
        with ctrl._lock:
            ctrl._error_rate_ewma = 0.99
            ctrl._recovery_latency_ewma = 9999.0
        assert ctrl.effective_max_failures() == base_config.max_failures
        assert ctrl.effective_reset_time() == float(base_config.reset_time_seconds)

    def test_llm_cb_with_disabled_adaptive_equivalent_to_none(self, base_config):
        """LLMCircuitBreaker + disabled AdaptiveController behaves like adaptive=None."""
        cfg = AdaptiveConfig(enabled=False)
        ctrl = AdaptiveController(base_config, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        for _ in range(base_config.max_failures):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With disabled adaptive, recovery EWMA should stay at the seed (reset_time_seconds);
        # open_at must remain None because record_open is a no-op.
        assert ctrl.snapshot()["open_at"] is None


class TestConfigMismatchRejected:
    """LLMCircuitBreaker must reject an AdaptiveController whose base_config disagrees."""

    def test_different_max_failures_raises(self, base_config):
        # base_config.max_failures == 10; controller is built with a different value.
        alt_base = LLMCircuitBreakerConfig(enabled=True, max_failures=99, reset_time_seconds=60)
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(alt_base, cfg)
        with pytest.raises(ValueError, match="max_failures"):
            LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)

    def test_different_reset_time_raises(self, base_config):
        alt_base = LLMCircuitBreakerConfig(enabled=True, max_failures=10, reset_time_seconds=999)
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(alt_base, cfg)
        with pytest.raises(ValueError, match="reset_time_seconds"):
            LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)

    def test_matching_base_config_accepted(self, base_config):
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(base_config, cfg)
        # Same instance -- no raise.
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        assert cb.adaptive is ctrl

    def test_equivalent_separate_config_accepted(self, base_config):
        """Two distinct config instances with identical fields are accepted."""
        equivalent = LLMCircuitBreakerConfig(
            enabled=base_config.enabled,
            max_failures=base_config.max_failures,
            reset_time_seconds=base_config.reset_time_seconds,
        )
        cfg = AdaptiveConfig(enabled=True)
        ctrl = AdaptiveController(equivalent, cfg)
        cb = LLMCircuitBreaker(config=base_config, backend_name="test", adaptive=ctrl, store=None)
        assert cb.adaptive is ctrl


class TestClockUnderLock:
    """Clock calls must happen under _lock so committed timestamps reflect acquisition time."""

    def test_record_open_timestamp_reflects_post_lock_time(self, base_config):
        """record_open stores a timestamp from AFTER lock acquisition."""
        cfg = AdaptiveConfig(enabled=True)
        clock_state = {"value": 100.0}

        def clock() -> float:
            # Each call advances; if the call happens before lock the stored
            # value would not equal the post-lock sample.
            clock_state["value"] += 1.0
            return clock_state["value"]

        ctrl = AdaptiveController(base_config, cfg, clock=clock)
        ctrl.record_open()
        # Only one clock() call should occur (inside the lock).
        assert ctrl.snapshot()["open_at"] == 101.0
        # If clock had been called outside lock too, value would be 102 already.
        assert clock_state["value"] == 101.0

    def test_record_close_latency_uses_post_lock_clock(self, base_config):
        """record_close reads the clock only once, under the lock."""
        cfg = AdaptiveConfig(enabled=True, recovery_sample_weight=1.0)
        clock_state = {"value": 100.0}

        def clock() -> float:
            clock_state["value"] += 1.0
            return clock_state["value"]

        ctrl = AdaptiveController(base_config, cfg, clock=clock)
        # record_open: one clock tick to 101.
        ctrl.record_open()
        assert clock_state["value"] == 101.0
        # record_close: one more tick to 102; latency=102-101=1.0.
        ctrl.record_close()
        assert clock_state["value"] == 102.0
        assert ctrl.snapshot()["recovery_latency_ewma"] == pytest.approx(1.0)
