# Quick Task 003: True Parallel Campaign Execution

**Status:** Complete

## Problem

The `parallel` config in campaign YAML was misleading - all trials fought over the same TiKV cluster because:
- docker-compose.yaml had hardcoded container names
- All containers used the same host ports (2379, 20160, etc.)
- TiKVEvalSubject had hardcoded `pd_endpoint = "http://localhost:2379"`
- The semaphore limited concurrency but trials still shared infrastructure

## Solution

Implemented true parallel execution with isolated clusters per parallel slot:

### 1. Docker Compose Parameterization (`subjects/tikv/docker-compose.yaml`)

- Removed all `container_name:` directives (Compose auto-namespaces with project)
- Added port environment variables with defaults:
  - `${PD_HOST_PORT:-2379}`
  - `${TIKV_HOST_PORT:-20160}`
  - `${TIKV_STATUS_HOST_PORT:-20180}`
  - `${PROM_HOST_PORT:-9090}`
  - `${GRAFANA_HOST_PORT:-3000}`

### 2. Instance-Aware Subject (`eval/src/eval/subjects/tikv/subject.py`)

- Added `instance_id` parameter to constructor
- Port allocation: `base_port + instance_id * 10000`
  - Instance 0: ports 2379, 20160, 20180, 9090, 3000
  - Instance 1: ports 12379, 30160, 30180, 19090, 13000
  - Instance 2: ports 22379, 40160, 40180, 29090, 23000
- Project name: `tikv-eval-{instance_id}` (or `tikv` for instance 0)
- Environment variables passed to DockerClient for port substitution
- Dynamic `pd_endpoint` using instance-specific port

### 3. Subject Pool (`eval/src/eval/runner/harness.py`)

- New `SubjectPool` class manages N isolated subject instances
- `acquire()`: Get available instance from pool (async, blocks if none available)
- `release()`: Return instance to pool when trial completes
- `shutdown()`: Clean up all Docker Compose projects
- Pool replaces semaphore pattern - parallelism controlled by pool size

## Files Modified

- `subjects/tikv/docker-compose.yaml` - Parameterized ports, removed container names
- `eval/src/eval/subjects/tikv/subject.py` - Added instance_id, port allocation
- `eval/src/eval/runner/harness.py` - Added SubjectPool, updated run_campaign_from_config

## Usage

With `parallel: 3` in campaign config:
- 3 isolated TiKV clusters spin up with different ports
- Trials acquire clusters from pool, run, then release back
- True concurrent execution without resource conflicts

## Port Allocation Table

| Instance | PD | TiKV | TiKV Status | Prometheus | Grafana |
|----------|-----|------|-------------|------------|---------|
| 0 | 2379 | 20160 | 20180 | 9090 | 3000 |
| 1 | 12379 | 30160 | 30180 | 19090 | 13000 |
| 2 | 22379 | 40160 | 40180 | 29090 | 23000 |
| N | +N*10000 | +N*10000 | +N*10000 | +N*10000 | +N*10000 |
