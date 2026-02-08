#!/bin/bash
# GCP Worker Management
#
# Usage:
#   ./scripts/gcp-workers.sh start 5      # Start 5 workers
#   ./scripts/gcp-workers.sh stop         # Stop all workers
#   ./scripts/gcp-workers.sh status       # List running workers
#   ./scripts/gcp-workers.sh logs worker-1 # View worker logs

set -euo pipefail

ZONE="${GCP_ZONE:-us-central1-a}"
TEMPLATE="eval-worker-template"

cmd="${1:-help}"
shift || true

case "$cmd" in
    start)
        count="${1:-1}"
        echo "Starting ${count} worker(s)..."
        for i in $(seq 1 "$count"); do
            name="eval-worker-$(date +%s)-${i}"
            echo "  Creating ${name}..."
            gcloud compute instances create "$name" \
                --source-instance-template="$TEMPLATE" \
                --zone="$ZONE" \
                --quiet
        done
        echo "Workers starting. Use '$0 status' to check."
        ;;

    stop)
        echo "Stopping all eval workers..."
        workers=$(gcloud compute instances list \
            --filter="name~'^eval-worker-'" \
            --format="value(name)" \
            --zones="$ZONE" 2>/dev/null || true)

        if [ -z "$workers" ]; then
            echo "No workers found."
            exit 0
        fi

        echo "$workers" | while read -r name; do
            echo "  Deleting ${name}..."
            gcloud compute instances delete "$name" --zone="$ZONE" --quiet --quiet
        done
        echo "Workers stopping."
        ;;

    status)
        echo "Running workers:"
        gcloud compute instances list \
            --filter="name~'^eval-worker-'" \
            --format="table(name,zone,status,networkInterfaces[0].accessConfigs[0].natIP)"
        ;;

    logs)
        instance="${1:?Usage: $0 logs <instance-name>}"
        echo "Fetching logs from ${instance}..."
        gcloud compute ssh "$instance" --zone="$ZONE" --command="docker logs eval-worker --tail 100"
        ;;

    ssh)
        instance="${1:?Usage: $0 ssh <instance-name>}"
        gcloud compute ssh "$instance" --zone="$ZONE"
        ;;

    help|*)
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Commands:"
        echo "  start <count>     Start N workers (default: 1)"
        echo "  stop              Stop all workers"
        echo "  status            List running workers"
        echo "  logs <instance>   View worker logs"
        echo "  ssh <instance>    SSH into worker"
        echo ""
        echo "Environment:"
        echo "  GCP_ZONE          Override zone (default: us-central1-a)"
        ;;
esac
