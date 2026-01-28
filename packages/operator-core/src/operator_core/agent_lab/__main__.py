"""Entry point for running agent_lab as a module."""
from pathlib import Path
import sys

from operator_core.agent_lab.loop import run_agent_loop

if __name__ == "__main__":
    # Default to ~/.operator/tickets.db
    db_path = Path.home() / ".operator" / "tickets.db"

    # Allow override via command line
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])

    run_agent_loop(db_path)
