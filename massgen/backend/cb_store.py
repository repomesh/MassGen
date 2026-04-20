"""State stores for LLM circuit breakers."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

DEFAULT_CIRCUIT_BREAKER_STATE: dict[str, Any] = {
    "state": "closed",
    "failure_count": 0,
    "last_failure_time": 0.0,
    "open_until": 0.0,
    "half_open_probe_active": False,
}


def _default_state() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CIRCUIT_BREAKER_STATE)


@runtime_checkable
class CircuitBreakerStore(Protocol):
    """Protocol for shared circuit breaker state stores.

    Implementations must persist state using Unix wall-clock timestamps
    (``time.time()``) for ``open_until`` and ``last_failure_time`` so that
    values remain meaningful across processes. Returned dicts also include
    the auxiliary keys ``_prev_state`` (str) and ``_prev_was_half_open``
    (bool) for the atomic_record_* methods, so callers can emit transition
    logs/metrics without a separate get_state() call.
    """

    def get_state(self, backend: str) -> dict:
        """Return a snapshot of the backend's circuit breaker state.

        Args:
            backend: Logical backend name used as the store key.

        Returns:
            Dict with keys: ``state`` (str), ``failure_count`` (int),
            ``last_failure_time`` (float, Unix time), ``open_until``
            (float, Unix time), ``half_open_probe_active`` (bool).
        """

    def set_state(self, backend: str, state: dict) -> None:
        """Persist the complete circuit breaker state for a backend."""

    def cas_state(self, backend: str, expected_state: str, updates: dict) -> bool:
        """Apply updates if the current state field matches expected_state.

        Returns:
            True if the update was applied, False otherwise.
        """

    def increment_failure(self, backend: str) -> int:
        """Atomically increment and return the backend failure count."""

    def atomic_record_failure(
        self,
        backend: str,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> dict:
        """Atomically record a failed call and return the new full state.

        The operation increments failure_count, records the current failure
        time, and applies the CLOSED/HALF_OPEN -> OPEN transition rules in one
        store-level critical section. The returned dict includes ``_prev_state``
        and ``_prev_was_half_open`` describing the state before this call.
        """

    def atomic_record_success(
        self,
        backend: str,
        expected_state: str | None = None,
    ) -> dict:
        """Atomically record a successful call and return the new full state.

        When expected_state is provided, the update is constrained to that
        current state. Without an expected state, OPEN is treated as a forced
        open guard and is returned unchanged. The returned dict includes
        ``_prev_state`` and ``_prev_was_half_open``.
        """

    def try_transition_and_claim_probe(
        self,
        backend: str,
        now: float,
        recovery_timeout: float,
    ) -> tuple[bool, dict, str | None]:
        """Atomically transition OPEN->HALF_OPEN or claim HALF_OPEN probe.

        All checks and writes occur in one store-level critical section:

        - If state==OPEN and now >= open_until: set state=HALF_OPEN,
          half_open_probe_active=True. Returns ``(True, new_state,
          "open->half_open")``.
        - Elif state==HALF_OPEN and not half_open_probe_active: set
          half_open_probe_active=True. Returns ``(True, new_state,
          "half_open_probe_claimed")``.
        - Else: returns ``(False, current_state, None)``.

        Args:
            backend: Logical backend name.
            now: Unix timestamp (``time.time()``) used for the open_until
                comparison. The caller owns the clock to match the values
                the store persists via ``atomic_record_failure`` and
                ``force_open``.
            recovery_timeout: Reserved for future TTL computation.

        Returns:
            ``(won, new_state, transition_label)`` -- ``won`` is True iff
            this caller successfully transitioned or claimed the probe.
        """

    def clear(self, backend: str) -> None:
        """Remove persisted state for a backend."""


class InMemoryStore:
    """Thread-safe in-process circuit breaker store.

    Uses an RLock for mutual exclusion. All timestamps are ``time.time()``
    (Unix wall-clock) to stay consistent with RedisStore semantics. This
    store is intended for single-process deployments and as the default
    test fixture; use RedisStore for multi-process coordination.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._storage: dict[str, dict] = {}

    def get_state(self, backend: str) -> dict:
        with self._lock:
            if backend not in self._storage:
                self._storage[backend] = _default_state()
            return copy.deepcopy(self._storage[backend])

    def set_state(self, backend: str, state: dict) -> None:
        with self._lock:
            complete_state = _default_state()
            complete_state.update(copy.deepcopy(state))
            self._storage[backend] = complete_state

    def cas_state(self, backend: str, expected_state: str, updates: dict) -> bool:
        with self._lock:
            if backend not in self._storage:
                self._storage[backend] = _default_state()
            if self._storage[backend].get("state") != expected_state:
                return False
            self._storage[backend].update(copy.deepcopy(updates))
            return True

    def increment_failure(self, backend: str) -> int:
        with self._lock:
            state = self.get_state(backend)
            state["failure_count"] = int(state["failure_count"]) + 1
            self.set_state(backend, state)
            return int(state["failure_count"])

    def atomic_record_failure(
        self,
        backend: str,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> dict:
        with self._lock:
            if backend not in self._storage:
                self._storage[backend] = _default_state()

            state = copy.deepcopy(self._storage[backend])
            prev_state_str = str(state["state"])
            now = time.time()
            failure_count = int(state["failure_count"]) + 1
            state["failure_count"] = failure_count
            state["last_failure_time"] = now

            if state["state"] == "half_open":
                state["state"] = "open"
                state["open_until"] = now + recovery_timeout
                state["half_open_probe_active"] = False
            elif state["state"] == "closed" and failure_count >= failure_threshold:
                state["state"] = "open"
                state["open_until"] = now + recovery_timeout
                state["half_open_probe_active"] = False
            elif state["state"] == "open":
                current_open_until = float(state.get("open_until", 0))
                state["open_until"] = max(current_open_until, now + recovery_timeout)

            self._storage[backend] = state
            result = copy.deepcopy(state)
            result["_prev_state"] = prev_state_str
            result["_prev_was_half_open"] = prev_state_str == "half_open"
            return result

    def atomic_record_success(
        self,
        backend: str,
        expected_state: str | None = None,
    ) -> dict:
        with self._lock:
            if backend not in self._storage:
                self._storage[backend] = _default_state()

            state = copy.deepcopy(self._storage[backend])
            prev_state_str = str(state["state"])

            if expected_state is not None and prev_state_str != expected_state:
                result = copy.deepcopy(state)
                result["_prev_state"] = prev_state_str
                result["_prev_was_half_open"] = prev_state_str == "half_open"
                return result

            if expected_state is None and prev_state_str == "open":
                result = copy.deepcopy(state)
                result["_prev_state"] = prev_state_str
                result["_prev_was_half_open"] = False
                return result

            if prev_state_str == "closed":
                state["failure_count"] = 0
                state["half_open_probe_active"] = False
                self._storage[backend] = state
            elif prev_state_str == "half_open":
                state["state"] = "closed"
                state["failure_count"] = 0
                state["half_open_probe_active"] = False
                self._storage[backend] = state

            result = copy.deepcopy(state)
            result["_prev_state"] = prev_state_str
            result["_prev_was_half_open"] = prev_state_str == "half_open"
            return result

    def try_transition_and_claim_probe(
        self,
        backend: str,
        now: float,
        recovery_timeout: float,
    ) -> tuple[bool, dict, str | None]:
        """Atomically transition OPEN->HALF_OPEN or claim HALF_OPEN probe.

        See ``CircuitBreakerStore.try_transition_and_claim_probe`` for the
        protocol contract. ``recovery_timeout`` is accepted for API
        compatibility but not used in-memory.
        """
        del recovery_timeout  # reserved for future use
        with self._lock:
            if backend not in self._storage:
                self._storage[backend] = _default_state()
            state = self._storage[backend]
            current = state["state"]

            if current == "open" and now >= float(state["open_until"]):
                state["state"] = "half_open"
                state["half_open_probe_active"] = True
                return True, copy.deepcopy(state), "open->half_open"

            if current == "half_open" and not state["half_open_probe_active"]:
                state["half_open_probe_active"] = True
                return True, copy.deepcopy(state), "half_open_probe_claimed"

            return False, copy.deepcopy(state), None

    def clear(self, backend: str) -> None:
        with self._lock:
            self._storage.pop(backend, None)


class RedisStore:
    """Redis hash-backed circuit breaker store.

    Provides cross-process atomicity via Lua scripts with WATCH/MULTI/EXEC
    fallback when Lua scripting is unavailable. All persisted timestamps
    (``open_until``, ``last_failure_time``) are Unix wall-clock seconds so
    that they remain comparable across processes and machines.

    Args:
        redis_client: A ``redis.Redis``-compatible client.
        ttl: Default TTL in seconds applied to the per-backend hash key.
        key_prefix: Namespace prefix -- allows multiple logical breakers
            (e.g. test vs prod) to share one Redis instance without key
            collisions.
    """

    _CAS_SCRIPT = """
local current_state = redis.call("HGET", KEYS[1], "state")
if current_state == false then
    current_state = "closed"
end
if current_state ~= ARGV[1] then
    return 0
end
for i = 4, #ARGV, 2 do
redis.call("HSET", KEYS[1], ARGV[i], ARGV[i + 1])
end
local base_ttl = tonumber(ARGV[2])
local half_open_probe_ttl = tonumber(ARGV[3])
local final_state = redis.call("HGET", KEYS[1], "state")
if final_state == false then final_state = "closed" end
local effective_ttl = base_ttl
if final_state == "open" then
    local open_until = tonumber(redis.call("HGET", KEYS[1], "open_until") or "0")
    local t = redis.call("TIME")
    local now = tonumber(t[1])
    local remaining = open_until - now
    if remaining + 60 > effective_ttl then effective_ttl = math.ceil(remaining + 60) end
elseif final_state == "half_open" then
    local probe_active = redis.call("HGET", KEYS[1], "half_open_probe_active")
    if probe_active == "True" then
        if half_open_probe_ttl > effective_ttl then effective_ttl = half_open_probe_ttl end
    end
end
if effective_ttl < 1 then effective_ttl = 1 end
redis.call("EXPIRE", KEYS[1], effective_ttl)
return 1
"""

    _INCREMENT_SCRIPT = """
local count = redis.call("HINCRBY", KEYS[1], "failure_count", 1)
if redis.call("HGET", KEYS[1], "state") == false then
    redis.call(
        "HSET",
        KEYS[1],
        "state",
        "closed",
        "last_failure_time",
        "0.0",
        "open_until",
        "0.0",
        "half_open_probe_active",
        "False"
    )
end
local existing_ttl = redis.call("TTL", KEYS[1])
local new_ttl = tonumber(ARGV[1])
if existing_ttl == -2 then existing_ttl = 0 end
if existing_ttl > new_ttl then new_ttl = existing_ttl end
redis.call("EXPIRE", KEYS[1], new_ttl)
return count
"""

    _RECORD_FAILURE_SCRIPT = """
local raw = redis.call("HGETALL", KEYS[1])
local state = {
    state = "closed",
    failure_count = "0",
    last_failure_time = "0.0",
    open_until = "0.0",
    half_open_probe_active = "False"
}
for i = 1, #raw, 2 do
    state[raw[i]] = raw[i + 1]
end

local failure_threshold = tonumber(ARGV[1])
local recovery_timeout = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
if now == nil then
    local redis_time = redis.call("TIME")
    now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)
end

local prev_state = state["state"]
local failure_count = tonumber(state["failure_count"]) or 0
failure_count = failure_count + 1
state["failure_count"] = tostring(failure_count)
state["last_failure_time"] = tostring(now)

if state["state"] == "half_open" then
    state["state"] = "open"
    state["open_until"] = tostring(now + recovery_timeout)
    state["half_open_probe_active"] = "False"
elseif state["state"] == "closed" and failure_count >= failure_threshold then
    state["state"] = "open"
    state["open_until"] = tostring(now + recovery_timeout)
    state["half_open_probe_active"] = "False"
elseif state["state"] == "open" then
    local current_open_until = tonumber(state["open_until"]) or 0
    state["open_until"] = tostring(math.max(current_open_until, now + recovery_timeout))
end

redis.call(
    "HSET",
    KEYS[1],
    "state",
    state["state"],
    "failure_count",
    state["failure_count"],
    "last_failure_time",
    state["last_failure_time"],
    "open_until",
    state["open_until"],
    "half_open_probe_active",
    state["half_open_probe_active"]
)
local effective_ttl = ttl
if state["state"] == "open" then
    local remaining = tonumber(state["open_until"]) - now
    if remaining ~= nil and remaining > 0 then
        local open_ttl = math.floor(remaining) + 60
        if open_ttl > effective_ttl then
            effective_ttl = open_ttl
        end
    end
end
redis.call("EXPIRE", KEYS[1], effective_ttl)
local prev_was_half_open = "False"
if prev_state == "half_open" then prev_was_half_open = "True" end
return {
    "state",
    state["state"],
    "failure_count",
    state["failure_count"],
    "last_failure_time",
    state["last_failure_time"],
    "open_until",
    state["open_until"],
    "half_open_probe_active",
    state["half_open_probe_active"],
    "_prev_state",
    prev_state,
    "_prev_was_half_open",
    prev_was_half_open
}
"""

    _RECORD_SUCCESS_SCRIPT = """
local raw = redis.call("HGETALL", KEYS[1])
local state = {
    state = "closed",
    failure_count = "0",
    last_failure_time = "0.0",
    open_until = "0.0",
    half_open_probe_active = "False"
}
for i = 1, #raw, 2 do
    state[raw[i]] = raw[i + 1]
end

local expected_state = ARGV[1]
local ttl = tonumber(ARGV[2])
local should_write = 0
local prev_state = state["state"]

if expected_state ~= "" and state["state"] ~= expected_state then
    local prev_was_half_open = "False"
    if prev_state == "half_open" then prev_was_half_open = "True" end
    return {
        "state",
        state["state"],
        "failure_count",
        state["failure_count"],
        "last_failure_time",
        state["last_failure_time"],
        "open_until",
        state["open_until"],
        "half_open_probe_active",
        state["half_open_probe_active"],
        "_prev_state",
        prev_state,
        "_prev_was_half_open",
        prev_was_half_open
    }
end

if state["state"] == "open" and expected_state == "" then
    return {
        "state",
        state["state"],
        "failure_count",
        state["failure_count"],
        "last_failure_time",
        state["last_failure_time"],
        "open_until",
        state["open_until"],
        "half_open_probe_active",
        state["half_open_probe_active"],
        "_prev_state",
        prev_state,
        "_prev_was_half_open",
        "False"
    }
end

if state["state"] == "closed" or state["state"] == "half_open" then
    state["state"] = "closed"
    state["failure_count"] = "0"
    state["half_open_probe_active"] = "False"
    should_write = 1
end

if should_write == 1 then
    redis.call(
        "HSET",
        KEYS[1],
        "state",
        state["state"],
        "failure_count",
        state["failure_count"],
        "last_failure_time",
        state["last_failure_time"],
        "open_until",
        state["open_until"],
        "half_open_probe_active",
        state["half_open_probe_active"]
    )
    redis.call("EXPIRE", KEYS[1], ttl)
end

local prev_was_half_open = "False"
if prev_state == "half_open" then prev_was_half_open = "True" end
return {
    "state",
    state["state"],
    "failure_count",
    state["failure_count"],
    "last_failure_time",
    state["last_failure_time"],
    "open_until",
    state["open_until"],
    "half_open_probe_active",
    state["half_open_probe_active"],
    "_prev_state",
    prev_state,
    "_prev_was_half_open",
    prev_was_half_open
}
"""

    _TRANSITION_PROBE_SCRIPT = """
local raw = redis.call("HGETALL", KEYS[1])
local state = {
    state = "closed",
    failure_count = "0",
    last_failure_time = "0.0",
    open_until = "0.0",
    half_open_probe_active = "False"
}
for i = 1, #raw, 2 do
    state[raw[i]] = raw[i + 1]
end

local now = tonumber(ARGV[1])
if now == nil then
    local redis_time = redis.call("TIME")
    now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)
end
local ttl = tonumber(ARGV[2])
local probe_ttl = tonumber(ARGV[3])
local transition = ""

if state["state"] == "open" and now >= tonumber(state["open_until"]) then
    state["state"] = "half_open"
    state["half_open_probe_active"] = "True"
    transition = "open->half_open"
elseif state["state"] == "half_open" and state["half_open_probe_active"] == "False" then
    state["half_open_probe_active"] = "True"
    transition = "half_open_probe_claimed"
end

if transition ~= "" then
    redis.call(
        "HSET", KEYS[1],
        "state", state["state"],
        "failure_count", state["failure_count"],
        "last_failure_time", state["last_failure_time"],
        "open_until", state["open_until"],
        "half_open_probe_active", state["half_open_probe_active"]
    )
    local effective_ttl = ttl
    if state["half_open_probe_active"] == "True" then
        effective_ttl = probe_ttl
    end
    redis.call("EXPIRE", KEYS[1], effective_ttl)
end

return {
    transition,
    "state", state["state"],
    "failure_count", state["failure_count"],
    "last_failure_time", state["last_failure_time"],
    "open_until", state["open_until"],
    "half_open_probe_active", state["half_open_probe_active"]
}
"""

    def __init__(
        self,
        redis_client: Any,
        ttl: int = 3600,
        key_prefix: str = "massgen:cb",
        half_open_probe_ttl: int | None = None,
    ) -> None:
        if redis_client is None:
            raise ValueError("redis_client is required for RedisStore")
        self._client = redis_client
        self._ttl = ttl
        self._key_prefix = key_prefix
        # Probe TTL must be at least as long as the base TTL so the
        # half_open state survives a long probe request even when callers
        # configure a small base TTL.
        self._half_open_probe_ttl = max(ttl, half_open_probe_ttl) if half_open_probe_ttl is not None else ttl
        self._fallback_lock = threading.Lock()

    def get_state(self, backend: str) -> dict:
        raw_state = self._client.hgetall(self._key(backend))
        return self._state_from_items(raw_state.items())

    def set_state(self, backend: str, state: dict) -> None:
        key = self._key(backend)
        complete_state = _default_state()
        complete_state.update(copy.deepcopy(state))
        mapping = {field: self._to_redis_value(complete_state[field]) for field in DEFAULT_CIRCUIT_BREAKER_STATE}
        self._client.hset(key, mapping=mapping)
        self._client.expire(key, self._compute_ttl(complete_state))

    def cas_state(self, backend: str, expected_state: str, updates: dict) -> bool:
        args: list[Any] = [
            expected_state,
            str(self._ttl),
            str(self._half_open_probe_ttl),
        ]
        for field, value in updates.items():
            args.extend([field, self._to_redis_value(value)])
        try:
            result = self._client.eval(self._CAS_SCRIPT, 1, self._key(backend), *args)
        except Exception as exc:
            if not self._script_unavailable(exc):
                raise
            return self._cas_state_without_lua(backend, expected_state, updates)
        return int(result) == 1

    def increment_failure(self, backend: str) -> int:
        try:
            result = self._client.eval(
                self._INCREMENT_SCRIPT,
                1,
                self._key(backend),
                str(self._ttl),
            )
        except Exception as exc:
            if not self._script_unavailable(exc):
                raise
            return self._increment_failure_without_lua(backend)
        return int(result)

    def atomic_record_failure(
        self,
        backend: str,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> dict:
        try:
            result = self._client.eval(
                self._RECORD_FAILURE_SCRIPT,
                1,
                self._key(backend),
                str(int(failure_threshold)),
                str(float(recovery_timeout)),
                str(self._ttl),
                str(time.time()),
            )
        except Exception as exc:
            if not self._script_unavailable(exc):
                raise
            return self._atomic_record_failure_without_lua(
                backend,
                failure_threshold,
                recovery_timeout,
            )
        return self._state_from_flat_pairs(result)

    def atomic_record_success(
        self,
        backend: str,
        expected_state: str | None = None,
    ) -> dict:
        try:
            result = self._client.eval(
                self._RECORD_SUCCESS_SCRIPT,
                1,
                self._key(backend),
                expected_state or "",
                str(self._ttl),
            )
        except Exception as exc:
            if not self._script_unavailable(exc):
                raise
            return self._atomic_record_success_without_lua(backend, expected_state)
        return self._state_from_flat_pairs(result)

    def try_transition_and_claim_probe(
        self,
        backend: str,
        now: float,
        recovery_timeout: float,
    ) -> tuple[bool, dict, str | None]:
        """Atomically transition OPEN->HALF_OPEN or claim HALF_OPEN probe.

        See ``CircuitBreakerStore.try_transition_and_claim_probe`` for the
        contract. ``recovery_timeout`` is accepted for API parity and
        reserved for future TTL policy decisions.
        """
        del recovery_timeout  # reserved
        try:
            result = self._client.eval(
                self._TRANSITION_PROBE_SCRIPT,
                1,
                self._key(backend),
                str(now),
                str(max(1, self._ttl)),
                str(max(1, self._half_open_probe_ttl)),
            )
        except Exception as exc:
            if not self._script_unavailable(exc):
                raise
            return self._try_transition_and_claim_probe_without_lua(backend, now)
        pairs = list(result)
        if not pairs:
            return False, self.get_state(backend), None
        transition_label = self._decode(pairs[0])
        state = self._state_from_flat_pairs(pairs[1:])
        if transition_label:
            return True, state, transition_label
        return False, state, None

    def _try_transition_and_claim_probe_without_lua(
        self,
        backend: str,
        now: float,
    ) -> tuple[bool, dict, str | None]:
        key = self._key(backend)
        with self._fallback_lock:
            for attempt in range(3):
                pipe = self._client.pipeline(True)
                try:
                    pipe.watch(key)
                    raw_state = pipe.hgetall(key)
                    state = self._state_from_items(raw_state.items())
                    current = state["state"]
                    transition: str | None = None

                    if current == "open" and now >= float(state["open_until"]):
                        state["state"] = "half_open"
                        state["half_open_probe_active"] = True
                        transition = "open->half_open"
                    elif current == "half_open" and not state["half_open_probe_active"]:
                        state["half_open_probe_active"] = True
                        transition = "half_open_probe_claimed"
                    else:
                        pipe.reset()
                        return False, state, None

                    pipe.multi()
                    pipe.hset(key, mapping=self._state_to_mapping(state))
                    pipe.expire(key, self._compute_ttl(state))
                    pipe.execute()
                    return True, state, transition
                except Exception as exc:
                    if self._watch_retryable(exc):
                        time.sleep(0.001 * (2**attempt))
                        continue
                    raise
                finally:
                    pipe.reset()
        return False, self.get_state(backend), None

    def clear(self, backend: str) -> None:
        self._client.delete(self._key(backend))

    def _key(self, backend: str) -> str:
        return f"{self._key_prefix}:{backend}"

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @staticmethod
    def _to_redis_value(value: Any) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        return str(value)

    def _state_from_items(self, items: Iterable[tuple[Any, Any]]) -> dict:
        state = _default_state()
        for raw_key, raw_value in items:
            key = self._decode(raw_key)
            value = self._decode(raw_value)
            if key == "failure_count":
                state[key] = int(value)
            elif key in {"last_failure_time", "open_until"}:
                state[key] = float(value)
            elif key in {"half_open_probe_active", "_prev_was_half_open"}:
                state[key] = value == "True"
            elif key in {"state", "_prev_state"}:
                state[key] = value
        return state

    def _state_from_flat_pairs(self, raw_pairs: Any) -> dict:
        pairs = list(raw_pairs)
        if len(pairs) % 2 != 0:
            raise ValueError("Redis circuit breaker script returned uneven field pairs")
        return self._state_from_items(zip(pairs[0::2], pairs[1::2], strict=True))

    def _state_to_mapping(self, state: dict) -> dict:
        return {field: self._to_redis_value(state[field]) for field in DEFAULT_CIRCUIT_BREAKER_STATE}

    @staticmethod
    def _script_unavailable(exc: Exception) -> bool:
        # Match only known Lua/EVAL unavailability signatures.
        # Require "unknown command" context to avoid classifying READONLY,
        # ACL-denied, proxy, or other operational errors as Lua unavailability.
        message = str(exc).lower()
        unknown_command = "unknown command" in message or "unknown redis command" in message or "err unknown command" in message
        mentions_script_command = "eval" in message or "evalsha" in message
        return "lupa" in message or (unknown_command and mentions_script_command)

    def _compute_ttl(self, updates: dict) -> int:
        if updates.get("state") == "open":
            open_until = float(updates.get("open_until", 0))
            remaining = int(open_until - time.time())
            return max(1, self._ttl, remaining + 60)
        if updates.get("state") == "half_open" and updates.get(
            "half_open_probe_active",
        ):
            return max(1, self._half_open_probe_ttl)
        return max(1, self._ttl)

    @staticmethod
    def _watch_retryable(exc: Exception) -> bool:
        err_msg = str(exc).lower()
        class_name = exc.__class__.__name__.lower()
        return "watch" in err_msg or "execabort" in err_msg or "multi" in err_msg or "wrongtype" in err_msg or class_name == "watcherror"

    def _cas_state_without_lua(
        self,
        backend: str,
        expected_state: str,
        updates: dict,
    ) -> bool:
        key = self._key(backend)
        for attempt in range(3):
            pipe = self._client.pipeline(True)
            try:
                pipe.watch(key)
                current = self._client.hget(key, "state")
                if current is not None:
                    current = self._decode(current)
                else:
                    current = "closed"
                if current != expected_state:
                    pipe.reset()
                    return False
                existing = self._state_from_items(self._client.hgetall(key).items())
                existing.update(updates)
                pipe.multi()
                for field, value in updates.items():
                    pipe.hset(key, field, self._to_redis_value(value))
                effective_ttl = self._compute_ttl(existing)
                pipe.expire(key, effective_ttl)
                pipe.execute()
                return True
            except Exception as exc:
                err_msg = str(exc).lower()
                if "watch" in err_msg or "multi" in err_msg or "wrongtype" in err_msg or "execabort" in err_msg:
                    time.sleep(0.001 * (2**attempt))
                    continue
                raise
            finally:
                pipe.reset()
        return False

    def _increment_failure_without_lua(self, backend: str) -> int:
        key = self._key(backend)
        for attempt in range(3):
            pipe = self._client.pipeline(True)
            try:
                pipe.watch(key)
                state = self.get_state(backend)
                state["failure_count"] = int(state["failure_count"]) + 1
                pipe.multi()
                mapping = {field: self._to_redis_value(state[field]) for field in DEFAULT_CIRCUIT_BREAKER_STATE}
                pipe.hset(key, mapping=mapping)
                pipe.expire(key, self._compute_ttl(state))
                pipe.execute()
                return int(state["failure_count"])
            except Exception as exc:
                err_msg = str(exc).lower()
                if "watch" in err_msg or "execabort" in err_msg:
                    time.sleep(0.001 * (2**attempt))
                    continue
                raise
            finally:
                pipe.reset()
        raise RuntimeError(
            f"Failed to atomically increment failure count for {backend!r} " "after 3 retries",
        )

    def _atomic_record_failure_without_lua(
        self,
        backend: str,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> dict:
        key = self._key(backend)
        with self._fallback_lock:
            for attempt in range(3):
                pipe = self._client.pipeline(True)
                try:
                    pipe.watch(key)
                    raw_state = pipe.hgetall(key)
                    state = self._state_from_items(raw_state.items())
                    prev_state_str = str(state["state"])
                    now = time.time()
                    failure_count = int(state["failure_count"]) + 1
                    state["failure_count"] = failure_count
                    state["last_failure_time"] = now

                    if state["state"] == "half_open":
                        state["state"] = "open"
                        state["open_until"] = now + recovery_timeout
                        state["half_open_probe_active"] = False
                    elif state["state"] == "closed" and failure_count >= failure_threshold:
                        state["state"] = "open"
                        state["open_until"] = now + recovery_timeout
                        state["half_open_probe_active"] = False
                    elif state["state"] == "open":
                        current_open_until = float(state.get("open_until", 0))
                        state["open_until"] = max(
                            current_open_until,
                            now + recovery_timeout,
                        )

                    pipe.multi()
                    pipe.hset(key, mapping=self._state_to_mapping(state))
                    pipe.expire(key, self._compute_ttl(state))
                    pipe.execute()
                    state["_prev_state"] = prev_state_str
                    state["_prev_was_half_open"] = prev_state_str == "half_open"
                    return state
                except Exception as exc:
                    if self._watch_retryable(exc):
                        time.sleep(0.001 * (2**attempt))
                        continue
                    raise
                finally:
                    pipe.reset()
        raise RuntimeError(
            f"Failed to atomically record failure for {backend!r} after 3 retries",
        )

    def _atomic_record_success_without_lua(
        self,
        backend: str,
        expected_state: str | None = None,
    ) -> dict:
        key = self._key(backend)
        with self._fallback_lock:
            for attempt in range(3):
                pipe = self._client.pipeline(True)
                try:
                    pipe.watch(key)
                    raw_state = pipe.hgetall(key)
                    state = self._state_from_items(raw_state.items())
                    prev_state_str = str(state["state"])

                    if expected_state is not None and prev_state_str != expected_state:
                        state["_prev_state"] = prev_state_str
                        state["_prev_was_half_open"] = prev_state_str == "half_open"
                        return state

                    if expected_state is None and prev_state_str == "open":
                        state["_prev_state"] = prev_state_str
                        state["_prev_was_half_open"] = False
                        return state

                    if prev_state_str in {"closed", "half_open"}:
                        state["state"] = "closed"
                        state["failure_count"] = 0
                        state["half_open_probe_active"] = False
                        pipe.multi()
                        pipe.hset(key, mapping=self._state_to_mapping(state))
                        pipe.expire(key, self._compute_ttl(state))
                        pipe.execute()

                    state["_prev_state"] = prev_state_str
                    state["_prev_was_half_open"] = prev_state_str == "half_open"
                    return state
                except Exception as exc:
                    if self._watch_retryable(exc):
                        time.sleep(0.001 * (2**attempt))
                        continue
                    raise
                finally:
                    pipe.reset()
        raise RuntimeError(
            f"Failed to atomically record success for {backend!r} after 3 retries",
        )


def make_store(backend: str = "memory", **kwargs: Any) -> CircuitBreakerStore:
    """Create a circuit breaker state store.

    Args:
        backend: ``"memory"`` for the in-process store or ``"redis"`` for the
            Redis-backed store.
        **kwargs: For ``"redis"``, ``redis_client`` is required; ``ttl``
            (default 3600), ``key_prefix`` (default ``"massgen:cb"``), and
            ``half_open_probe_ttl`` (default equals ``ttl``) are forwarded
            to ``RedisStore``. Use ``half_open_probe_ttl`` to keep the
            half_open probe entry alive longer than the base TTL.

    Raises:
        ValueError: If ``backend`` is unknown, or if ``backend=="redis"`` but
            ``redis_client`` is missing.
    """
    if backend == "memory":
        return InMemoryStore()
    if backend == "redis":
        redis_client = kwargs.get("redis_client")
        if redis_client is None:
            raise ValueError(
                "redis_client is required for backend='redis'",
            )
        redis_kwargs: dict[str, Any] = {"ttl": kwargs.get("ttl", 3600)}
        if "key_prefix" in kwargs:
            redis_kwargs["key_prefix"] = kwargs["key_prefix"]
        if "half_open_probe_ttl" in kwargs:
            redis_kwargs["half_open_probe_ttl"] = kwargs["half_open_probe_ttl"]
        return RedisStore(redis_client, **redis_kwargs)
    raise ValueError(f"Unknown circuit breaker store backend: {backend}")
