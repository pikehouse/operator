#!/bin/bash
# GCP Cloud Eval Smoke Test
#
# Validates the cloud infrastructure is working:
# 1. Connects to Cloud SQL
# 2. Creates a test campaign
# 3. Enqueues work items
# 4. Simulates worker claiming work
# 5. Cleans up test data
#
# Prerequisites:
#   - Cloud SQL instance running and accessible
#   - EVAL_DATABASE_URL set in .env or environment
#
# Usage:
#   ./scripts/gcp-smoke-test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVAL_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$EVAL_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

echo "=== GCP Cloud Eval Smoke Test ==="
echo ""

# Load environment
if [ -f "$ENV_FILE" ]; then
    echo ">>> Loading .env from ${ENV_FILE}"
    set -a
    source "$ENV_FILE"
    set +a
fi

# Check for required env var
if [ -z "${EVAL_DATABASE_URL:-}" ]; then
    echo "Error: EVAL_DATABASE_URL not set"
    echo "Run ./scripts/gcp-setup.sh first or set EVAL_DATABASE_URL"
    exit 1
fi

# Strip quotes if present
EVAL_DATABASE_URL="${EVAL_DATABASE_URL//\"/}"

echo ">>> Testing connection to Cloud SQL..."
echo "    URL: ${EVAL_DATABASE_URL%%:*}://***@${EVAL_DATABASE_URL#*@}"
echo ""

cd "$EVAL_DIR"

# Run the Python smoke test
uv run python -c "
import asyncio
import os
import sys

async def smoke_test():
    from datetime import datetime, timezone
    from eval.runner.db_postgres import PostgresDB
    from eval.runner.queue import WorkQueue
    from eval.types import Campaign

    db_url = os.environ['EVAL_DATABASE_URL']
    print('>>> Connecting to PostgreSQL...')

    try:
        db = PostgresDB(db_url)
        await db.ensure_schema()
        print('    Connected and schema verified')
    except Exception as e:
        print(f'    FAILED: {e}')
        sys.exit(1)

    try:
        # Create test campaign
        print('>>> Creating test campaign...')
        now = datetime.now(timezone.utc)
        campaign = Campaign(
            id=None,
            subject_name='tikv',
            chaos_type='smoke_test',
            trial_count=2,
            baseline=False,
            variant_name='smoke_test_variant',
            created_at=now.isoformat()
        )
        campaign_id = await db.insert_campaign(campaign)
        print(f'    Created campaign_id={campaign_id}')

        # Enqueue work items
        print('>>> Enqueuing work items...')
        queue = WorkQueue(db)
        work_items = [
            {'subject_type': 'tikv', 'chaos_type': 'node_kill', 'baseline': False},
            {'subject_type': 'tikv', 'chaos_type': 'latency', 'chaos_params': {'min_ms': 50, 'max_ms': 100}},
        ]
        work_ids = await queue.enqueue(campaign_id, work_items)
        print(f'    Enqueued {len(work_ids)} work items: {work_ids}')

        # Check queue status
        status = await queue.get_campaign_status(campaign_id)
        print(f'    Queue status: {status}')
        assert status['pending'] == 2, f'Expected 2 pending, got {status}'

        # Simulate worker claiming
        print('>>> Simulating worker claim...')
        worker_id = 'smoke-test-worker'
        item = await queue.claim_next(worker_id)
        assert item is not None, 'Expected to claim work item'
        print(f'    Claimed work_id={item.id}, chaos_type={item.chaos_type}')

        # Check updated status
        status = await queue.get_campaign_status(campaign_id)
        print(f'    Queue status: {status}')
        assert status['pending'] == 1, f'Expected 1 pending, got {status}'
        assert status['running'] == 1, f'Expected 1 running, got {status}'

        # Complete the work item
        print('>>> Completing work item...')
        await queue.complete(item.id, trial_id=None, error=None)

        status = await queue.get_campaign_status(campaign_id)
        print(f'    Queue status: {status}')
        assert status['completed'] == 1, f'Expected 1 completed, got {status}'

        # Cleanup: delete test data
        print('>>> Cleaning up test data...')
        pool = await db._get_pool()
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM work_queue WHERE campaign_id = \$1', campaign_id)
            await conn.execute('DELETE FROM trials WHERE campaign_id = \$1', campaign_id)
            await conn.execute('DELETE FROM campaigns WHERE id = \$1', campaign_id)
        print('    Cleaned up test campaign and work items')

        await db.close()
        print('')
        print('=== Smoke Test PASSED ===')
        print('')
        print('Cloud SQL is working correctly. You can now:')
        print('')
        print('  # Start workers')
        print('  ./scripts/gcp-workers.sh start 5')
        print('')
        print('  # Run a campaign')
        print('  eval run campaign campaigns/smoke-test.yaml --cloud=gcp')

    except Exception as e:
        print(f'    FAILED: {e}')
        import traceback
        traceback.print_exc()
        await db.close()
        sys.exit(1)

asyncio.run(smoke_test())
"

exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo ""
    echo "=== Smoke Test FAILED ==="
    exit $exit_code
fi
