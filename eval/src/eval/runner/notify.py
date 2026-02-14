"""LISTEN/NOTIFY-based campaign progress tracking.

Uses PostgreSQL LISTEN/NOTIFY for instant wake-up when work items complete,
with polling fallback for reliability. Displays live Rich progress.
"""

import asyncio
import json
import logging

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from rich.live import Live
from rich.table import Table
from rich.text import Text

from eval.runner.db_postgres import PostgresDB
from eval.runner.queue import WorkQueue

logger = logging.getLogger(__name__)


def _build_display(
    campaign_id: int,
    counts: dict[str, int],
    listening: bool,
) -> Table:
    """Build Rich table showing campaign progress."""
    total = sum(counts.values())
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    running = counts.get("running", 0)
    pending = counts.get("pending", 0)
    done = completed + failed

    pct = int(done / total * 100) if total else 100
    bar_filled = pct // 5
    bar = f"{'█' * bar_filled}{'░' * (20 - bar_filled)}"

    table = Table(show_header=False, show_edge=False, pad_edge=False, box=None)
    table.add_column(min_width=60)

    mode = "live" if listening else "polling"
    table.add_row(Text(f"Campaign {campaign_id} ({mode})", style="bold"))
    table.add_row(Text(f"  {bar} {done}/{total} ({pct}%)"))

    parts = []
    if completed:
        parts.append(f"[green]{completed} completed[/green]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    if running:
        parts.append(f"[cyan]{running} running[/cyan]")
    if pending:
        parts.append(f"[yellow]{pending} pending[/yellow]")
    table.add_row(Text.from_markup("  " + "  ".join(parts)))

    return table


async def wait_for_campaign(
    db_url: str,
    campaign_id: int,
    poll_interval: float = 30.0,
) -> dict[str, int]:
    """Wait for a campaign to complete, showing live progress.

    Uses PostgreSQL LISTEN/NOTIFY for instant updates when work items
    complete, falling back to polling if LISTEN fails.

    Args:
        db_url: PostgreSQL connection URL
        campaign_id: Campaign ID to wait for
        poll_interval: Seconds between poll fallbacks

    Returns:
        Final status counts dict (completed, failed, running, pending)
    """
    db = PostgresDB(db_url)
    await db.ensure_schema()
    queue = WorkQueue(db)

    # Event signaled by LISTEN callback
    wake = asyncio.Event()
    listening = False
    listen_conn = None

    def _on_notify(conn, pid, channel, payload):
        try:
            data = json.loads(payload)
            if data.get("campaign_id") == campaign_id:
                wake.set()
        except (json.JSONDecodeError, KeyError):
            wake.set()  # Wake on any parse error to be safe

    # Try to set up LISTEN connection
    try:
        listen_conn = await asyncpg.connect(db_url)
        await listen_conn.add_listener("work_item_completed", _on_notify)
        listening = True
    except Exception as e:
        logger.warning(f"LISTEN setup failed, using polling only: {e}")
        listening = False

    try:
        # Get initial status
        counts = await queue.get_campaign_status(campaign_id)
        total = sum(counts.values())

        if total == 0:
            from rich.console import Console
            Console().print(f"[red]No work items found for campaign {campaign_id}[/red]")
            return counts

        with Live(_build_display(campaign_id, counts, listening), refresh_per_second=1) as live:
            while True:
                pending = counts.get("pending", 0)
                running = counts.get("running", 0)

                if pending + running == 0:
                    live.update(_build_display(campaign_id, counts, listening))
                    break

                # Wait for notification or poll timeout
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass

                # Always refresh from DB (notifications just wake us faster)
                counts = await queue.get_campaign_status(campaign_id)
                live.update(_build_display(campaign_id, counts, listening))

        return counts

    finally:
        if listen_conn is not None:
            try:
                await listen_conn.remove_listener("work_item_completed", _on_notify)
                await listen_conn.close()
            except Exception:
                pass
        await db.close()
