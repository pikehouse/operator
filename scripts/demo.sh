#!/bin/bash
# Demo management script for Operator
# Usage: ./scripts/demo.sh <command> [subject]
#
# Commands:
#   start <tikv|ratelimiter>  - Start cluster for demo
#   stop <tikv|ratelimiter>   - Stop cluster
#   reset <tikv|ratelimiter>  - Stop and restart cluster
#   status                    - Show status of all clusters
#   run <tikv|ratelimiter>    - Start cluster + run demo
#   ports                     - Check for port conflicts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Compose files
TIKV_COMPOSE="$PROJECT_DIR/subjects/tikv/docker-compose.yaml"
RATELIMITER_COMPOSE="$PROJECT_DIR/docker/docker-compose.yml"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

reset_demo_state() {
    log_info "Resetting demo state..."

    # Kill any running agent processes
    pkill -f "operator_core.agent_lab" 2>/dev/null && log_info "Killed agent process" || true
    pkill -f "operator_core.cli.main monitor" 2>/dev/null && log_info "Killed monitor process" || true

    # Reset ticket database
    TICKET_DB="$HOME/.operator/tickets.db"
    if [ -f "$TICKET_DB" ]; then
        rm "$TICKET_DB"
        log_info "Deleted ticket database: $TICKET_DB"
    fi

    # Flush Redis if ratelimiter cluster is running
    if docker exec docker-redis-1 redis-cli PING > /dev/null 2>&1; then
        docker exec docker-redis-1 redis-cli FLUSHALL > /dev/null
        log_info "Flushed Redis"
    fi

    log_info "Demo state reset complete"
}

check_ports() {
    local subject=$1
    local conflicts=0

    if [[ "$subject" == "tikv" || -z "$subject" ]]; then
        # TiKV ports: 2379 (PD), 9090 (Prometheus), 3000 (Grafana)
        for port in 2379 9090 3000; do
            if lsof -i :$port > /dev/null 2>&1; then
                local proc=$(lsof -i :$port | tail -1 | awk '{print $1}')
                log_warn "Port $port in use by $proc"
                conflicts=1
            fi
        done
    fi

    if [[ "$subject" == "ratelimiter" || -z "$subject" ]]; then
        # Ratelimiter ports: 6379 (Redis), 8001 (API)
        for port in 6379 8001; do
            if lsof -i :$port > /dev/null 2>&1; then
                local proc=$(lsof -i :$port | tail -1 | awk '{print $1}')
                log_warn "Port $port in use by $proc"
                conflicts=1
            fi
        done
    fi

    return $conflicts
}

start_tikv() {
    log_info "Starting TiKV cluster..."

    # Check if prometheus/grafana ports are in use
    if lsof -i :9090 > /dev/null 2>&1; then
        log_warn "Port 9090 in use, starting without prometheus/grafana"
        docker compose -f "$TIKV_COMPOSE" up -d pd0 pd1 pd2 tikv0 tikv1 tikv2
    else
        docker compose -f "$TIKV_COMPOSE" up -d
    fi

    log_info "Waiting for cluster to be healthy..."
    sleep 5

    # Check PD health
    for i in {1..10}; do
        if curl -s http://localhost:2379/pd/api/v1/members > /dev/null 2>&1; then
            local members=$(curl -s http://localhost:2379/pd/api/v1/members | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('members',[])))" 2>/dev/null || echo "0")
            log_info "TiKV cluster ready with $members PD members"
            return 0
        fi
        sleep 2
    done

    log_error "TiKV cluster failed to start"
    return 1
}

start_ratelimiter() {
    log_info "Starting rate limiter cluster (without loadgen)..."
    # Start only the core services, exclude loadgen which floods with counters
    docker compose -f "$RATELIMITER_COMPOSE" up -d redis ratelimiter-1 ratelimiter-2 ratelimiter-3 prometheus

    log_info "Waiting for services..."
    sleep 3

    # Check API health
    for i in {1..10}; do
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            log_info "Rate limiter cluster ready"
            return 0
        fi
        sleep 2
    done

    log_error "Rate limiter failed to start"
    return 1
}

stop_tikv() {
    log_info "Stopping TiKV cluster..."
    docker compose -f "$TIKV_COMPOSE" down -v 2>/dev/null || true
    log_info "TiKV cluster stopped"
}

stop_ratelimiter() {
    log_info "Stopping rate limiter cluster..."
    # Stop loadgen first if running (it floods counters)
    docker compose -f "$RATELIMITER_COMPOSE" stop loadgen 2>/dev/null || true
    # Flush Redis to clear stale counters
    docker exec docker-redis-1 redis-cli FLUSHALL 2>/dev/null || true
    docker compose -f "$RATELIMITER_COMPOSE" down -v 2>/dev/null || true
    log_info "Rate limiter cluster stopped"
}

rebuild_ratelimiter() {
    log_info "Rebuilding rate limiter images..."
    docker compose -f "$RATELIMITER_COMPOSE" build
    log_info "Rebuild complete"
}

rebuild_tikv() {
    log_info "Rebuilding TiKV images..."
    docker compose -f "$TIKV_COMPOSE" build
    log_info "Rebuild complete"
}

show_status() {
    echo ""
    echo "=== TiKV Cluster ==="
    if curl -s http://localhost:2379/pd/api/v1/members > /dev/null 2>&1; then
        echo -e "${GREEN}Running${NC}"
        docker compose -f "$TIKV_COMPOSE" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null | head -10
    else
        echo -e "${RED}Not running${NC}"
    fi

    echo ""
    echo "=== Rate Limiter Cluster ==="
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo -e "${GREEN}Running${NC}"
        docker compose -f "$RATELIMITER_COMPOSE" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null | head -10
    else
        echo -e "${RED}Not running${NC}"
    fi
    echo ""
}

run_demo() {
    local subject=$1
    local skip_reset=$2

    case "$subject" in
        tikv)
            if [[ "$skip_reset" != "--quick" ]]; then
                log_info "Tearing down all clusters..."
                stop_tikv
                stop_ratelimiter
                echo ""
                start_tikv
            else
                log_info "Quick mode: skipping cluster reset"
            fi
            cd "$PROJECT_DIR" && uv run python -m demo tikv
            ;;
        ratelimiter)
            if [[ "$skip_reset" != "--quick" ]]; then
                log_info "Tearing down all clusters..."
                stop_tikv
                stop_ratelimiter
                echo ""
                start_ratelimiter
            else
                log_info "Quick mode: skipping cluster reset"
            fi
            cd "$PROJECT_DIR" && uv run python -m demo ratelimiter
            ;;
        *)
            log_error "Unknown subject: $subject"
            exit 1
            ;;
    esac
}

# Main
case "${1:-help}" in
    start)
        case "$2" in
            tikv) start_tikv ;;
            ratelimiter) start_ratelimiter ;;
            *) log_error "Usage: $0 start <tikv|ratelimiter>"; exit 1 ;;
        esac
        ;;
    stop)
        case "$2" in
            tikv) stop_tikv ;;
            ratelimiter) stop_ratelimiter ;;
            all) stop_tikv; stop_ratelimiter ;;
            *) log_error "Usage: $0 stop <tikv|ratelimiter|all>"; exit 1 ;;
        esac
        ;;
    reset)
        case "$2" in
            tikv) stop_tikv && start_tikv ;;
            ratelimiter) stop_ratelimiter && start_ratelimiter ;;
            *) log_error "Usage: $0 reset <tikv|ratelimiter>"; exit 1 ;;
        esac
        ;;
    rebuild)
        case "$2" in
            tikv) rebuild_tikv ;;
            ratelimiter) rebuild_ratelimiter ;;
            all) rebuild_tikv; rebuild_ratelimiter ;;
            *) log_error "Usage: $0 rebuild <tikv|ratelimiter|all>"; exit 1 ;;
        esac
        ;;
    status)
        show_status
        ;;
    run)
        run_demo "$2" "$3"
        ;;
    ports)
        check_ports "$2"
        if [[ $? -eq 0 ]]; then
            log_info "No port conflicts detected"
        fi
        ;;
    reset-state)
        reset_demo_state
        ;;
    help|*)
        echo "Demo management script for Operator"
        echo ""
        echo "Usage: $0 <command> [subject] [options]"
        echo ""
        echo "Commands:"
        echo "  run <tikv|ratelimiter> [--quick]  - Run demo (--quick skips cluster reset)"
        echo "  start <tikv|ratelimiter>          - Start cluster only"
        echo "  stop <tikv|ratelimiter|all>       - Stop cluster"
        echo "  reset <tikv|ratelimiter>          - Stop and restart cluster"
        echo "  rebuild <tikv|ratelimiter|all>    - Rebuild Docker images"
        echo "  reset-state                       - Kill agent/monitor, reset ticket DB, flush Redis"
        echo "  status                            - Show cluster status"
        echo "  ports [subject]                   - Check port conflicts"
        echo ""
        echo "Examples:"
        echo "  $0 run tikv               # Clean start: teardown, start cluster, run demo"
        echo "  $0 run tikv --quick       # Quick start: just run demo (cluster must be running)"
        echo "  $0 run ratelimiter        # Clean start rate limiter demo"
        echo "  $0 rebuild ratelimiter    # Rebuild ratelimiter images after code changes"
        echo "  $0 stop all               # Stop all clusters"
        echo "  $0 reset-state            # Reset demo state (kill processes, clear DB)"
        ;;
esac
