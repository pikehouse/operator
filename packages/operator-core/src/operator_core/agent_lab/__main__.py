"""Entry point for running agent_lab as a module."""
import asyncio
import sys
from pathlib import Path

from operator_core.agent_lab.loop import run_agent_loop
from operator_core.cli import DEFAULT_DB_PATH

if __name__ == "__main__":
    db_path = DEFAULT_DB_PATH

    # Allow override via command line
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])

    asyncio.run(run_agent_loop(db_path))
