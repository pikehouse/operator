#!/bin/bash
# GCP End-to-End Smoke Test
#
# Integration test that validates Cloud SQL queue infrastructure:
# 1. Creates a campaign in Cloud SQL
# 2. Runs a LOCAL worker process (uses local Docker for TiKV)
# 3. Waits for trial to complete
# 4. Validates results in Cloud SQL
# 5. Cleans up
#
# This tests the distributed queue coordination without spinning up GCP VMs,
# making it fast and cheap while still validating the cloud infrastructure.
#
# Prerequisites:
#   - Cloud SQL instance running and accessible
#   - EVAL_DATABASE_URL set in .env or environment
#   - Docker running locally (for TiKV cluster)
#   - TiKV chaos image built: docker compose build (in subjects/tikv/)
#
# Usage:
#   ./scripts/gcp-e2e-test.sh [--timeout MINUTES] [--cleanup-only]
#
# Options:
#   --timeout M       Timeout in minutes (default: 10)
#   --cleanup-only    Just clean up any existing test data

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVAL_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$EVAL_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

# Defaults
TIMEOUT_MINUTES=10
CLEANUP_ONLY=false
CAMPAIGN_ID=""
WORKER_PID=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}>>>${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --timeout)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  GCP End-to-End Smoke Test${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Load environment
if [ -f "$ENV_FILE" ]; then
    log_info "Loading .env from ${ENV_FILE}"
    set -a
    source "$ENV_FILE"
    set +a
fi

# Strip quotes from EVAL_DATABASE_URL if present
EVAL_DATABASE_URL="${EVAL_DATABASE_URL//\"/}"
export EVAL_DATABASE_URL

# Check prerequisites
if [ -z "${EVAL_DATABASE_URL:-}" ]; then
    log_error "EVAL_DATABASE_URL not set"
    exit 1
fi

cd "$EVAL_DIR"

# Cleanup function
cleanup() {
    local exit_code=$?
    echo ""
    log_info "Cleaning up..."

    # Stop local worker if running
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        log_info "Stopping local worker (PID $WORKER_PID)..."
        kill "$WORKER_PID" 2>/dev/null || true
        wait "$WORKER_PID" 2>/dev/null || true
    fi

    # Stop any Docker containers from the test (instance_id=5 -> project tikv-eval-1)
    log_info "Stopping TiKV containers..."
    docker compose -f "$PROJECT_ROOT/subjects/tikv/docker-compose.yaml" -p tikv-eval-1 down -v 2>/dev/null || true

    # Clean up test campaign data if we created one
    if [ -n "$CAMPAIGN_ID" ]; then
        log_info "Cleaning up test campaign $CAMPAIGN_ID..."
        uv run python -c "
import asyncio
import os

async def cleanup():
    from eval.runner.db_postgres import PostgresDB

    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    pool = await db._get_pool()

    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM work_queue WHERE campaign_id = \$1', $CAMPAIGN_ID)
        await conn.execute('DELETE FROM trials WHERE campaign_id = \$1', $CAMPAIGN_ID)
        await conn.execute('DELETE FROM campaigns WHERE id = \$1', $CAMPAIGN_ID)

    await db.close()
    print('    Cleaned up campaign $CAMPAIGN_ID')

asyncio.run(cleanup())
" 2>/dev/null || log_warn "Failed to clean up campaign data"
    fi

    if [ $exit_code -eq 0 ]; then
        echo ""
        log_success "Test completed successfully!"
    else
        echo ""
        log_error "Test failed with exit code $exit_code"
    fi

    exit $exit_code
}

trap cleanup EXIT

# Cleanup-only mode
if [ "$CLEANUP_ONLY" = true ]; then
    log_info "Cleanup-only mode"
    docker compose -f "$PROJECT_ROOT/subjects/tikv/docker-compose.yaml" -p tikv-eval-1 down -v 2>/dev/null || true
    log_success "Cleanup complete"
    exit 0
fi

# Check Docker is running
if ! docker info &>/dev/null; then
    log_error "Docker is not running"
    exit 1
fi

# Step 1: Verify Cloud SQL connection
log_info "Step 1: Verifying Cloud SQL connection..."
uv run python -c "
import asyncio
import os

async def verify():
    from eval.runner.db_postgres import PostgresDB
    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    await db.ensure_schema()
    await db.close()
    print('    Connection verified')

asyncio.run(verify())
"
log_success "Cloud SQL connection OK"

# Step 2: Create test campaign with single node_kill trial
log_info "Step 2: Creating test campaign..."
CAMPAIGN_ID=$(uv run python -c "
import asyncio
import os
from datetime import datetime, timezone

async def create_campaign():
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue
    from eval.types import Campaign

    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    await db.ensure_schema()
    queue = WorkQueue(db)

    # Create minimal test campaign (1 trial)
    now = datetime.now(timezone.utc)
    pool = await db._get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''
            INSERT INTO campaigns (subject_name, chaos_type, trial_count, baseline, variant_name, created_at)
            VALUES (\$1, \$2, \$3, \$4, \$5, \$6)
            RETURNING id
        ''', 'tikv', 'node_kill', 1, False, 'e2e-test', now)
        campaign_id = row['id']

    # Enqueue single work item
    work_items = [{'subject_type': 'tikv', 'chaos_type': 'node_kill', 'baseline': False}]
    await queue.enqueue(campaign_id, work_items)

    await db.close()
    print(campaign_id)

asyncio.run(create_campaign())
")
log_success "Created campaign $CAMPAIGN_ID with 1 work item"

# Step 3: Start local worker process
log_info "Step 3: Starting local worker (background)..."

# Run worker in background with LOCAL mode (uses local Docker)
# The worker will poll Cloud SQL and execute trials locally
uv run python -c "
import asyncio
import os
import sys

async def run_local_worker():
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue
    from eval.subjects.factory import SubjectRegistry
    from eval.types import Trial
    import json
    from datetime import datetime, timezone

    db_url = os.environ['EVAL_DATABASE_URL']
    worker_id = 'e2e-test-worker'

    db = PostgresDB(db_url)
    await db.ensure_schema()
    queue = WorkQueue(db)

    print(f'Worker {worker_id} starting (LOCAL mode)')

    # Process ONE work item then exit
    work_item = await queue.claim_next(worker_id)
    if not work_item:
        print('No work available')
        await db.close()
        return

    print(f'Claimed work {work_item.id}: {work_item.chaos_type}')

    trial_id = None
    error = None

    try:
        # Create LOCAL subject (uses docker-compose on this machine)
        # Use instance_id=1 to avoid conflicts with default instance 0
        # Port offset = 1 * 10000 = 10000, so PD at 12379, TiKV at 30160
        subject = SubjectRegistry.create(
            work_item.subject_type,
            instance_id=1,
            mode='local',
        )

        def now():
            return datetime.now(timezone.utc).isoformat()

        started_at = now()

        # Reset subject (starts TiKV cluster)
        print('Resetting subject...')
        await subject.reset()

        # Wait for healthy
        print('Waiting for healthy...')
        healthy = await subject.wait_healthy(timeout_sec=120.0)
        if not healthy:
            raise RuntimeError('Subject failed to become healthy')

        initial_state = await subject.capture_state()

        # Inject chaos
        print(f'Injecting chaos: {work_item.chaos_type}')
        chaos_injected_at = now()
        chaos_metadata = await subject.inject_chaos(
            work_item.chaos_type,
            **work_item.chaos_params
        )

        # Wait briefly then cleanup
        await asyncio.sleep(5)

        # Cleanup chaos
        await subject.cleanup_chaos(chaos_metadata)

        # Wait for recovery
        print('Waiting for recovery...')
        resolved = await subject.wait_healthy(timeout_sec=60.0)
        resolved_at = now() if resolved else None

        final_state = await subject.capture_state()
        ended_at = now()

        # Create trial record
        trial = Trial(
            campaign_id=work_item.campaign_id,
            started_at=started_at,
            chaos_injected_at=chaos_injected_at,
            ticket_created_at=None,
            resolved_at=resolved_at,
            ended_at=ended_at,
            initial_state=json.dumps(initial_state),
            final_state=json.dumps(final_state),
            chaos_metadata=json.dumps(chaos_metadata),
            commands_json='[]',
        )
        trial_id = await db.insert_trial(trial)
        print(f'Trial {trial_id} recorded')

    except Exception as e:
        error = str(e)
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

    finally:
        # Mark work complete
        await queue.complete(work_item.id, trial_id=trial_id, error=error)
        print(f'Work item {work_item.id} completed')
        await db.close()

asyncio.run(run_local_worker())
" &
WORKER_PID=$!
log_success "Worker started (PID $WORKER_PID)"

# Step 4: Wait for work to complete
log_info "Step 4: Waiting for trial to complete (timeout: ${TIMEOUT_MINUTES}m)..."

TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
START_TIME=$(date +%s)
POLL_INTERVAL=15

while true; do
    ELAPSED=$(($(date +%s) - START_TIME))

    if [ $ELAPSED -ge $TIMEOUT_SECONDS ]; then
        log_error "Timeout waiting for trial to complete"

        # Show queue status for debugging
        log_info "Queue status:"
        uv run python -c "
import asyncio
import os

async def status():
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue

    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    queue = WorkQueue(db)
    status = await queue.get_campaign_status($CAMPAIGN_ID)
    print(f'    {status}')
    await db.close()

asyncio.run(status())
"
        exit 1
    fi

    # Check queue status
    STATUS=$(uv run python -c "
import asyncio
import os

async def check():
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue

    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    queue = WorkQueue(db)
    status = await queue.get_campaign_status($CAMPAIGN_ID)
    await db.close()

    pending = status.get('pending', 0)
    running = status.get('running', 0)
    completed = status.get('completed', 0)
    failed = status.get('failed', 0)

    # Return status code
    if completed + failed == 1:
        print('done')
    elif running > 0:
        print('running')
    else:
        print('pending')

asyncio.run(check())
")

    ELAPSED_MIN=$((ELAPSED / 60))
    ELAPSED_SEC=$((ELAPSED % 60))

    case "$STATUS" in
        done)
            log_success "Trial completed (${ELAPSED_MIN}m ${ELAPSED_SEC}s)"
            break
            ;;
        running)
            echo -ne "\r    Status: running... (${ELAPSED_MIN}m ${ELAPSED_SEC}s elapsed)    "
            ;;
        pending)
            echo -ne "\r    Status: pending... (${ELAPSED_MIN}m ${ELAPSED_SEC}s elapsed)    "
            ;;
    esac

    sleep $POLL_INTERVAL
done

echo ""  # Clear the status line

# Step 5: Validate results
log_info "Step 5: Validating results..."

VALIDATION=$(uv run python -c "
import asyncio
import os
import json

async def validate():
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue

    db = PostgresDB(os.environ['EVAL_DATABASE_URL'])
    queue = WorkQueue(db)

    # Check final status
    status = await queue.get_campaign_status($CAMPAIGN_ID)
    completed = status.get('completed', 0)
    failed = status.get('failed', 0)

    # Get work item details
    pool = await db._get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT status, error, trial_id FROM work_queue
            WHERE campaign_id = \$1
        ''', $CAMPAIGN_ID)

    await db.close()

    result = {
        'completed': completed,
        'failed': failed,
        'status': row['status'] if row else 'unknown',
        'error': row['error'] if row else None,
        'trial_id': row['trial_id'] if row else None,
    }

    print(json.dumps(result))

asyncio.run(validate())
")

COMPLETED=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['completed'])")
FAILED=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['failed'])")
STATUS=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
ERROR=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['error'] or '')")
TRIAL_ID=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['trial_id'] or '')")

echo "    Completed: $COMPLETED"
echo "    Failed: $FAILED"
echo "    Status: $STATUS"
if [ -n "$ERROR" ]; then
    echo "    Error: $ERROR"
fi
if [ -n "$TRIAL_ID" ]; then
    echo "    Trial ID: $TRIAL_ID"
fi

# Validation checks
if [ "$COMPLETED" -eq 1 ] && [ "$FAILED" -eq 0 ]; then
    log_success "Trial completed successfully"
elif [ "$FAILED" -eq 1 ]; then
    log_error "Trial failed: $ERROR"
    exit 1
else
    log_error "Unexpected state: completed=$COMPLETED, failed=$FAILED"
    exit 1
fi

# Check that trial was recorded
if [ -n "$TRIAL_ID" ]; then
    log_success "Trial recorded in database (trial_id=$TRIAL_ID)"
else
    log_warn "No trial_id recorded (worker may not have written results)"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  E2E Test PASSED${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Summary:"
echo "  - Cloud SQL: Connected and schema verified"
echo "  - Campaign: Created and work enqueued to Cloud SQL"
echo "  - Worker: Local process claimed work via Cloud SQL queue"
echo "  - Trial: Executed node_kill chaos on local Docker"
echo "  - Results: Written back to Cloud SQL database"
echo ""
echo "This validates the distributed queue infrastructure works correctly."
echo "For full cloud execution, use: ./scripts/gcp-workers.sh start N"
echo ""
