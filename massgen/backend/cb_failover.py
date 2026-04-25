"""Multi-region failover router for LLM circuit breakers (Phase 6).

When a backend's circuit breaker enters OPEN, FailoverRouter redirects
traffic to a secondary region. When the CB recovers (CLOSED), it restores
the primary after a configurable minimum failover duration.

Opt-in: enabled=False in FailoverConfig is the default, preserving full
back-compat. Wired into LLMCircuitBreaker via failover=None kwarg.

Zero external dependencies -- pure Python, builds on existing CB abstractions.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FailoverConfig:
    """Configuration for the multi-region failover router.

    All fields have safe defaults so existing CB configs need no changes.
    Set enabled=True and populate regions to activate failover.
    """

    enabled: bool = False
    # Map backend name to ordered list of region strings.
    # First element is the primary; subsequent elements are secondaries
    # tried in order. Example: {"gpt-5.4": ["us-east", "eu-west"]}
    regions: dict[str, list[str]] = field(default_factory=dict)
    # Seconds to wait for health probe before committing failover.
    # Must be > 0.
    health_check_timeout_seconds: float = 5.0
    # Minimum seconds to stay on secondary after a failover before
    # restoring primary on CB recovery. Prevents flapping. >= 0.
    min_failover_duration_seconds: float = 30.0
    # Reserved for future background recovery checks. Must be > 0.
    recovery_check_interval_seconds: float = 10.0

    def __post_init__(self) -> None:
        """Validate all configuration fields."""
        if self.health_check_timeout_seconds <= 0:
            raise ValueError(
                f"health_check_timeout_seconds must be > 0, " f"got {self.health_check_timeout_seconds}",
            )
        if self.min_failover_duration_seconds < 0:
            raise ValueError(
                f"min_failover_duration_seconds must be >= 0, " f"got {self.min_failover_duration_seconds}",
            )
        if self.recovery_check_interval_seconds <= 0:
            raise ValueError(
                f"recovery_check_interval_seconds must be > 0, " f"got {self.recovery_check_interval_seconds}",
            )
        for backend, region_list in self.regions.items():
            if not isinstance(backend, str) or not backend.strip():
                raise ValueError(
                    f"regions keys must be non-empty strings, got {backend!r}",
                )
            if not region_list:
                raise ValueError(
                    f"regions[{backend!r}] must be a non-empty list, got {region_list!r}",
                )
            for region in region_list:
                if not isinstance(region, str) or not region.strip():
                    raise ValueError(
                        f"regions[{backend!r}] contains invalid region: {region!r}",
                    )
            if len(region_list) != len(set(region_list)):
                duplicates = [r for r in region_list if region_list.count(r) > 1]
                raise ValueError(
                    f"regions[{backend!r}] contains duplicate region(s): {duplicates!r}",
                )


class FailoverRouter:
    """Routes backends to secondary regions when their circuit breaker opens.

    Thread-safe: all mutating methods acquire self._lock (threading.Lock).
    Pure Python, zero external dependencies.

    The router is event-driven: callers notify it via on_cb_state_change()
    when a CB transitions, passing a required monotonically-increasing seq
    so out-of-order notifies are dropped. No background threads are created.
    """

    def __init__(
        self,
        config: FailoverConfig,
        *,
        clock: Callable[[], float] | None = None,
        health_probe: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize the failover router.

        Args:
            config: Failover configuration including enabled flag and region map.
            clock: Monotonic clock for measuring failover duration. Defaults to
                time.monotonic. Injectable for tests.
            health_probe: Callable that accepts a region string and returns True
                if the region is healthy. When None, defaults to a function that
                always returns True. WARNING: the default is NOT production safe
                -- it will commit failover to the configured secondary on every
                CB OPEN even if the secondary is also down. Production callers
                must provide an explicit probe that actually checks the region.
                A one-shot WARNING is logged at construction when config.enabled
                is True and no explicit probe is supplied. Any exception raised
                by the probe is caught and treated as a probe failure -- no
                failover is committed. Each probe call runs under a
                health_check_timeout_seconds deadline; on timeout the probe is
                treated as a failure and the next region is tried.
        """
        self._config = config
        self._clock: Callable[[], float] = clock or time.monotonic
        if health_probe is None:
            self._health_probe: Callable[[str], bool] = lambda _region: True
            if config.enabled:
                logger.warning(
                    "FailoverRouter constructed with enabled=True and no explicit "
                    "health_probe; using default probe that returns True for all "
                    "regions. This is NOT production safe -- failover will commit "
                    "to the configured secondary even if it is also unhealthy. "
                    "Provide a real probe via the health_probe= kwarg.",
                )
        else:
            self._health_probe = health_probe
        self._lock = threading.Lock()
        # Per-backend failover state:
        #   _active_region[backend] = str (current active region)
        #   _failover_at[backend] = float | None (clock value when failover committed, None if not failed over)
        #   _failover_pending[backend] = bool (True while a probe is in-flight for this backend)
        #     Prevents concurrent threads from all probing and committing independently.
        #   _closed_during_probe[backend] = bool (True when CLOSED arrived while a probe was pending)
        #     Prevents stale OPEN probes from committing after the CB has already recovered.
        self._active_region: dict[str, str] = {}
        self._failover_at: dict[str, float | None] = {}
        self._failover_pending: dict[str, bool] = {}
        self._closed_during_probe: dict[str, bool] = {}
        # Last applied transition seq per backend, for out-of-order notify drop.
        # See on_cb_state_change docstring.
        self._last_seq: dict[str, int] = {}

    def _try_lazy_recovery_unlocked(self, backend: str, region_list: list[str]) -> None:
        """Restore primary if min_failover_duration has elapsed since failover.

        Caller must hold self._lock. Mutates _active_region and _failover_at
        when eligible. No-op when not failed over or duration not elapsed.
        Used by get_active_region, is_failed_over, and snapshot to keep router
        observation methods consistent.
        """
        failover_at = self._failover_at.get(backend)
        if failover_at is None:
            return
        elapsed = self._clock() - failover_at
        min_duration = self._config.min_failover_duration_seconds
        if elapsed < min_duration:
            return
        primary = region_list[0]
        self._active_region.pop(backend, None)
        self._failover_at[backend] = None
        logger.info(
            "Lazy recovery for %r: restored primary %r (elapsed=%.1fs >= min_duration=%.1fs).",
            backend,
            primary,
            elapsed,
            min_duration,
        )

    def get_active_region(self, backend: str) -> str | None:
        """Return the active region for a backend, or None if not configured.

        Returns None when config.enabled is False or the backend has no
        regions configured. Returns the primary (regions[backend][0]) when
        not failed over, or the secondary when failed over.

        Side effect: applies lazy recovery -- if the backend is currently
        failed over and min_failover_duration_seconds has elapsed since the
        failover, restores the primary inline (mutates router state). This
        keeps observation methods (get_active_region, is_failed_over,
        snapshot) consistent without requiring a background recovery thread.

        Args:
            backend: Logical backend name matching a key in config.regions.

        Returns:
            Active region string, or None.
        """
        if not self._config.enabled:
            return None
        region_list = self._config.regions.get(backend)
        if not region_list:
            return None
        with self._lock:
            self._try_lazy_recovery_unlocked(backend, region_list)
            return self._active_region.get(backend, region_list[0])

    def on_cb_state_change(
        self,
        backend: str,
        old_state: str,
        new_state: str,
        *,
        seq: int,
    ) -> None:
        """Evaluate failover or recovery when a circuit breaker changes state.

        When new_state=="open": attempt failover to the first secondary region
        that passes the health probe. If already failed over or the probe
        fails, the current routing is preserved.

        When new_state=="closed": restore primary if the minimum failover
        duration has elapsed. If the duration has not elapsed, recovery is
        deferred (logged but not applied).

        This method is a no-op when:
        - config.enabled is False
        - backend is not in config.regions
        - new_state is not "open" or "closed" (e.g. "half_open" or any
          unrecognized value -- ignored without consuming a seq slot)
        - An exception is raised by the health probe (treated as probe failure)
        - seq is not strictly greater than the last applied seq for this
          backend (the notify is stale and would otherwise overwrite a
          fresher CB state with an older view)

        Args:
            backend: Logical backend name.
            old_state: CB state before the transition (for logging).
            new_state: CB state after the transition.
            seq: Monotonically increasing transition sequence number from the
                CB. Required, kwarg-only. record_failure / record_success
                release self._lock before calling _notify_failover, so a stale
                notify can otherwise overwrite a fresher one and leave the
                router in a state inconsistent with the actual CB state. Pass
                a unique strictly-increasing integer from the producer; tests
                calling this method directly may use any monotonically
                increasing sequence (e.g. 1, 2, 3 ...).
        """
        if not self._config.enabled:
            return
        region_list = self._config.regions.get(backend)
        if not region_list:
            return
        # Drop notifies with new_state that this router doesn't act on
        # (e.g. "half_open"). Without this guard an unknown state would
        # consume a seq slot and silently drop subsequent legitimate
        # notifies whose seq is <= the consumed value.
        if new_state not in ("open", "closed"):
            logger.debug(
                "Ignoring failover notify for %r with unsupported new_state=%r.",
                backend,
                new_state,
            )
            return

        with self._lock:
            last = self._last_seq.get(backend, 0)
            if seq <= last:
                logger.debug(
                    "Dropping stale failover notify for %r: seq=%d <= last=%d.",
                    backend,
                    seq,
                    last,
                )
                return
            self._last_seq[backend] = seq

        if new_state == "open":
            self._handle_open(backend, old_state, region_list)
        else:  # new_state == "closed", guarded above
            self._handle_closed(backend, old_state, region_list)

    def _handle_open(
        self,
        backend: str,
        old_state: str,
        region_list: list[str],
    ) -> None:
        """Internal: evaluate failover when CB enters OPEN.

        Uses a _failover_pending flag to prevent concurrent threads from each
        launching independent probes and committing redundant failovers. The
        first thread to set the flag wins the probe; all subsequent callers
        see either the pending flag or the committed failover and return early.
        """
        # The whole probe (lock-claim + probe loop + commit) runs under one
        # try/finally so a BaseException (KeyboardInterrupt, SystemExit,
        # asyncio.CancelledError) arriving anywhere during probe slot claim
        # cannot leave _failover_pending stuck True. The pending_claimed
        # flag is set BEFORE _failover_pending so the finally cleanup is
        # always reachable when the actual flag is set.
        pending_claimed = False
        primary = region_list[0]
        committed = False
        timeout = self._config.health_check_timeout_seconds
        try:
            with self._lock:
                already_failed_over = self._failover_at.get(backend) is not None
                pending = self._failover_pending.get(backend, False)
                if already_failed_over or pending:
                    # Idempotent: already on secondary, or another thread is probing.
                    return
                if len(region_list) < 2:
                    # No secondary configured for this backend.
                    logger.warning(
                        "Failover triggered for %r but no secondary region configured (regions list has only one entry).",
                        backend,
                    )
                    return
                # Set the cleanup-reachability marker before mutating the
                # actual pending flag. If BaseException fires between these
                # two assignments, the finally still runs (pending_claimed
                # is True) and clears the (False) pending flag harmlessly.
                pending_claimed = True
                self._failover_pending[backend] = True
                self._closed_during_probe.pop(backend, None)

            for candidate in region_list[1:]:
                probe_result = False
                # Enforce health_check_timeout_seconds via a daemon thread +
                # join(timeout). A hanging probe must not block the calling
                # thread (and through it the LLMCircuitBreaker) indefinitely;
                # without this, _failover_pending would also stick True and
                # silently disable all subsequent OPEN events.
                #
                # Python cannot cancel a running thread, so a hanging probe
                # leaks until process exit. The thread is daemon so it does
                # not delay shutdown. Probe authors should use timeouts in
                # their HTTP clients to avoid the leak in practice.
                probe_outcome: list[bool | Exception] = [False]

                def _probe_runner(region: str = candidate, sink: list[bool | Exception] = probe_outcome) -> None:
                    """Run health probe in a daemon thread; record bool or Exception in sink.

                    KeyboardInterrupt and SystemExit are not caught -- consistent
                    with the policy in LLMCircuitBreaker._notify_failover. If a
                    probe somehow raises one in this worker thread, it surfaces
                    as a thread crash rather than being absorbed.
                    """
                    try:
                        sink[0] = bool(self._health_probe(region))
                    except Exception as exc:  # noqa: BLE001 -- never let probe break router
                        sink[0] = exc

                probe_thread = threading.Thread(target=_probe_runner, name=f"failover-probe-{candidate}", daemon=True)
                probe_thread.start()
                probe_thread.join(timeout=timeout)
                if probe_thread.is_alive():
                    logger.warning(
                        "Health probe for %r region %r timed out after %.1fs; treating as failure (thread abandoned).",
                        backend,
                        candidate,
                        timeout,
                    )
                    probe_result = False
                elif isinstance(probe_outcome[0], Exception):
                    logger.warning(
                        "Health probe for %r raised %s; skipping region %r.",
                        backend,
                        type(probe_outcome[0]).__name__,
                        candidate,
                    )
                    continue
                else:
                    probe_result = bool(probe_outcome[0])
                if probe_result:
                    with self._lock:
                        if not self._failover_pending.get(backend, False):
                            logger.info(
                                "Failover probe for %r succeeded but commit was aborted because pending failover state was cleared before commit.",
                                backend,
                            )
                            return
                        if self._closed_during_probe.get(backend, False):
                            logger.info(
                                "Failover probe for %r succeeded but commit was aborted because the circuit breaker closed during the probe.",
                                backend,
                            )
                            return
                        self._active_region[backend] = candidate
                        self._failover_at[backend] = self._clock()
                        # Atomically clear pending+latch so observers don't see
                        # a transient (failed_over=True, pending=True) state
                        # that could cause a subsequent OPEN event to be
                        # wrongly suppressed if recovery races with this commit.
                        self._failover_pending[backend] = False
                        self._closed_during_probe.pop(backend, None)
                    logger.info(
                        "Failover committed for %r: %r -> %r (CB transitioned %s -> open).",
                        backend,
                        primary,
                        candidate,
                        old_state,
                    )
                    committed = True
                    return
                else:
                    logger.warning(
                        "Health probe failed for %r region %r; trying next.",
                        backend,
                        candidate,
                    )

            if not committed:
                logger.warning(
                    "All secondary regions for %r failed health probe; staying on primary %r.",
                    backend,
                    primary,
                )
        finally:
            # Clean up only when:
            # - we actually claimed the probe slot (pending_claimed=True), AND
            # - the probe did not commit (commit clears pending atomically).
            # This prevents (a) wiping a subsequent concurrent probe's claim
            # after a successful commit, and (b) leaving _failover_pending stuck
            # True if a BaseException fires between slot claim and probe start.
            if pending_claimed and not committed:
                with self._lock:
                    self._failover_pending[backend] = False
                    self._closed_during_probe.pop(backend, None)

    def _handle_closed(
        self,
        backend: str,
        old_state: str,
        region_list: list[str],
    ) -> None:
        """Internal: evaluate recovery when CB returns to CLOSED."""
        with self._lock:
            failover_at = self._failover_at.get(backend)
            if failover_at is not None:
                now = self._clock()
                elapsed = now - failover_at
                min_duration = self._config.min_failover_duration_seconds
                if elapsed >= min_duration:
                    primary = region_list[0]
                    self._active_region.pop(backend, None)
                    self._failover_at[backend] = None
                    logger.info(
                        "Recovery complete for %r: restored primary %r " "(elapsed=%.1fs >= min_duration=%.1fs, CB transitioned %s -> closed).",
                        backend,
                        primary,
                        elapsed,
                        min_duration,
                        old_state,
                    )
                else:
                    remaining = min_duration - elapsed
                    active = self._active_region.get(backend, region_list[0])
                    logger.info(
                        "Recovery deferred for %r: staying on %r for %.1f more seconds " "(elapsed=%.1fs < min_duration=%.1fs).",
                        backend,
                        active,
                        remaining,
                        elapsed,
                        min_duration,
                    )
                return
            if self._failover_pending.get(backend, False):
                self._closed_during_probe[backend] = True
                logger.debug(
                    "CLOSED notification for %r arrived during an in-flight failover probe; " "marking probe for abort.",
                    backend,
                )

    def is_failed_over(self, backend: str) -> bool:
        """Return True iff the backend is currently routing to a secondary region.

        Side effect: applies lazy recovery (see get_active_region) so that
        is_failed_over and get_active_region report consistent state.

        Args:
            backend: Logical backend name.

        Returns:
            True if currently failed over, False otherwise (including when
            config.enabled is False or backend has no regions configured).
        """
        if not self._config.enabled:
            return False
        region_list = self._config.regions.get(backend)
        if not region_list:
            return False
        with self._lock:
            self._try_lazy_recovery_unlocked(backend, region_list)
            return self._failover_at.get(backend) is not None

    def snapshot(self) -> dict[str, Any]:
        """Return an observable point-in-time snapshot of all backends.

        All live fields are captured under a single lock acquisition.
        Side effect: applies lazy recovery for each configured backend so
        snapshot agrees with get_active_region/is_failed_over.

        Returns:
            Dict with key "backends" mapping each configured backend name to
            a dict containing:
            - "active_region": current active region string (primary or secondary)
            - "failed_over": bool
            - "failover_at": float | None (monotonic timestamp, None if not failed over)
        """
        with self._lock:
            result: dict[str, Any] = {}
            for backend, region_list in self._config.regions.items():
                self._try_lazy_recovery_unlocked(backend, region_list)
                primary = region_list[0]
                active = self._active_region.get(backend, primary)
                failover_at = self._failover_at.get(backend)
                result[backend] = {
                    "active_region": active,
                    "failed_over": failover_at is not None,
                    "failover_at": failover_at,
                }
        return {"backends": result}

    def reset(self, backend: str) -> None:
        """Administratively restore the primary region for a backend.

        Clears all per-backend tracking state -- active region, failover
        timestamp, in-flight probe pending flag, closed-during-probe latch,
        and last-applied seq -- regardless of min_failover_duration_seconds
        and regardless of whether a failover is currently in progress.
        Clearing _last_seq lets a fresh producer (e.g. a hot-swapped CB
        instance whose _transition_seq starts at 0) resume notifying without
        having its early notifies dropped as stale. No-op when backend is
        not in config.regions.

        Args:
            backend: Logical backend name.
        """
        if backend not in self._config.regions:
            return
        # Guard above + FailoverConfig validation guarantee a non-empty list.
        region_list = self._config.regions[backend]
        with self._lock:
            self._active_region.pop(backend, None)
            self._failover_at[backend] = None
            self._failover_pending[backend] = False
            self._closed_during_probe.pop(backend, None)
            # Clear seq history so a new producer (or hot-swapped CB instance
            # whose _transition_seq starts at 0) can resume notifying without
            # its early notifies being dropped as stale by lingering last_seq.
            self._last_seq.pop(backend, None)
        logger.info("Administrative reset for %r: restored primary %r.", backend, region_list[0])
