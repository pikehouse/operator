#!/usr/bin/env bash
# Run the chaos demo for TiKV or Rate Limiter with TUI integration

set -euo pipefail

# Usage message
usage() {
    cat <<EOF
Usage: $0 [tikv|ratelimiter]

Run the chaos demo for the specified subject with full TUI integration.

Arguments:
  tikv         Run TiKV chaos demo (default)
  ratelimiter  Run Rate Limiter chaos demo

Examples:
  $0                 # Run TiKV demo (default)
  $0 tikv            # Run TiKV demo
  $0 ratelimiter     # Run Rate Limiter demo

Requirements:
  - Docker Compose running appropriate cluster
  - ANTHROPIC_API_KEY set in .env
EOF
}

# Parse arguments
SUBJECT="${1:-tikv}"

if [[ "$SUBJECT" == "--help" ]] || [[ "$SUBJECT" == "-h" ]]; then
    usage
    exit 0
fi

# Validate subject argument
if [[ "$SUBJECT" != "tikv" ]] && [[ "$SUBJECT" != "ratelimiter" ]]; then
    echo "Error: Invalid subject '$SUBJECT'. Must be 'tikv' or 'ratelimiter'."
    echo ""
    usage
    exit 1
fi

# Ensure we're in project root
cd "$(dirname "$0")/.."

# Source .env for ANTHROPIC_API_KEY
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set subject-specific configuration
if [[ "$SUBJECT" == "tikv" ]]; then
    COMPOSE_FILE="subjects/tikv/docker-compose.yaml"
    export PD_ENDPOINT=http://localhost:2379
    export PROMETHEUS_URL=http://localhost:9090

    echo "========================================="
    echo "TiKV Chaos Demo"
    echo "========================================="
    echo ""
    echo "Compose file: $COMPOSE_FILE"
    echo ""
    echo "Ensure TiKV cluster is running:"
    echo "  docker compose -f $COMPOSE_FILE up -d"
    echo ""

elif [[ "$SUBJECT" == "ratelimiter" ]]; then
    COMPOSE_FILE="docker/docker-compose.yml"
    # Rate limiter endpoints for monitor/agent subprocesses
    export RATELIMITER_URL="http://localhost:8001"
    export REDIS_URL="redis://localhost:6379"
    export PROMETHEUS_URL="http://localhost:9090"

    echo "========================================="
    echo "Rate Limiter Chaos Demo"
    echo "========================================="
    echo ""
    echo "Compose file: $COMPOSE_FILE"
    echo ""

    # Ensure rate limiter cluster is running
    echo "Checking cluster status..."
    if ! docker compose -f "$COMPOSE_FILE" ps | grep -q "ratelimiter"; then
        echo ""
        echo "Starting rate limiter cluster..."
        docker compose -f "$COMPOSE_FILE" up -d
        echo ""
        echo "Waiting for services to be ready..."
        sleep 3
    else
        echo "Cluster is running."
    fi
    echo ""
fi

export COMPOSE_FILE

# Run the demo via python -m demo
echo "Starting demo..."
echo ""
uv run python -m demo "$SUBJECT"
