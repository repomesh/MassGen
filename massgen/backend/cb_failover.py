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
                f"health_check_timeout_seconds must be > 0, "
                f"got {self.health_check_timeout_seconds}",
            )
        if self.min_failover_duration_seconds < 0:
            raise ValueError(
                f"min_failover_duration_seconds must be >= 0, "
                f"got {self.min_failover_duration_seconds}",
            )
        if self.recovery_check_interval_seconds <= 0:
            raise ValueError(
                f"recovery_check_interval_seconds must be > 0, "
                f"got {self.recovery_check_interval_seconds}",
            )
        for backend, region_list in self.regions.items():
            if not isinstance(backend, str) or not backend:
                raise ValueError(
                    f"regions keys must be non-empty strings, got {backend!r}",
                )
            if not region_list:
                raise ValueError(
                    f"regions[{backend!r}] must be a non-empty list, got {region_list!r}",
                )
            for region in region_list:
                if not isinstance(region, str) or not region:
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
    when a CB transitions. No background threads are created.
    """

    def __init__(
        self,
        config: FailoverConfig,
        cb_registry: dict[str, Any] | None = None,
        *,
        clock: Callable[[], float] | None = None,
        health_probe: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize the failover router.

        Args:
            config: Failover configuration including enabled flag and region map.
            cb_registry: Optional mapping of backend names to LLMCircuitBreaker
                instances, used only for snapshot() enrichment. Does not affect
                routing decisions.
            clock: Monotonic clock for measuring failover duration. Defaults to
                time.monotonic. Injectable for tests.
            health_probe: Callable that accepts a region string and returns True
                if the region is healthy. Defaults to a function that always
                returns True (assume healthy). Injectable for tests to simulate
                failures. Any exception raised by the probe is caught and treated
                as a probe failure -- no failover is committed.
        """
        self._config = config
        self._cb_registry = cb_registry
        self._clock: Callable[[], float] = clock or time.monotonic
        self._health_probe: Callable[[str], bool] = health_probe or (lambda _region: True)
        self._lock = threading.Lock()
        # Per-backend failover state:
        #   _active_region[backend] = str (current active region)
        #   _failover_at[backend] = float | None (clock value when failover committed, None if not failed over)
        #   _failover_pending[backend] = bool (True while a probe is in-flight for this backend)
        #     Prevents concurrent threads from all probing and committing independently.
        self._active_region: dict[str, str] = {}
        self._failover_at: dict[str, float | None] = {}
        self._failover_pending: dict[str, bool] = {}

    def get_active_region(self, backend: str) -> str | None:
        """Return the active region for a backend, or None if not configured.

        Returns None when config.enabled is False or the backend has no
        regions configured. Returns the primary (regions[backend][0]) when
        not failed over, or the secondary when failed over.

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
            return self._active_region.get(backend, region_list[0])

    def on_cb_state_change(self, backend: str, old_state: str, new_state: str) -> None:
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
        - An exception is raised by the health probe (treated as probe failure)

        Args:
            backend: Logical backend name.
            old_state: CB state before the transition (for logging).
            new_state: CB state after the transition.
        """
        if not self._config.enabled:
            return
        region_list = self._config.regions.get(backend)
        if not region_list:
            return

        if new_state == "open":
            self._handle_open(backend, old_state, region_list)
        elif new_state == "closed":
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
        with self._lock:
            already_failed_over = self._failover_at.get(backend) is not None
            pending = self._failover_pending.get(backend, False)
            if already_failed_over or pending:
                # Idempotent: already on secondary, or another thread is probing.
                return
            if len(region_list) < 2:
                # No secondary configured for this backend.
                logger.warning(
                    "Failover triggered for %r but no secondary region configured "
                    "(regions list has only one entry).",
                    backend,
                )
                return
            # Claim the probe slot before releasing the lock.
            self._failover_pending[backend] = True

        # Probe runs outside the lock so it cannot block concurrent reads.
        primary = region_list[0]
        committed = False
        try:
            for candidate in region_list[1:]:
                probe_result = False
                try:
                    probe_result = bool(self._health_probe(candidate))
                except Exception:  # noqa: BLE001 -- probe failures must never propagate
                    logger.warning(
                        "Health probe for %r raised an exception; skipping region %r.",
                        backend,
                        candidate,
                    )
                    continue
                if probe_result:
                    with self._lock:
                        self._active_region[backend] = candidate
                        self._failover_at[backend] = self._clock()
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
            # Always clear the pending flag so future OPEN events can retry.
            with self._lock:
                self._failover_pending[backend] = False

    def _handle_closed(
        self,
        backend: str,
        old_state: str,
        region_list: list[str],
    ) -> None:
        """Internal: evaluate recovery when CB returns to CLOSED."""
        with self._lock:
            failover_at = self._failover_at.get(backend)
            if failover_at is None:
                # Not failed over -- nothing to restore.
                return
            now = self._clock()
            elapsed = now - failover_at
            min_duration = self._config.min_failover_duration_seconds
            if elapsed >= min_duration:
                primary = region_list[0]
                self._active_region.pop(backend, None)
                self._failover_at[backend] = None
                logger.info(
                    "Recovery complete for %r: restored primary %r "
                    "(elapsed=%.1fs >= min_duration=%.1fs, CB transitioned %s -> closed).",
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
                    "Recovery deferred for %r: staying on %r for %.1f more seconds "
                    "(elapsed=%.1fs < min_duration=%.1fs).",
                    backend,
                    active,
                    remaining,
                    elapsed,
                    min_duration,
                )

    def is_failed_over(self, backend: str) -> bool:
        """Return True iff the backend is currently routing to a secondary region.

        Args:
            backend: Logical backend name.

        Returns:
            True if currently failed over, False otherwise (including when
            config.enabled is False or backend has no regions configured).
        """
        if not self._config.enabled:
            return False
        with self._lock:
            return self._failover_at.get(backend) is not None

    def snapshot(self) -> dict[str, Any]:
        """Return an observable point-in-time snapshot of all backends.

        All live fields are captured under a single lock acquisition.

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

        Clears failover state regardless of min_failover_duration_seconds.
        Safe to call when not failed over (no-op in that case).

        Args:
            backend: Logical backend name.
        """
        region_list = self._config.regions.get(backend)
        with self._lock:
            self._active_region.pop(backend, None)
            self._failover_at[backend] = None
            self._failover_pending[backend] = False
        if region_list:
            logger.info("Administrative reset for %r: restored primary %r.", backend, region_list[0])
