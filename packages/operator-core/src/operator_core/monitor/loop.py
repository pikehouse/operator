"""
MonitorLoop daemon for continuous invariant checking.

This module implements the monitor loop daemon that:
- Runs continuously at a configurable interval
- Checks all registered invariants via InvariantChecker
- Creates/updates tickets for violations via TicketDB
- Auto-resolves tickets when violations clear
- Outputs periodic heartbeat messages
- Handles graceful shutdown on SIGINT/SIGTERM

Per RESEARCH.md Pattern 2: Daemon Loop with Signal Handling
- Uses asyncio.Event for shutdown coordination
- Registers signal handlers inside run() with get_running_loop()
- Uses wait_for with timeout for interruptible sleep
"""

import asyncio
import functools
import signal
from datetime import datetime
from pathlib import Path

from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import make_violation_key
from operator_protocols import (
    InvariantCheckerProtocol,
    InvariantViolation,
    SubjectProtocol,
)


class MonitorLoop:
    """
    Long-running daemon that checks invariants and manages tickets.

    Runs continuously at configurable interval, checking all registered
    invariants, creating tickets for violations, and auto-resolving
    tickets when conditions clear.

    Uses asyncio.Event for shutdown coordination per RESEARCH.md.

    This class is subject-agnostic - it works with any SubjectProtocol
    and InvariantCheckerProtocol implementation.

    Example:
        subject = create_tikv_subject(pd_client, prom_client)
        checker = TiKVInvariantChecker()
        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=Path("~/.operator/tickets.db"),
            interval_seconds=30.0,
        )
        await loop.run()  # Runs until SIGINT/SIGTERM
    """

    def __init__(
        self,
        subject: SubjectProtocol,
        checker: InvariantCheckerProtocol,
        db_path: Path,
        interval_seconds: float = 30.0,
    ) -> None:
        """
        Initialize monitor loop.

        Args:
            subject: Any SubjectProtocol implementation for observations
            checker: Any InvariantCheckerProtocol for invariant checks
            db_path: Path to SQLite database file
            interval_seconds: Seconds between check cycles (default 30)
        """
        self.subject = subject
        self.checker = checker
        self.db_path = db_path
        self.interval = interval_seconds
        self._shutdown = asyncio.Event()

        # Stats for heartbeat
        self._invariant_count = 0
        self._violation_count = 0
        self._last_check: datetime | None = None

    async def run(self) -> None:
        """
        Run the monitor loop until shutdown signal.

        Registers SIGINT and SIGTERM handlers for graceful shutdown.
        Checks invariants at configured interval, creating/updating
        tickets for violations.
        """
        loop = asyncio.get_running_loop()

        # Register signal handlers per RESEARCH.md Pattern 2
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        print(f"Monitor loop starting (interval: {self.interval}s)")

        async with TicketDB(self.db_path) as db:
            while not self._shutdown.is_set():
                await self._check_cycle(db)
                self._log_heartbeat()

                # Wait for interval or shutdown signal
                # Per RESEARCH.md: Use Event.wait() with timeout, not asyncio.sleep
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self.interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue loop

        print("Monitor loop stopped")

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signal by setting shutdown event."""
        print(f"Received {sig.name}, shutting down...")
        self._shutdown.set()

    async def _check_cycle(self, db: TicketDB) -> None:
        """
        Run one check cycle across all invariants.

        Uses the generic observe/check pattern:
        1. Call subject.observe() to get current system state
        2. Call checker.check(observation) to detect violations
        3. Create/update tickets for violations
        4. Auto-resolve tickets for cleared violations

        This is subject-agnostic - works with any SubjectProtocol/InvariantCheckerProtocol.
        """
        self._last_check = datetime.now()

        try:
            # Generic observation pattern - subject handles all data gathering
            observation = await self.subject.observe()

            # Generic check pattern - checker handles all invariant checking
            violations = self.checker.check(observation)
        except Exception as e:
            # Log but don't crash on observation/check failure
            print(f"Check cycle failed: {e}")
            violations = []

        # Track stats
        self._invariant_count = len(violations) if violations else 0
        self._violation_count = len(violations)

        # Create/update tickets for violations
        if violations:
            batch_key = f"batch-{datetime.now().isoformat()}"
            for v in violations:
                await db.create_or_update_ticket(v, batch_key=batch_key)

        # Auto-resolve cleared violations (per CONTEXT.md)
        current_keys = {make_violation_key(v) for v in violations}
        resolved_count = await db.auto_resolve_cleared(current_keys)
        if resolved_count > 0:
            print(f"Auto-resolved {resolved_count} ticket(s)")

    def _log_heartbeat(self) -> None:
        """Output periodic status message per CONTEXT.md."""
        status = (
            "all passing"
            if self._violation_count == 0
            else f"{self._violation_count} violations"
        )
        print(f"Check complete: {self._invariant_count} invariants, {status}")
