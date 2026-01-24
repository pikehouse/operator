# Phase 2 Plan 05: TiKV Subject Summary

**Completed:** 2026-01-24
**Duration:** ~15 minutes

## One-liner

TiKV invariants (store down, high latency, low disk) with grace periods plus TiKVSubject implementation wiring PDClient and PrometheusClient.

## What was built

### TiKV Invariants Module (`invariants.py`)

Complete invariant checking system:

- **InvariantChecker class** - Tracks violations with grace period support
- **Store down invariant** - Immediate detection, critical severity
- **High latency invariant** - 100ms P99 threshold, 60s grace period
- **Low disk space invariant** - 70% threshold, immediate detection

Key features:
- Per-store tracking (independent grace periods)
- Violations clear when conditions resolve
- Configurable thresholds and grace periods
- First-seen time preserved for persistent violations

### TiKVSubject Implementation (`subject.py`)

Complete Subject Protocol implementation:

- **Observations**: All implemented using PDClient and PrometheusClient
  - `get_stores()` - Delegates to PDClient
  - `get_hot_write_regions()` - Returns all regions (filtering deferred)
  - `get_store_metrics()` - Combines PD address lookup + Prometheus metrics
  - `get_cluster_metrics()` - Calculates store count, region count, leader distribution

- **Actions**: All raise NotImplementedError (deferred to Phase 5)
  - transfer_leader, split_region
  - set_leader_schedule_limit, set_replica_schedule_limit
  - drain_store, set_low_space_threshold, set_region_schedule_limit

- **Configuration**: TIKV_CONFIG with actions, observations, SLOs
  - SLOs: write_latency_p99 (100ms), disk_usage (70%), store_availability (100%)

### Package Updates

- Updated `__init__.py` to export TiKVSubject, TIKV_CONFIG, and invariant types
- Added dev dependencies (pytest, pytest-asyncio) to workspace pyproject.toml

## Key Files

| File | Purpose |
|------|---------|
| `packages/operator-tikv/src/operator_tikv/invariants.py` | Invariant checking with grace periods |
| `packages/operator-tikv/src/operator_tikv/subject.py` | TiKVSubject implementation |
| `packages/operator-tikv/tests/test_invariants.py` | 24 invariant tests |
| `packages/operator-tikv/src/operator_tikv/__init__.py` | Updated exports |
| `pyproject.toml` | Added dev dependencies |

## Commits

1. `ac8966a` - feat(02-05): add TiKV invariants module (24 tests)
2. `cb6aa34` - feat(02-05): add TiKVSubject implementation
3. `2e3197f` - chore(02-05): add pytest dev dependencies to workspace

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Store down has no grace period | Critical issue, immediate alerting needed |
| High latency has 60s grace period | Allows transient spikes without alerting |
| Low disk has no grace period | Disk issues are urgent, need immediate visibility |
| Actions raise NotImplementedError | Per plan - deferred to Phase 5 |
| get_hot_write_regions returns all regions | Hotspot filtering deferred |

## Verification

```bash
# All tests pass
uv sync --group dev && uv run pytest packages/operator-tikv/tests/ -v
# 60 passed in 0.19s

# Imports work correctly
uv run python -c "
from operator_tikv import TiKVSubject, PDClient, PrometheusClient
print('Config:', TiKVSubject.get_config().name)
print('Observations:', [o.name for o in TiKVSubject.get_config().observations])
"
# Config: tikv
# Observations: ['get_stores', 'get_hot_write_regions', 'get_store_metrics', 'get_cluster_metrics']
```

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

Phase 2 (TiKV Subject) is now complete. Ready for Phase 3 (Local Cluster).

Dependencies delivered:
- TiKVSubject implements Subject Protocol
- All observations available (get_stores, get_store_metrics, get_cluster_metrics, get_hot_write_regions)
- Invariant checking for health monitoring
- Complete test coverage (60 tests)
