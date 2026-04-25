"""Tests for Phase 6 FailoverRouter (cb_failover.py)."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest.mock

import pytest

from massgen.backend.cb_failover import FailoverConfig, FailoverRouter
from massgen.backend.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_config() -> FailoverConfig:
    """Two-region failover config with 30s min duration."""
    return FailoverConfig(
        enabled=True,
        regions={"gpt-5.4": ["us-east", "eu-west"]},
        min_failover_duration_seconds=30.0,
    )


@pytest.fixture
def router(simple_config: FailoverConfig) -> FailoverRouter:
    """Default-probe router built from simple_config."""
    return FailoverRouter(simple_config)


@pytest.fixture
def cb_config() -> LLMCircuitBreakerConfig:
    """Enabled CB config with 3 failures threshold."""
    return LLMCircuitBreakerConfig(enabled=True, max_failures=3, reset_time_seconds=60)


# ---------------------------------------------------------------------------
# Category A: FailoverConfig validation (10 tests)
# ---------------------------------------------------------------------------


class TestFailoverConfigValidation:
    """FailoverConfig field validation."""

    def test_defaults_valid(self) -> None:
        """Default constructor must succeed -- enabled=False, empty regions."""
        cfg = FailoverConfig()
        assert cfg.enabled is False
        assert cfg.regions == {}

    def test_zero_health_check_timeout_rejects(self) -> None:
        """health_check_timeout_seconds=0 must raise ValueError."""
        with pytest.raises(ValueError, match="health_check_timeout_seconds"):
            FailoverConfig(enabled=True, health_check_timeout_seconds=0)

    def test_negative_min_failover_duration_rejects(self) -> None:
        """min_failover_duration_seconds=-1 must raise ValueError."""
        with pytest.raises(ValueError, match="min_failover_duration_seconds"):
            FailoverConfig(enabled=True, min_failover_duration_seconds=-1.0)

    def test_zero_recovery_check_interval_rejects(self) -> None:
        """recovery_check_interval_seconds=0 must raise ValueError."""
        with pytest.raises(ValueError, match="recovery_check_interval_seconds"):
            FailoverConfig(enabled=True, recovery_check_interval_seconds=0)

    def test_duplicate_region_in_list_rejects(self) -> None:
        """Duplicate region strings within one backend must raise ValueError."""
        with pytest.raises(ValueError, match="duplicate"):
            FailoverConfig(enabled=True, regions={"gpt-5.4": ["us-east", "us-east"]})

    def test_empty_region_string_rejects(self) -> None:
        """An empty string in the regions list must raise ValueError."""
        with pytest.raises(ValueError, match="invalid region"):
            FailoverConfig(enabled=True, regions={"gpt-5.4": ["us-east", ""]})

    def test_whitespace_region_rejected(self) -> None:
        """Whitespace-only region names must raise ValueError."""
        with pytest.raises(ValueError, match="invalid region"):
            FailoverConfig(enabled=True, regions={"x": ["primary", "  "]})

    def test_whitespace_backend_rejected(self) -> None:
        """Whitespace-only backend names must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty strings"):
            FailoverConfig(enabled=True, regions={"  ": ["p", "s"]})

    def test_empty_region_list_rejects(self) -> None:
        """An empty list for a backend must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty list"):
            FailoverConfig(enabled=True, regions={"gpt-5.4": []})

    def test_valid_multiregion_config_accepted(self) -> None:
        """Three distinct regions must not raise."""
        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west", "ap-southeast"]},
        )
        assert len(cfg.regions["gpt-5.4"]) == 3


# ---------------------------------------------------------------------------
# Category B: Failover trigger (7 tests)
# ---------------------------------------------------------------------------


class TestFailoverTrigger:
    """on_cb_state_change("open") behavior with various probe outcomes."""

    def test_open_with_healthy_probe_commits_failover(self, simple_config: FailoverConfig) -> None:
        """on_cb_state_change("open") with probe returning True must failover."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        assert not router.is_failed_over("gpt-5.4")
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

    def test_open_with_failing_probe_stays_on_primary(self, simple_config: FailoverConfig) -> None:
        """on_cb_state_change("open") with probe returning False must not failover."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: False)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert not router.is_failed_over("gpt-5.4")

    def test_open_with_probe_raising_stays_on_primary(self, simple_config: FailoverConfig) -> None:
        """Probe that raises must be swallowed; no failover committed."""

        def raising_probe(_region: str) -> bool:
            raise RuntimeError("network error")

        router = FailoverRouter(simple_config, health_probe=raising_probe)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert not router.is_failed_over("gpt-5.4")

    def test_hanging_probe_times_out_per_health_check_timeout_seconds(self) -> None:
        """A probe that hangs longer than health_check_timeout_seconds must be cancelled.

        Without timeout enforcement, a hanging probe blocks the calling thread
        and leaves _failover_pending stuck True, silently disabling all
        subsequent OPEN events for that backend.
        """
        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west", "ap-southeast"]},
            health_check_timeout_seconds=0.05,
            min_failover_duration_seconds=30.0,
        )

        def hanging_probe(_region: str) -> bool:
            # Block far longer than the configured timeout.
            time.sleep(5.0)
            return True

        router = FailoverRouter(cfg, health_probe=hanging_probe)

        start = time.monotonic()
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        elapsed = time.monotonic() - start

        # Two secondaries x 0.05s timeout => bounded above by ~0.5s with thread overhead.
        assert elapsed < 1.0, f"on_cb_state_change should complete near timeout, took {elapsed:.2f}s"
        assert not router.is_failed_over("gpt-5.4")
        # The pending flag must be cleared so a subsequent OPEN can retry.
        assert router._failover_pending.get("gpt-5.4", False) is False

    def test_get_active_region_returns_secondary_after_failover(self, simple_config: FailoverConfig) -> None:
        """get_active_region must return the secondary region after failover."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        active = router.get_active_region("gpt-5.4")
        assert active == "eu-west"

    def test_get_active_region_returns_none_for_unknown_backend(self, simple_config: FailoverConfig) -> None:
        """get_active_region returns None for a backend not in config.regions."""
        router = FailoverRouter(simple_config)
        assert router.get_active_region("unknown-backend") is None

    def test_enabled_false_makes_all_methods_noop(self) -> None:
        """FailoverConfig(enabled=False) must make get_active_region/is_failed_over/on_cb_state_change all no-ops."""
        cfg = FailoverConfig(enabled=False, regions={"gpt-5.4": ["us-east", "eu-west"]})
        router = FailoverRouter(cfg, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") is None


# ---------------------------------------------------------------------------
# Category C: Recovery (12 tests)
# ---------------------------------------------------------------------------


class TestRecovery:
    """on_cb_state_change("closed") + lazy recovery via observation methods."""

    def test_closed_after_min_duration_restores_primary(self, simple_config: FailoverConfig) -> None:
        """on_cb_state_change("closed") after min_failover_duration elapsed must restore primary."""
        now = [0.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 31.0
        router.on_cb_state_change("gpt-5.4", "open", "closed")
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "us-east"

    def test_closed_before_min_duration_defers_recovery(self, simple_config: FailoverConfig) -> None:
        """on_cb_state_change("closed") before min duration elapsed must keep secondary."""
        now = [0.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 5.0  # only 5s elapsed, min is 30s
        router.on_cb_state_change("gpt-5.4", "open", "closed")
        # Too soon -- must remain failed over
        assert router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "eu-west"

    def test_closed_during_post_commit_window_triggers_recovery(self) -> None:
        """CLOSED after failover commit but before pending clears must recover."""
        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=0.0,
        )
        router = FailoverRouter(cfg, health_probe=lambda _r: True)
        hook_called = [False]
        real_lock = threading.Lock()

        class PostCommitHookLock:
            """Lock proxy that injects a CLOSED notification after each commit-block lock release.

            NOTE: this test deliberately reaches into private attrs
            (_failover_at, _failover_pending) and replaces _lock to simulate a
            CLOSED notification arriving in the post-commit/pre-finally window.
            If FailoverRouter switches to RLock or renames these private
            attributes, this test must be updated.
            """

            def __enter__(self) -> None:
                """Acquire the inner real lock."""
                real_lock.acquire()

            def __exit__(
                self,
                exc_type: object,
                exc_value: object,
                traceback: object,
            ) -> bool:
                """Release the lock, then optionally fire a one-shot CLOSED notification."""
                real_lock.release()
                # After the atomic commit fix, pending is cleared at the same
                # lock acquisition that writes _failover_at, so the "in window"
                # check is now just "commit just happened" (failover_at != None).
                if not hook_called[0] and router._failover_at.get("gpt-5.4") is not None:
                    hook_called[0] = True
                    router.on_cb_state_change("gpt-5.4", "open", "closed")
                return False

        router._lock = PostCommitHookLock()  # type: ignore[assignment]

        router.on_cb_state_change("gpt-5.4", "closed", "open")

        assert hook_called[0]
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "us-east"
        assert router._failover_at["gpt-5.4"] is None

    def test_get_active_region_lazy_recovery_after_min_duration(self) -> None:
        """get_active_region must restore primary after deferred recovery matures."""
        now = [10.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 50.0

        assert router.get_active_region("gpt-5.4") == "us-east"
        assert not router.is_failed_over("gpt-5.4")
        assert router._failover_at["gpt-5.4"] is None

    def test_get_active_region_no_lazy_recovery_before_min_duration(self) -> None:
        """get_active_region must keep secondary before min duration elapses."""
        now = [10.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 20.0

        assert router.get_active_region("gpt-5.4") == "eu-west"
        assert router.is_failed_over("gpt-5.4")

    def test_is_failed_over_lazy_recovery_after_min_duration(self) -> None:
        """is_failed_over must apply lazy recovery so it agrees with get_active_region."""
        now = [10.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 50.0

        # Calling is_failed_over first must itself drive recovery.
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "us-east"

    def test_snapshot_lazy_recovery_after_min_duration(self) -> None:
        """snapshot must apply lazy recovery so it stays consistent with get_active_region."""
        now = [10.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")

        now[0] = 50.0

        # Calling snapshot first must itself drive recovery.
        snap = router.snapshot()
        assert snap["backends"]["gpt-5.4"]["active_region"] == "us-east"
        assert snap["backends"]["gpt-5.4"]["failed_over"] is False
        assert snap["backends"]["gpt-5.4"]["failover_at"] is None
        assert router.get_active_region("gpt-5.4") == "us-east"

    def test_lazy_recovery_negative_elapsed_does_not_recover(self) -> None:
        """_try_lazy_recovery_unlocked must not recover if clock goes backward (elapsed < 0)."""
        now = [100.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        # Clock skews backward.
        now[0] = 50.0
        # Lazy recovery via get_active_region: elapsed = 50-100 = -50 < 30, no-op.
        assert router.get_active_region("gpt-5.4") == "eu-west"
        assert router.is_failed_over("gpt-5.4")

    def test_lazy_recovery_zero_min_duration_recovers_on_first_observation(self) -> None:
        """min_failover_duration_seconds=0 must allow lazy recovery on the first observation post-failover."""
        now = [10.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=0.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")

        # First observation at the same clock instant: elapsed = 0 >= 0 -> recover.
        assert router.get_active_region("gpt-5.4") == "us-east"
        assert not router.is_failed_over("gpt-5.4")

    def test_reset_admin_restores_primary_immediately(self, simple_config: FailoverConfig) -> None:
        """reset() must restore primary regardless of min_failover_duration."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        router.reset("gpt-5.4")
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "us-east"

    def test_closed_when_not_failed_over_is_noop(self, simple_config: FailoverConfig) -> None:
        """on_cb_state_change("closed") when not failed over must not crash."""
        router = FailoverRouter(simple_config)
        router.on_cb_state_change("gpt-5.4", "open", "closed")  # must not raise
        assert not router.is_failed_over("gpt-5.4")

    def test_reset_unknown_backend_is_noop(self, simple_config: FailoverConfig) -> None:
        """reset() for an unknown backend must not create state or raise."""
        router = FailoverRouter(simple_config)
        router.reset("unknown")
        assert "unknown" not in router._active_region
        assert "unknown" not in router._failover_at
        assert "unknown" not in router._failover_pending


# ---------------------------------------------------------------------------
# Category D: Multi-backend isolation (2 tests)
# ---------------------------------------------------------------------------


class TestMultiBackendIsolation:
    """Per-backend state must not leak across backends."""

    def test_failover_for_one_backend_does_not_affect_another(self) -> None:
        """Failover for backend A must not change the active region of backend B."""
        cfg = FailoverConfig(
            enabled=True,
            regions={
                "backend-a": ["us-east", "eu-west"],
                "backend-b": ["ap-southeast", "us-west"],
            },
        )
        router = FailoverRouter(cfg, health_probe=lambda _r: True)
        router.on_cb_state_change("backend-a", "closed", "open")
        assert router.is_failed_over("backend-a")
        assert not router.is_failed_over("backend-b")
        assert router.get_active_region("backend-b") == "ap-southeast"

    def test_snapshot_reports_all_configured_backends(self) -> None:
        """snapshot() must include an entry for every backend in config.regions."""
        cfg = FailoverConfig(
            enabled=True,
            regions={
                "backend-a": ["us-east", "eu-west"],
                "backend-b": ["ap-southeast"],
            },
        )
        router = FailoverRouter(cfg, health_probe=lambda _r: True)
        snap = router.snapshot()
        assert "backends" in snap
        assert "backend-a" in snap["backends"]
        assert "backend-b" in snap["backends"]
        assert snap["backends"]["backend-a"]["active_region"] == "us-east"
        assert snap["backends"]["backend-b"]["failed_over"] is False


# ---------------------------------------------------------------------------
# Category E: LLM CB integration (4 tests)
# ---------------------------------------------------------------------------


class TestLLMCBIntegration:
    """Wiring between LLMCircuitBreaker state transitions and FailoverRouter notifications."""

    def test_llm_cb_failover_none_is_back_compat(self, cb_config: LLMCircuitBreakerConfig) -> None:
        """LLMCircuitBreaker(failover=None) must behave identically to pre-Phase 6."""
        cb = LLMCircuitBreaker(cb_config, failover=None)
        assert cb.failover is None
        cb.record_failure()
        assert cb.failure_count == 1

    def test_record_failure_to_open_calls_on_cb_state_change(
        self,
        cb_config: LLMCircuitBreakerConfig,
        simple_config: FailoverConfig,
    ) -> None:
        """When CB transitions CLOSED -> OPEN via record_failure, on_cb_state_change must be called."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=router)
        for _ in range(cb_config.max_failures):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert router.is_failed_over("gpt-5.4")

    def test_record_success_from_half_open_triggers_closed_notification(
        self,
        cb_config: LLMCircuitBreakerConfig,
        simple_config: FailoverConfig,
    ) -> None:
        """HALF_OPEN -> CLOSED via record_success must notify router of 'closed'."""
        now = [0.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=router)

        # Drive to OPEN -> failover committed
        for _ in range(cb_config.max_failures):
            cb.record_failure()
        assert router.is_failed_over("gpt-5.4")

        # Manually set HALF_OPEN
        with cb._lock:
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_probe_active = False

        # Advance clock past min_failover_duration so recovery can complete.
        now[0] = 31.0

        # record_success: HALF_OPEN -> CLOSED, router should restore primary
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert not router.is_failed_over("gpt-5.4")

    def test_force_open_notifies_router(
        self,
        cb_config: LLMCircuitBreakerConfig,
        simple_config: FailoverConfig,
    ) -> None:
        """force_open must call on_cb_state_change('open') on the router."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=router)
        cb.force_open(reason="test")
        assert router.is_failed_over("gpt-5.4")


# ---------------------------------------------------------------------------
# Category F: Concurrency (4 tests)
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Multi-thread safety of FailoverRouter operations."""

    def test_concurrent_open_events_commit_exactly_one_failover(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """8 threads calling on_cb_state_change("open") simultaneously must yield exactly one failover."""
        probe_call_count = [0]
        probe_lock = threading.Lock()

        def counting_probe(_region: str) -> bool:
            with probe_lock:
                probe_call_count[0] += 1
            return True

        router = FailoverRouter(simple_config, health_probe=counting_probe)
        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                barrier.wait()
                router.on_cb_state_change("gpt-5.4", "closed", "open")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # Exactly one failover committed (subsequent calls are idempotent)
        assert router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "eu-west"
        assert probe_call_count[0] <= 1

    def test_concurrent_get_and_set_does_not_corrupt_state(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """Concurrent get_active_region + on_cb_state_change must not raise or corrupt state."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(500):
                    region = router.get_active_region("gpt-5.4")
                    assert region in (None, "us-east", "eu-west"), f"Unexpected: {region}"
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer() -> None:
            try:
                for i in range(50):
                    if i % 2 == 0:
                        router.on_cb_state_change("gpt-5.4", "closed", "open")
                    else:
                        router.reset("gpt-5.4")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent errors: {errors}"

    def test_reset_during_inflight_probe_aborts_failover(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """reset() during an in-flight probe must prevent the probe from committing."""
        probe_started = threading.Event()
        probe_release = threading.Event()

        def slow_probe(_region: str) -> bool:
            probe_started.set()
            assert probe_release.wait(timeout=2.0)
            return True

        router = FailoverRouter(simple_config, health_probe=slow_probe)
        thread = threading.Thread(
            target=router.on_cb_state_change,
            args=("gpt-5.4", "closed", "open"),
        )

        thread.start()
        assert probe_started.wait(timeout=2.0)
        router.reset("gpt-5.4")
        probe_release.set()
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        assert not router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "us-east"

    def test_closed_during_inflight_probe_aborts_failover(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """CLOSED during an in-flight probe must prevent the probe from committing."""
        probe_started = threading.Event()
        probe_release = threading.Event()

        def slow_probe(_region: str) -> bool:
            probe_started.set()
            assert probe_release.wait(timeout=2.0)
            return True

        router = FailoverRouter(simple_config, health_probe=slow_probe)
        thread = threading.Thread(
            target=router.on_cb_state_change,
            args=("gpt-5.4", "closed", "open"),
        )

        thread.start()
        assert probe_started.wait(timeout=2.0)
        router.on_cb_state_change("gpt-5.4", "open", "closed")
        probe_release.set()
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        assert not router.is_failed_over("gpt-5.4")


# ---------------------------------------------------------------------------
# Category G: Adversarial (6 tests)
# ---------------------------------------------------------------------------


class TestAdversarial:
    """Edge cases and attacker-mindset scenarios."""

    def test_on_cb_state_change_unknown_old_state_does_not_crash(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """on_cb_state_change with a garbage old_state must not raise."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "totally_invalid_state", "open")
        # Should have committed failover normally
        assert router.is_failed_over("gpt-5.4")

    def test_probe_raises_arbitrary_exception_no_crash(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """health_probe that raises ValueError must be caught; no failover."""

        def evil_probe(_region: str) -> bool:
            raise ValueError("bad region")

        router = FailoverRouter(simple_config, health_probe=evil_probe)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert not router.is_failed_over("gpt-5.4")

    def test_clock_backward_skew_does_not_cause_premature_recovery(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """If clock goes backward after failover, recovery must not trigger prematurely."""
        # failover at t=100, close at t=90 (skew): elapsed = 90-100 = -10
        # -10 < 30 (min_duration), so must NOT restore
        now = [100.0]

        def fake_clock() -> float:
            return now[0]

        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east", "eu-west"]},
            min_failover_duration_seconds=30.0,
        )
        router = FailoverRouter(cfg, clock=fake_clock, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert router.is_failed_over("gpt-5.4")

        now[0] = 90.0  # clock skew backward
        router.on_cb_state_change("gpt-5.4", "open", "closed")
        # Both _handle_closed and lazy recovery in is_failed_over must see negative elapsed.
        assert router.is_failed_over("gpt-5.4")
        assert router.get_active_region("gpt-5.4") == "eu-west"

    def test_second_open_when_already_failed_over_is_idempotent(
        self,
        simple_config: FailoverConfig,
    ) -> None:
        """on_cb_state_change("open") while already failed over must not double-failover."""
        probe_count = [0]

        def counting_probe(_region: str) -> bool:
            probe_count[0] += 1
            return True

        router = FailoverRouter(simple_config, health_probe=counting_probe)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        first_probe_count = probe_count[0]

        # Second open event while already on secondary
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert probe_count[0] == first_probe_count, "Probe called again despite already failed over"
        assert router.get_active_region("gpt-5.4") == "eu-west"

    def test_snapshot_is_point_in_time_consistent(self, simple_config: FailoverConfig) -> None:
        """snapshot() must return a dict with expected structure for all backends."""
        router = FailoverRouter(simple_config, health_probe=lambda _r: True)
        snap = router.snapshot()
        assert "backends" in snap
        entry = snap["backends"]["gpt-5.4"]
        assert "active_region" in entry
        assert "failed_over" in entry
        assert "failover_at" in entry
        assert entry["failed_over"] is False
        assert entry["failover_at"] is None

        router.on_cb_state_change("gpt-5.4", "closed", "open")
        snap2 = router.snapshot()
        entry2 = snap2["backends"]["gpt-5.4"]
        assert entry2["failed_over"] is True
        assert isinstance(entry2["failover_at"], float)
        assert entry2["active_region"] == "eu-west"

    def test_no_secondary_configured_logs_warning_no_crash(self) -> None:
        """Backend with only one region (no secondary) must not raise on OPEN."""
        cfg = FailoverConfig(
            enabled=True,
            regions={"gpt-5.4": ["us-east"]},  # no secondary
        )
        router = FailoverRouter(cfg, health_probe=lambda _r: True)
        router.on_cb_state_change("gpt-5.4", "closed", "open")
        assert not router.is_failed_over("gpt-5.4")


# ---------------------------------------------------------------------------
# Category H: Phase 6 integration (4 tests)
# ---------------------------------------------------------------------------


class TestPhase6Integration:
    """Phase 6 BaseException handler integration with LLMCircuitBreaker."""

    @pytest.mark.asyncio
    async def test_base_exception_probe_reopen_notifies_failover(
        self,
        cb_config: LLMCircuitBreakerConfig,
    ) -> None:
        """CancelledError during HALF_OPEN probe must notify failover of re-open."""
        failover = unittest.mock.Mock()
        cb = LLMCircuitBreaker(
            cb_config,
            backend_name="gpt-5.4",
            failover=failover,
        )
        with cb._lock:
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_probe_active = False

        async def cancelled_probe() -> None:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await cb.call_with_retry(cancelled_probe, max_retries=1)

        failover.on_cb_state_change.assert_called_with(
            "gpt-5.4",
            "half_open",
            "open",
        )

    def test_notify_failover_propagates_keyboard_interrupt(
        self,
        cb_config: LLMCircuitBreakerConfig,
    ) -> None:
        """A router raising KeyboardInterrupt must propagate; CB must not silently swallow it."""
        failover = unittest.mock.Mock()
        failover.on_cb_state_change.side_effect = KeyboardInterrupt()
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=failover)

        with pytest.raises(KeyboardInterrupt):
            for _ in range(cb_config.max_failures):
                cb.record_failure()

    def test_notify_failover_propagates_system_exit(
        self,
        cb_config: LLMCircuitBreakerConfig,
    ) -> None:
        """A router raising SystemExit must propagate; CB must not silently swallow it."""
        failover = unittest.mock.Mock()
        failover.on_cb_state_change.side_effect = SystemExit(1)
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=failover)

        with pytest.raises(SystemExit):
            for _ in range(cb_config.max_failures):
                cb.record_failure()

    def test_notify_failover_swallows_generic_exception(
        self,
        cb_config: LLMCircuitBreakerConfig,
    ) -> None:
        """A router raising RuntimeError must be swallowed; CB state mutation completes."""
        failover = unittest.mock.Mock()
        failover.on_cb_state_change.side_effect = RuntimeError("router bug")
        cb = LLMCircuitBreaker(cb_config, backend_name="gpt-5.4", failover=failover)

        # Drive to OPEN. record_failure must not raise even though router raises.
        for _ in range(cb_config.max_failures):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert failover.on_cb_state_change.called
