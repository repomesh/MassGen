"""Tests for distributed circuit breaker state stores."""

from __future__ import annotations

import threading

import pytest

from massgen.backend.cb_store import (
    DEFAULT_CIRCUIT_BREAKER_STATE,
    InMemoryStore,
    RedisStore,
    make_store,
)
from massgen.backend.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
)


def _enabled_config(**overrides) -> LLMCircuitBreakerConfig:
    defaults = {"enabled": True, "max_failures": 3, "reset_time_seconds": 1}
    defaults.update(overrides)
    return LLMCircuitBreakerConfig(**defaults)


def _open_state(**overrides) -> dict:
    state = {
        "state": "open",
        "failure_count": 2,
        "last_failure_time": 10.5,
        "open_until": 20.5,
        "half_open_probe_active": True,
    }
    state.update(overrides)
    return state


def _fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis()


class TestInMemoryStoreHappyPath:
    def test_get_state_returns_defaults_for_new_backend(self):
        store = InMemoryStore()

        assert store.get_state("claude") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_set_state_persists_values(self):
        store = InMemoryStore()
        expected = _open_state()

        store.set_state("claude", expected)

        assert store.get_state("claude") == expected

    def test_get_state_returns_copy_not_reference(self):
        store = InMemoryStore()
        state = store.get_state("claude")

        state["state"] = "open"

        assert store.get_state("claude")["state"] == "closed"

    def test_cas_state_succeeds_when_state_matches(self):
        store = InMemoryStore()

        result = store.cas_state("claude", "closed", {"state": "open"})

        assert result is True
        assert store.get_state("claude")["state"] == "open"

    def test_cas_state_fails_when_state_mismatches(self):
        store = InMemoryStore()

        result = store.cas_state("claude", "open", {"state": "half_open"})

        assert result is False
        assert store.get_state("claude")["state"] == "closed"

    def test_increment_failure_returns_new_count(self):
        store = InMemoryStore()

        assert store.increment_failure("claude") == 1

    def test_increment_failure_is_sequential(self):
        store = InMemoryStore()

        assert [store.increment_failure("claude") for _ in range(3)] == [1, 2, 3]

    def test_clear_resets_to_defaults(self):
        store = InMemoryStore()
        store.set_state("claude", _open_state())

        store.clear("claude")

        assert store.get_state("claude") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_multiple_backends_isolated(self):
        store = InMemoryStore()

        store.set_state("claude", _open_state())

        assert store.get_state("openai") == DEFAULT_CIRCUIT_BREAKER_STATE
        assert store.get_state("claude")["state"] == "open"

    def test_set_state_full_dict_roundtrip(self):
        store = InMemoryStore()
        expected = _open_state(
            state="half_open",
            failure_count=7,
            half_open_probe_active=False,
        )

        store.set_state("claude", expected)

        assert store.get_state("claude") == expected


class TestInMemoryStoreThreadSafety:
    def test_concurrent_increment_failure_100_threads(self):
        store = InMemoryStore()

        threads = [threading.Thread(target=store.increment_failure, args=("claude",)) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert store.get_state("claude")["failure_count"] == 100

    def test_concurrent_cas_state_only_one_wins(self):
        store = InMemoryStore()
        results: list[bool] = []
        lock = threading.Lock()

        def attempt_cas() -> None:
            result = store.cas_state("claude", "closed", {"state": "open"})
            with lock:
                results.append(result)

        threads = [threading.Thread(target=attempt_cas) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1
        assert results.count(False) == 99


class TestInMemoryStoreAtomicRecordFailure:
    def test_basic_increment_increments_count(self):
        store = InMemoryStore()

        state = store.atomic_record_failure(
            "claude",
            failure_threshold=3,
            recovery_timeout=1.0,
        )

        assert state["failure_count"] == 1
        assert store.get_state("claude")["failure_count"] == 1

    def test_closed_to_open_transition_at_threshold(self):
        store = InMemoryStore()

        for _ in range(3):
            state = store.atomic_record_failure(
                "claude",
                failure_threshold=3,
                recovery_timeout=1.0,
            )

        assert state["state"] == "open"
        assert state["failure_count"] == 3
        assert state["open_until"] > state["last_failure_time"]

    def test_half_open_to_open_on_any_failure(self):
        store = InMemoryStore()
        store.set_state(
            "claude",
            {"state": "half_open", "half_open_probe_active": True},
        )

        state = store.atomic_record_failure(
            "claude",
            failure_threshold=5,
            recovery_timeout=1.0,
        )

        assert state["state"] == "open"
        assert state["half_open_probe_active"] is False
        assert state["failure_count"] == 1

    def test_below_threshold_stays_closed(self):
        store = InMemoryStore()

        for _ in range(3):
            state = store.atomic_record_failure(
                "claude",
                failure_threshold=5,
                recovery_timeout=1.0,
            )

        assert state["state"] == "closed"
        assert state["failure_count"] == 3

    def test_concurrent_100_threads_exact_count(self):
        store = InMemoryStore()

        threads = [
            threading.Thread(
                target=store.atomic_record_failure,
                args=("claude", 200, 1.0),
            )
            for _ in range(100)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert store.get_state("claude")["failure_count"] == 100


class TestInMemoryStoreAtomicRecordSuccess:
    def test_closed_resets_failure_count(self):
        store = InMemoryStore()
        store.set_state("claude", {"state": "closed", "failure_count": 5})

        state = store.atomic_record_success("claude")

        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["half_open_probe_active"] is False

    def test_half_open_transitions_to_closed(self):
        store = InMemoryStore()
        store.set_state(
            "claude",
            {
                "state": "half_open",
                "failure_count": 5,
                "half_open_probe_active": True,
            },
        )

        state = store.atomic_record_success("claude")

        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["half_open_probe_active"] is False

    def test_open_with_no_expected_state_is_noop(self):
        store = InMemoryStore()
        expected = _open_state(failure_count=5, half_open_probe_active=False)
        store.set_state("claude", expected)

        state = store.atomic_record_success("claude")

        # state includes _prev_state / _prev_was_half_open metadata -- compare core fields only
        core_keys = set(expected.keys())
        assert {k: state[k] for k in core_keys} == expected
        assert state["_prev_state"] == "open"
        assert state["_prev_was_half_open"] is False
        assert store.get_state("claude") == expected

    def test_expected_state_mismatch_is_noop(self):
        store = InMemoryStore()
        expected = {"state": "closed", "failure_count": 5}
        store.set_state("claude", expected)

        state = store.atomic_record_success("claude", expected_state="half_open")

        assert state["state"] == "closed"
        assert state["failure_count"] == 5


class TestRedisStoreHappyPath:
    def test_get_state_returns_defaults_for_new_backend(self):
        store = RedisStore(_fake_redis())

        assert store.get_state("claude") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_set_and_get_state_roundtrip(self):
        store = RedisStore(_fake_redis())
        expected = _open_state()

        store.set_state("claude", expected)

        assert store.get_state("claude") == expected

    def test_cas_state_succeeds_when_matches(self):
        store = RedisStore(_fake_redis())
        store.set_state("claude", DEFAULT_CIRCUIT_BREAKER_STATE)

        result = store.cas_state("claude", "closed", {"state": "open"})

        assert result is True
        assert store.get_state("claude")["state"] == "open"

    def test_cas_state_fails_when_mismatches(self):
        store = RedisStore(_fake_redis())
        store.set_state("claude", DEFAULT_CIRCUIT_BREAKER_STATE)

        result = store.cas_state("claude", "open", {"state": "half_open"})

        assert result is False
        assert store.get_state("claude")["state"] == "closed"

    def test_increment_failure_atomic(self):
        store = RedisStore(_fake_redis())

        assert [store.increment_failure("claude") for _ in range(3)] == [1, 2, 3]
        assert store.get_state("claude")["failure_count"] == 3

    def test_clear_removes_key(self):
        store = RedisStore(_fake_redis())
        store.set_state("claude", _open_state())

        store.clear("claude")

        assert store.get_state("claude") == DEFAULT_CIRCUIT_BREAKER_STATE

    def test_ttl_set_on_set_state(self):
        client = _fake_redis()
        store = RedisStore(client, ttl=123)

        store.set_state("claude", DEFAULT_CIRCUIT_BREAKER_STATE)

        assert client.ttl("massgen:cb:claude") == 123


class TestRedisStoreAtomicRecordFailure:
    def test_basic_increment_increments_count(self):
        store = RedisStore(_fake_redis())

        state = store.atomic_record_failure(
            "claude",
            failure_threshold=3,
            recovery_timeout=1.0,
        )

        assert state["failure_count"] == 1
        assert store.get_state("claude")["failure_count"] == 1

    def test_closed_to_open_transition_at_threshold(self):
        store = RedisStore(_fake_redis())

        for _ in range(3):
            state = store.atomic_record_failure(
                "claude",
                failure_threshold=3,
                recovery_timeout=1.0,
            )

        assert state["state"] == "open"
        assert state["failure_count"] == 3
        assert state["open_until"] > state["last_failure_time"]

    def test_half_open_to_open_on_any_failure(self):
        store = RedisStore(_fake_redis())
        store.set_state(
            "claude",
            {"state": "half_open", "half_open_probe_active": True},
        )

        state = store.atomic_record_failure(
            "claude",
            failure_threshold=5,
            recovery_timeout=1.0,
        )

        assert state["state"] == "open"
        assert state["half_open_probe_active"] is False
        assert state["failure_count"] == 1

    def test_below_threshold_stays_closed(self):
        store = RedisStore(_fake_redis())

        for _ in range(3):
            state = store.atomic_record_failure(
                "claude",
                failure_threshold=5,
                recovery_timeout=1.0,
            )

        assert state["state"] == "closed"
        assert state["failure_count"] == 3

    def test_concurrent_100_threads_exact_count(self):
        store = RedisStore(_fake_redis())

        threads = [
            threading.Thread(
                target=store.atomic_record_failure,
                args=("claude", 200, 1.0),
            )
            for _ in range(100)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert store.get_state("claude")["failure_count"] == 100


class TestRedisStoreAtomicRecordSuccess:
    def test_closed_resets_failure_count(self):
        store = RedisStore(_fake_redis())
        store.set_state("claude", {"state": "closed", "failure_count": 5})

        state = store.atomic_record_success("claude")

        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["half_open_probe_active"] is False

    def test_half_open_transitions_to_closed(self):
        store = RedisStore(_fake_redis())
        store.set_state(
            "claude",
            {
                "state": "half_open",
                "failure_count": 5,
                "half_open_probe_active": True,
            },
        )

        state = store.atomic_record_success("claude")

        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["half_open_probe_active"] is False

    def test_open_with_no_expected_state_is_noop(self):
        store = RedisStore(_fake_redis())
        expected = _open_state(failure_count=5, half_open_probe_active=False)
        store.set_state("claude", expected)

        state = store.atomic_record_success("claude")

        # state includes _prev_state / _prev_was_half_open metadata -- compare core fields only
        core_keys = set(expected.keys())
        assert {k: state[k] for k in core_keys} == expected
        assert state["_prev_state"] == "open"
        assert state["_prev_was_half_open"] is False
        assert store.get_state("claude") == expected

    def test_expected_state_mismatch_is_noop(self):
        store = RedisStore(_fake_redis())
        expected = {"state": "closed", "failure_count": 5}
        store.set_state("claude", expected)

        state = store.atomic_record_success("claude", expected_state="half_open")

        assert state["state"] == "closed"
        assert state["failure_count"] == 5


class TestMakeStore:
    def test_make_store_memory_returns_in_memory_store(self):
        assert isinstance(make_store("memory"), InMemoryStore)

    def test_make_store_redis_returns_redis_store(self):
        store = make_store("redis", redis_client=_fake_redis())

        assert isinstance(store, RedisStore)

    def test_make_store_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown circuit breaker store backend"):
            make_store("unknown")


class TestCBIntegration:
    def test_cb_with_store_starts_closed(self):
        cb = LLMCircuitBreaker(config=_enabled_config(), store=InMemoryStore())

        assert cb.state == CircuitState.CLOSED

    def test_cb_with_store_opens_after_max_failures(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=2),
            store=InMemoryStore(),
        )

        cb.record_failure()
        cb.record_failure()

        assert cb.state == CircuitState.OPEN

    def test_cb_with_store_reset_returns_to_closed(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            store=InMemoryStore(),
        )
        cb.record_failure()

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_cb_store_none_preserves_behavior(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=1), store=None)

        cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 1

    def test_cb_store_persisted_across_instances(self):
        store = InMemoryStore()
        first = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="claude",
            store=store,
        )
        second = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1),
            backend_name="claude",
            store=store,
        )

        first.record_failure()

        assert second.state == CircuitState.OPEN
        assert second.should_block() is True
