#!/bin/bash
# Run the TUI demo with proper environment

cd /Users/jrtipton/x/operator

export PD_ENDPOINT=http://localhost:2379
export PROMETHEUS_URL=http://localhost:9090

# Source .env for ANTHROPIC_API_KEY
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Use a proper script file to ensure stdin is connected as TTY for keyboard input
uv run --package operator-core python scripts/tui_main.py
