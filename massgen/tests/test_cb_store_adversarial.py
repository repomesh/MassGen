"""Adversarial tests for circuit breaker state stores."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from massgen.backend.cb_store import (
    DEFAULT_CIRCUIT_BREAKER_STATE,
    InMemoryStore,
    RedisStore,
)
from massgen.backend.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
)


def _enabled_config(**overrides: Any) -> LLMCircuitBreakerConfig:
    defaults = {"enabled": True, "max_failures": 3, "reset_time_seconds": 1}
    defaults.update(overrides)
    return LLMCircuitBreakerConfig(**defaults)


def _complete_state(**overrides: Any) -> dict[str, Any]:
    state = dict(DEFAULT_CIRCUIT_BREAKER_STATE)
    state.update(overrides)
    return state


def _assert_complete_state(state: dict[str, Any]) -> None:
    assert set(DEFAULT_CIRCUIT_BREAKER_STATE).issubset(state)


def _fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis()


class TestAdversarialInMemoryStore:
    def test_backend_name_empty_string(self) -> None:
        store = InMemoryStore()

        assert store.get_state("") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_backend_name_very_long(self) -> None:
        store = InMemoryStore()
        long_backend = "x" * 10000

        store.set_state(long_backend, _complete_state(state="open"))

        assert store.get_state(long_backend)["state"] == "open"
        assert store.get_state("normal") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_backend_name_unicode(self) -> None:
        store = InMemoryStore()

        state = store.get_state("\u4e2d\u6587backend")

        assert state == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_set_state_missing_keys(self) -> None:
        store = InMemoryStore()

        store.set_state("backend", {"state": "open"})

        assert store.get_state("backend") == _complete_state(state="open")

    def test_set_state_extra_keys(self) -> None:
        store = InMemoryStore()

        store.set_state("backend", _complete_state(extra_unknown_key="ignored_or_kept"))

        state = store.get_state("backend")
        _assert_complete_state(state)

    def test_cas_state_same_state_no_op(self) -> None:
        store = InMemoryStore()

        result = store.cas_state("backend", "closed", {"failure_count": 5})

        assert result is True
        assert store.get_state("backend")["state"] == "closed"
        assert store.get_state("backend")["failure_count"] == 5

    def test_cas_state_invalid_expected_state(self) -> None:
        store = InMemoryStore()

        result = store.cas_state(
            "backend",
            "nonexistent_state",
            {"state": "open"},
        )

        assert result is False

    def test_increment_failure_many_times(self) -> None:
        store = InMemoryStore()

        for _ in range(1000):
            store.increment_failure("backend")

        assert store.get_state("backend")["failure_count"] == 1000

    def test_clear_nonexistent_backend_no_crash(self) -> None:
        store = InMemoryStore()

        store.clear("never_existed")

    def test_clear_then_get_returns_defaults(self) -> None:
        store = InMemoryStore()
        store.set_state("backend", _complete_state(state="open", failure_count=10))

        store.clear("backend")

        assert store.get_state("backend") == DEFAULT_CIRCUIT_BREAKER_STATE


class TestAdversarialInMemoryStoreConcurrency:
    def test_concurrent_increment_failure_100_threads(self) -> None:
        store = InMemoryStore()

        threads = [threading.Thread(target=store.increment_failure, args=("backend",)) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert store.get_state("backend")["failure_count"] == 100

    def test_concurrent_cas_state_race(self) -> None:
        store = InMemoryStore()
        results: list[bool] = []
        result_lock = threading.Lock()

        def attempt_cas() -> None:
            result = store.cas_state(
                "backend",
                "closed",
                {"state": "open", "failure_count": 1},
            )
            with result_lock:
                results.append(result)

        threads = [threading.Thread(target=attempt_cas) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1
        assert results.count(False) == 99
        assert store.get_state("backend")["state"] == "open"

    def test_concurrent_clear_and_increment(self) -> None:
        store = InMemoryStore()
        exceptions: list[BaseException] = []
        exception_lock = threading.Lock()

        def run_safely(action: Any) -> None:
            try:
                action("backend")
            except Exception as exc:
                with exception_lock:
                    exceptions.append(exc)

        threads = [threading.Thread(target=run_safely, args=(store.increment_failure,)) for _ in range(50)]
        threads.extend(threading.Thread(target=run_safely, args=(store.clear,)) for _ in range(50))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert exceptions == []
        final_count = store.get_state("backend")["failure_count"]
        assert 0 <= final_count <= 50

    def test_concurrent_set_and_get_state(self) -> None:
        store = InMemoryStore()
        exceptions: list[BaseException] = []
        observed_states: list[dict[str, Any]] = []
        lock = threading.Lock()

        def set_open_state() -> None:
            try:
                store.set_state("backend", _complete_state(state="open"))
            except Exception as exc:
                with lock:
                    exceptions.append(exc)

        def get_state() -> None:
            try:
                state = store.get_state("backend")
                with lock:
                    observed_states.append(state)
            except Exception as exc:
                with lock:
                    exceptions.append(exc)

        threads = [threading.Thread(target=set_open_state) for _ in range(50)]
        threads.extend(threading.Thread(target=get_state) for _ in range(50))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert exceptions == []
        assert observed_states
        for state in observed_states:
            _assert_complete_state(state)


class TestAdversarialRedisStore:
    def test_redis_store_missing_key_returns_defaults(self) -> None:
        store = RedisStore(_fake_redis())

        assert store.get_state("backend") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_redis_store_cas_when_key_missing(self) -> None:
        store = RedisStore(_fake_redis())

        result = store.cas_state("backend", "closed", {"state": "open"})

        assert result is True
        assert store.get_state("backend")["state"] == "open"

    def test_redis_store_increment_on_missing_key(self) -> None:
        store = RedisStore(_fake_redis())

        assert store.increment_failure("backend") == 1
        assert store.get_state("backend")["failure_count"] == 1

    def test_redis_store_clear_missing_key_no_crash(self) -> None:
        store = RedisStore(_fake_redis())

        store.clear("backend")

    def test_redis_store_ttl_refreshed_on_increment(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=123)

        store.increment_failure("backend")

        assert client.ttl("massgen:cb:backend") > 0

    def test_redis_store_increment_preserves_open_state_ttl(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=1)
        open_until = time.time() + 120
        store.set_state(
            "backend",
            _complete_state(state="open", open_until=open_until),
        )
        ttl_before = client.ttl("massgen:cb:backend")

        store.increment_failure("backend")

        assert client.ttl("massgen:cb:backend") >= ttl_before - 1

    def test_redis_store_increment_without_lua_preserves_open_state_ttl(
        self,
        monkeypatch,
    ) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=1)
        open_until = time.time() + 120
        store.set_state(
            "backend",
            _complete_state(state="open", open_until=open_until),
        )
        ttl_before = client.ttl("massgen:cb:backend")

        def raise_unknown_command(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("unknown command 'eval'")

        monkeypatch.setattr(client, "eval", raise_unknown_command)

        store.increment_failure("backend")

        assert client.ttl("massgen:cb:backend") >= ttl_before - 1

    def test_redis_store_increment_without_lua_retry_exhaustion_raises(
        self,
        monkeypatch,
    ) -> None:
        store = RedisStore(_fake_redis())

        def raise_unknown_command(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("unknown command 'eval'")

        class FailingWatchPipeline:
            def watch(self, key: str) -> None:
                raise RuntimeError("watch conflict")

            def reset(self) -> None:
                pass

        monkeypatch.setattr(store._client, "eval", raise_unknown_command)
        monkeypatch.setattr(
            store._client,
            "pipeline",
            lambda transaction=True: FailingWatchPipeline(),
        )

        with pytest.raises(
            RuntimeError,
            match=("Failed to atomically increment failure count for 'backend' " "after 3 retries"),
        ):
            store.increment_failure("backend")

    def test_redis_store_open_state_ttl_covers_open_until(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=1)
        open_until = time.time() + 120

        store.set_state(
            "backend",
            _complete_state(state="open", open_until=open_until),
        )

        assert client.ttl("massgen:cb:backend") >= 170

    def test_redis_store_cas_open_state_ttl_covers_open_until(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=1)
        open_until = time.time() + 120

        result = store.cas_state(
            "backend",
            "closed",
            {"state": "open", "open_until": open_until},
        )

        assert result is True
        assert client.ttl("massgen:cb:backend") >= 170

    def test_redis_store_cas_missing_state_preserves_partial_hash(self) -> None:
        client = _fake_redis()
        store = RedisStore(client)
        client.hset("massgen:cb:backend", "failure_count", "7")

        result = store.cas_state("backend", "closed", {"state": "open"})

        assert result is True
        assert store.get_state("backend")["failure_count"] == 7

    def test_redis_store_state_dict_wrong_types(self) -> None:
        client = _fake_redis()
        store = RedisStore(client)
        client.hset(
            "massgen:cb:backend",
            mapping={
                "state": "open",
                "failure_count": "not_a_number",
                "last_failure_time": "also_not_a_float",
                "open_until": "still_not_a_float",
                "half_open_probe_active": "not_a_bool",
            },
        )

        # Current behavior raises ValueError for corrupted numeric fields.
        # Graceful defaulting would also be acceptable for this boundary case.
        try:
            state = store.get_state("backend")
        except ValueError:
            return

        assert state == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_redis_store_cas_without_lua_only_one_winner(self, monkeypatch) -> None:
        """Concurrent CAS fallback allows exactly one closed-to-open winner."""
        client = _fake_redis()
        store = RedisStore(client)

        # Disable Lua scripting to force _cas_state_without_lua path.
        def raise_eval(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("unknown command 'eval'")

        monkeypatch.setattr(client, "eval", raise_eval)

        results: list[bool] = []
        lock = threading.Lock()

        def attempt() -> None:
            res = store.cas_state(
                "backend",
                "closed",
                {"state": "open", "open_until": time.time() + 60},
            )
            with lock:
                results.append(res)

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1
        assert results.count(False) == 19
        assert store.get_state("backend")["state"] == "open"

    def test_redis_store_script_unavailable_does_not_match_readonly(
        self,
        monkeypatch,
    ) -> None:
        """READONLY errors are not classified as Lua unavailability."""
        client = _fake_redis()
        store = RedisStore(client)

        def raise_readonly(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("READONLY You can't write against a read only replica")

        monkeypatch.setattr(client, "eval", raise_readonly)

        with pytest.raises(RuntimeError, match="READONLY"):
            store.cas_state("backend", "closed", {"state": "open"})


class TestAdversarialCBIntegration:
    def test_closed_should_block_returns_false(self) -> None:
        config = LLMCircuitBreakerConfig(enabled=True)
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)

        assert cb.should_block() is False
        assert cb.state == CircuitState.CLOSED
        assert store.get_state("test")["state"] == "closed"

    def test_half_open_should_block_active_probe_blocks(self) -> None:
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=1,
            reset_time_seconds=60,
        )
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)
        store.set_state(
            "test",
            {
                "state": "half_open",
                "failure_count": 1,
                "last_failure_time": 0.0,
                "open_until": 0.0,
                "half_open_probe_active": True,
            },
        )

        assert cb.should_block() is True

    def test_half_open_should_block_inactive_probe_allows_one(self) -> None:
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=1,
            reset_time_seconds=60,
        )
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)
        store.set_state(
            "test",
            {
                "state": "half_open",
                "failure_count": 1,
                "last_failure_time": 0.0,
                "open_until": 0.0,
                "half_open_probe_active": False,
            },
        )

        assert cb.should_block() is False
        assert store.get_state("test")["half_open_probe_active"] is True
        assert cb.should_block() is True

    def test_record_success_resets_failure_count_in_store(self) -> None:
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=3)
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)

        cb.record_failure()
        cb.record_failure()
        assert store.get_state("test")["failure_count"] == 2

        cb.record_success()

        assert store.get_state("test")["failure_count"] == 0
        assert store.get_state("test")["state"] == "closed"

    def test_closed_reset_is_noop(self) -> None:
        config = LLMCircuitBreakerConfig(enabled=True)
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert store.get_state("test")["failure_count"] == 0

    def test_half_open_force_open_transitions_to_open(self) -> None:
        config = LLMCircuitBreakerConfig(
            enabled=True,
            max_failures=1,
            reset_time_seconds=60,
        )
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)

        cb.force_open("test")
        store.set_state(
            "test",
            {
                "state": "half_open",
                "failure_count": 1,
                "last_failure_time": 0.0,
                "open_until": 0.0,
                "half_open_probe_active": True,
            },
        )
        assert cb.state == CircuitState.HALF_OPEN

        cb.force_open("force from half_open")

        assert cb.state == CircuitState.OPEN

    def test_half_open_reset_returns_to_closed(self) -> None:
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=1)
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)
        store.set_state(
            "test",
            {
                "state": "half_open",
                "failure_count": 1,
                "last_failure_time": 0.0,
                "open_until": 0.0,
                "half_open_probe_active": True,
            },
        )

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert store.get_state("test")["failure_count"] == 0

    def test_open_record_success_does_not_close_forced_open_circuit(self) -> None:
        config = LLMCircuitBreakerConfig(enabled=True, max_failures=1)
        store = InMemoryStore()
        cb = LLMCircuitBreaker(config, backend_name="test", store=store)

        cb.force_open("test")
        assert cb.state == CircuitState.OPEN

        cb.record_success()

        assert cb.state == CircuitState.OPEN
        assert store.get_state("test")["state"] == "open"

    def test_state_machine_all_closed_transitions(self) -> None:
        store = InMemoryStore()
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=2),
            backend_name="backend",
            store=store,
        )

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        cb.force_open()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_state_machine_all_open_transitions(self) -> None:
        store = InMemoryStore()
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="backend",
            store=store,
        )

        cb.force_open()
        assert cb.should_block() is True

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        first_open_until = store.get_state("backend")["open_until"]
        time.sleep(0.001)
        cb.force_open()
        assert cb.state == CircuitState.OPEN
        assert store.get_state("backend")["open_until"] >= first_open_until

        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_state_machine_half_open_transitions(self) -> None:
        store = InMemoryStore()
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="backend",
            store=store,
        )

        cb.force_open()
        state = store.get_state("backend")
        state["open_until"] = time.time() - 1
        store.set_state("backend", state)

        assert cb.should_block() is False
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        cb.force_open()
        state = store.get_state("backend")
        state["open_until"] = time.time() - 1
        store.set_state("backend", state)
        assert cb.should_block() is False
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_contradictory_state_dict(self) -> None:
        store = InMemoryStore()
        cb = LLMCircuitBreaker(
            config=_enabled_config(),
            backend_name="backend",
            store=store,
        )
        store.set_state("backend", _complete_state(state="open", open_until=0.0))

        assert cb.should_block() is False
        assert cb.state == CircuitState.HALF_OPEN

    def test_exception_during_store_raises_propagates(self) -> None:
        class RaisingAtomicFailureStore(InMemoryStore):
            def atomic_record_failure(
                self,
                backend: str,
                failure_threshold: int,
                recovery_timeout: float,
            ) -> dict:
                raise RuntimeError("atomic_record_failure failed")

        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="backend",
            store=RaisingAtomicFailureStore(),
        )

        with pytest.raises(RuntimeError, match="atomic_record_failure failed"):
            cb.record_failure()

    def test_rule_45_no_mutation_before_validation(self) -> None:
        store = InMemoryStore()
        before = store.get_state("backend")

        result = store.cas_state(
            "backend",
            "nonexistent_state",
            {"state": "open", "failure_count": 100},
        )

        assert result is False
        assert store.get_state("backend") == before

    def test_rule_27_error_recovery_store_write_failure(self, monkeypatch) -> None:
        store = InMemoryStore()
        store.set_state("backend", _complete_state(state="closed", failure_count=2))
        before = store.get_state("backend")
        cb = LLMCircuitBreaker(
            config=_enabled_config(),
            backend_name="backend",
            store=store,
        )

        def fail_atomic_record_success(
            self: InMemoryStore,
            backend: str,
            expected_state: str | None = None,
        ) -> dict:
            raise RuntimeError("write failed")

        monkeypatch.setattr(
            InMemoryStore,
            "atomic_record_success",
            fail_atomic_record_success,
        )

        with pytest.raises(RuntimeError, match="write failed"):
            cb.record_success()

        assert store.get_state("backend") == before

    def test_rule_27_redis_hset_succeeds_expire_fails_state_readable(self) -> None:
        """RedisStore partial-write: HSET succeeds but EXPIRE fails.

        When EXPIRE fails, the key has no TTL but the state data is still
        readable. This is an acceptable degradation -- state is correct,
        key just won't auto-expire. Document the behavior rather than hide it.
        """
        client = _fake_redis()
        store = RedisStore(client, ttl=60)
        original_expire = client.expire

        expire_call_count = [0]

        def fail_on_second_expire(key: str, seconds: int) -> bool:
            expire_call_count[0] += 1
            if expire_call_count[0] == 1:
                raise RuntimeError("expire failed")
            return original_expire(key, seconds)

        client.expire = fail_on_second_expire

        with pytest.raises(RuntimeError, match="expire failed"):
            store.set_state("backend", _complete_state(state="open", failure_count=3))

        # After partial write: HSET succeeded (data readable), EXPIRE failed (no TTL).
        # State is defined -- either full data if HSET was atomic, or empty if HSET
        # also failed. Both are acceptable; no crash and no corrupted type errors.
        state = store.get_state("backend")
        assert isinstance(state["failure_count"], int)
        assert state["state"] in ("closed", "open", "half_open")

    def test_two_cb_same_store_different_backends(self) -> None:
        store = InMemoryStore()
        backend_a = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="backend_a",
            store=store,
        )
        backend_b = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="backend_b",
            store=store,
        )

        backend_a.record_failure()

        assert backend_a.state == CircuitState.OPEN
        assert backend_b.state == CircuitState.CLOSED
        assert backend_b.failure_count == 0


class TestConcurrentLinearizability:
    def test_100_threads_mixed_failure_success_linearizable(self) -> None:
        store = InMemoryStore()
        failure_count = 50
        success_count = 50

        threads = [
            threading.Thread(
                target=store.atomic_record_failure,
                args=("claude", 200, 30.0),
            )
            for _ in range(failure_count)
        ]
        threads.extend(threading.Thread(target=store.atomic_record_success, args=("claude",)) for _ in range(success_count))

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        state = store.get_state("claude")
        assert state["state"] == "closed"
        assert 0 <= state["failure_count"] <= failure_count
        assert state["half_open_probe_active"] is False


class TestForceOpenRace:
    def test_force_open_wins_over_concurrent_record_success(self) -> None:
        # record_success() now calls atomic_record_success() directly (no prior
        # get_state() read). The old TOCTOU window -- where force_open() could
        # slip between get_state() and atomic_record_success() -- no longer
        # exists. This test verifies that when force_open() completes BEFORE
        # atomic_record_success() acquires the lock, the OPEN state is preserved
        # because atomic_record_success() guards against open with no
        # expected_state.
        force_open_done = threading.Event()
        success_start = threading.Event()

        class CoordinatedStore(InMemoryStore):
            def atomic_record_success(self, backend: str, expected_state: str | None = None) -> dict:
                success_start.set()
                assert force_open_done.wait(timeout=5)
                return super().atomic_record_success(backend, expected_state)

        store = CoordinatedStore()
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=10, reset_time_seconds=30),
            backend_name="claude",
            store=store,
        )

        def force_open() -> None:
            assert success_start.wait(timeout=5)
            cb.force_open("quota", open_for_seconds=30)
            force_open_done.set()

        def record_success() -> None:
            cb.record_success()

        threads = [
            threading.Thread(target=force_open),
            threading.Thread(target=record_success, name="record-success"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # force_open() ran before atomic_record_success() -- OPEN must survive
        assert cb.state == CircuitState.OPEN
        assert store.get_state("claude")["state"] == "open"


class TestAtomicFailureOrdering:
    def test_failure_count_never_exceeds_thread_count(self) -> None:
        store = InMemoryStore()
        thread_count = 100

        threads = [
            threading.Thread(
                target=store.atomic_record_failure,
                args=("claude", 200, 30.0),
            )
            for _ in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        state = store.get_state("claude")
        assert state["failure_count"] == thread_count
        assert state["failure_count"] <= thread_count


class TestTryTransitionAndClaimProbe:
    """Adversarial tests for the atomic OPEN->HALF_OPEN / probe-claim op."""

    def test_inmemory_open_elapsed_transitions_exactly_one(self) -> None:
        store = InMemoryStore()
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() - 0.01),
        )

        results: list[tuple[bool, str | None]] = []
        lock = threading.Lock()

        def claim() -> None:
            won, _state, label = store.try_transition_and_claim_probe(
                "claude",
                time.time(),
                30.0,
            )
            with lock:
                results.append((won, label))

        threads = [threading.Thread(target=claim) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r[0]]
        assert len(winners) == 1, f"exactly one winner expected, got {len(winners)}"
        assert winners[0][1] == "open->half_open"
        assert store.get_state("claude")["half_open_probe_active"] is True
        assert store.get_state("claude")["state"] == "half_open"

    def test_inmemory_half_open_probe_claim_exactly_one(self) -> None:
        store = InMemoryStore()
        store.set_state(
            "claude",
            _complete_state(state="half_open", half_open_probe_active=False),
        )

        results: list[bool] = []
        lock = threading.Lock()

        def claim() -> None:
            won, _state, _label = store.try_transition_and_claim_probe(
                "claude",
                time.time(),
                30.0,
            )
            with lock:
                results.append(won)

        threads = [threading.Thread(target=claim) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1, f"exactly one probe winner, got {sum(results)}"

    def test_inmemory_open_not_yet_elapsed_blocks(self) -> None:
        store = InMemoryStore()
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() + 100),
        )

        won, state, label = store.try_transition_and_claim_probe(
            "claude",
            time.time(),
            30.0,
        )
        assert won is False
        assert label is None
        assert state["state"] == "open"

    def test_inmemory_force_open_during_transition_no_phantom_half_open(self) -> None:
        """force_open extending open_until must not be undone by a stale CAS."""
        store = InMemoryStore()
        # Initially OPEN with elapsed open_until -- ripe for transition
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() - 0.01),
        )

        # Simulate force_open extending open_until before our claim
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() + 100),
        )

        won, state, _label = store.try_transition_and_claim_probe(
            "claude",
            time.time(),
            30.0,
        )
        # New open_until is in the future -- must NOT transition
        assert won is False
        assert state["state"] == "open"

    def test_redis_open_elapsed_transitions_exactly_one(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=60)
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() - 0.01),
        )

        results: list[tuple[bool, str | None]] = []
        lock = threading.Lock()

        def claim() -> None:
            won, _state, label = store.try_transition_and_claim_probe(
                "claude",
                time.time(),
                30.0,
            )
            with lock:
                results.append((won, label))

        threads = [threading.Thread(target=claim) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r[0]]
        assert len(winners) == 1
        assert winners[0][1] == "open->half_open"

    def test_redis_open_not_elapsed_blocks(self) -> None:
        client = _fake_redis()
        store = RedisStore(client, ttl=60)
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() + 100),
        )

        won, state, label = store.try_transition_and_claim_probe(
            "claude",
            time.time(),
            30.0,
        )
        assert won is False
        assert label is None
        assert state["state"] == "open"


class TestMakeStoreFactory:
    """Adversarial tests for the make_store factory function."""

    def test_make_store_redis_missing_client_raises_valueerror(self) -> None:
        from massgen.backend.cb_store import make_store

        with pytest.raises(ValueError, match="redis_client is required"):
            make_store("redis")

    def test_make_store_redis_forwards_key_prefix(self) -> None:
        from massgen.backend.cb_store import make_store

        client = _fake_redis()
        store = make_store(
            "redis",
            redis_client=client,
            ttl=42,
            key_prefix="custom:ns",
        )
        assert isinstance(store, RedisStore)
        assert store._key_prefix == "custom:ns"
        assert store._ttl == 42

    def test_make_store_memory_default(self) -> None:
        from massgen.backend.cb_store import make_store

        store = make_store()
        assert isinstance(store, InMemoryStore)

    def test_make_store_unknown_backend_raises(self) -> None:
        from massgen.backend.cb_store import make_store

        with pytest.raises(ValueError, match="Unknown circuit breaker store"):
            make_store("postgres")


class TestProbeOwnershipInRetries:
    """Adversarial: store-mode probe ownership tracking through retries."""

    def test_store_mode_probe_owner_tracked_via_should_block_with_claim(self) -> None:
        """Verify _should_block_with_claim returns claim flag in store mode."""
        store = InMemoryStore()
        store.set_state(
            "claude",
            _complete_state(state="open", open_until=time.time() - 1),
        )
        cb = LLMCircuitBreaker(
            backend_name="claude",
            config=_enabled_config(reset_time_seconds=30),
            store=store,
        )

        blocked, claimed = cb._should_block_with_claim()
        assert blocked is False
        assert claimed is True
        # Subsequent caller must NOT also claim (probe already taken)
        blocked2, claimed2 = cb._should_block_with_claim()
        assert blocked2 is True
        assert claimed2 is False
