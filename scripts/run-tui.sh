#!/bin/bash
# Run the TUI demo with proper environment

cd /Users/jrtipton/x/operator

export PD_ENDPOINT=http://localhost:2379
export PROMETHEUS_URL=http://localhost:9090

# Source .env for ANTHROPIC_API_KEY
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

uv run --package operator-core python -c "
import asyncio
from operator_core.tui import TUIController

async def main():
    controller = TUIController()
    await controller.run()

asyncio.run(main())
"
