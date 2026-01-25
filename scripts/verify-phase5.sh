#!/usr/bin/env bash
# Phase 5 Verification Script
# Tests AI diagnosis end-to-end

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Phase 5: AI Diagnosis Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${RED}ERROR: ANTHROPIC_API_KEY not set${NC}"
    echo "Export your API key: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi
echo -e "${GREEN}✓${NC} ANTHROPIC_API_KEY is set"

# Change to subjects/tikv directory (where docker-compose.yaml is)
cd "$PROJECT_ROOT/subjects/tikv"

# Check if cluster is running
echo
echo "Checking cluster status..."
if ! docker compose ps --format json 2>/dev/null | grep -q "running"; then
    echo -e "${YELLOW}Starting cluster...${NC}"
    docker compose up -d
    echo "Waiting 30s for cluster to initialize..."
    sleep 30
else
    echo -e "${GREEN}✓${NC} Cluster is running"
fi

# Create a fresh test database
TEST_DB="/tmp/operator-test-$$.db"
echo
echo "Using test database: $TEST_DB"

# Stop tikv0 to create a violation
echo
echo "Stopping tikv0 to create an invariant violation..."
docker compose stop tikv0

# Run monitor briefly to create a ticket (background + sleep + kill for macOS compatibility)
echo
echo "Running monitor for 15s to detect violation..."
cd "$PROJECT_ROOT"
uv run operator monitor run --interval 5 --db "$TEST_DB" &
MONITOR_PID=$!
sleep 15
kill $MONITOR_PID 2>/dev/null || true
wait $MONITOR_PID 2>/dev/null || true

# Check if we got a ticket
echo
echo "Checking for tickets..."
TICKET_COUNT=$(uv run operator tickets list --db "$TEST_DB" --json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$TICKET_COUNT" -lt 1 ]; then
    echo -e "${YELLOW}No tickets created yet. Running monitor longer...${NC}"
    uv run operator monitor run --interval 5 --db "$TEST_DB" &
    MONITOR_PID=$!
    sleep 30
    kill $MONITOR_PID 2>/dev/null || true
    wait $MONITOR_PID 2>/dev/null || true
fi

# List tickets
echo
echo "Current tickets:"
uv run operator tickets list --db "$TEST_DB"

# Get first ticket ID
TICKET_ID=$(uv run operator tickets list --db "$TEST_DB" --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")

if [ -z "$TICKET_ID" ]; then
    echo -e "${RED}ERROR: No tickets found to diagnose${NC}"
    echo "The cluster may not have any invariant violations."
    echo "Try stopping a TiKV node: docker compose stop tikv0"
    rm -f "$TEST_DB"
    exit 1
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Running AI Diagnosis on Ticket #$TICKET_ID"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# Run diagnosis
uv run operator agent diagnose "$TICKET_ID" --db "$TEST_DB"

# Show the diagnosis
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Diagnosis Result"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
uv run operator tickets show "$TICKET_ID" --db "$TEST_DB"

# Cleanup - restart tikv0 and remove test db
echo
echo "Restarting tikv0..."
cd "$PROJECT_ROOT/subjects/tikv"
docker compose start tikv0
cd "$PROJECT_ROOT"
rm -f "$TEST_DB"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e " ${GREEN}Verification Complete${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "Check the diagnosis above for:"
echo "  • Timeline section"
echo "  • Affected Components"
echo "  • Metric Readings"
echo "  • Primary Diagnosis with confidence"
echo "  • Alternatives Considered (2-3)"
echo "  • Recommended Action with severity and risks"
echo
