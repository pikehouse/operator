# Phase 16: Core Abstraction Refactoring - Research

**Researched:** 2026-01-26
**Domain:** Python package architecture, Protocol-based abstraction, refactoring
**Confidence:** HIGH

## Summary

This research comprehensively audits the current codebase to identify all TiKV-specific coupling points in operator-core that need to be decoupled. The codebase already has a two-package structure (operator-core and operator-tikv) with a Subject Protocol defined, but there are 12 files in operator-core that still directly import from operator-tikv, breaking the clean abstraction boundary.

The refactoring requires creating two new packages (operator-protocols and operator-helpers), moving shared utilities and protocol definitions, and updating all imports. The current code uses `typing.Protocol` with `@runtime_checkable` which aligns with the codebase's existing patterns and should be retained.

**Primary recommendation:** Execute a big-bang refactor on a feature branch, extracting packages in dependency order (protocols first, then helpers, then update core), with all existing tests passing as the validation gate.

## Current State: TiKV Coupling Audit

### Direct TiKV Imports in operator-core (MUST BE REMOVED)

| File | Import | Coupling Type |
|------|--------|--------------|
| `monitor/loop.py` | `from operator_tikv.invariants import InvariantChecker, InvariantViolation` | Type + class import |
| `monitor/loop.py` | `from operator_tikv.subject import TiKVSubject` | Concrete type annotation |
| `monitor/types.py` | `from operator_tikv.invariants import InvariantViolation` | Type import for `make_violation_key()` |
| `db/tickets.py` | `from operator_tikv.invariants import InvariantViolation` | Type annotation in method signature |
| `cli/monitor.py` | `from operator_tikv.invariants import InvariantChecker` | Class instantiation |
| `cli/monitor.py` | `from operator_tikv.pd_client import PDClient` | Class instantiation |
| `cli/monitor.py` | `from operator_tikv.prom_client import PrometheusClient` | Class instantiation |
| `cli/monitor.py` | `from operator_tikv.subject import TiKVSubject` | Class instantiation |
| `cli/agent.py` | `from operator_tikv.pd_client import PDClient` | Class instantiation |
| `cli/agent.py` | `from operator_tikv.prom_client import PrometheusClient` | Class instantiation |
| `cli/agent.py` | `from operator_tikv.subject import TiKVSubject` | Class instantiation |
| `agent/runner.py` | `from operator_tikv.subject import TiKVSubject` | Type annotation |
| `agent/context.py` | `from operator_tikv.subject import TiKVSubject` | Type annotation (TYPE_CHECKING) |
| `demo/chaos.py` | `from operator_tikv.invariants import InvariantChecker` | Class instantiation |
| `demo/chaos.py` | `from operator_tikv.pd_client import PDClient` | Class instantiation |
| `demo/chaos.py` | `from operator_tikv.prom_client import PrometheusClient` | Class instantiation |
| `demo/chaos.py` | `from operator_tikv.subject import TiKVSubject` | Class instantiation |

### TiKV-Specific Types Currently in operator-core/types.py

These types are TiKV-specific and need to either:
1. Become generic (for protocols package), OR
2. Move to operator-tikv (if TiKV-specific)

| Type | Current Location | Decision |
|------|-----------------|----------|
| `Store` | operator_core.types | **Keep generic** - has id, address, state (applies to any distributed system) |
| `Region` | operator_core.types | **Move to tikv** - TiKV-specific concept (leader_store_id, peer_store_ids) |
| `StoreMetrics` | operator_core.types | **Keep generic** - qps, latency, disk, cpu are universal |
| `ClusterMetrics` | operator_core.types | **Keep generic** - store_count, region_count, leader_count are universal |
| `StoreId` (type alias) | operator_core.types | **Keep generic** - just `str` alias |
| `RegionId` (type alias) | operator_core.types | **Move to tikv** - TiKV-specific |

### Current Subject Protocol (operator_core/subject.py)

The current Subject Protocol is **heavily TiKV-specific**:

```python
@runtime_checkable
class Subject(Protocol):
    # Observations - return TiKV types
    async def get_stores(self) -> list[Store]: ...
    async def get_hot_write_regions(self) -> list[Region]: ...  # TiKV-specific
    async def get_store_metrics(self, store_id: str) -> StoreMetrics: ...
    async def get_cluster_metrics(self) -> ClusterMetrics: ...

    # Actions - TiKV-specific operations
    async def transfer_leader(self, region_id: int, to_store_id: str) -> None: ...
    async def split_region(self, region_id: int) -> None: ...
    async def set_leader_schedule_limit(self, n: int) -> None: ...
    async def set_replica_schedule_limit(self, n: int) -> None: ...
    async def drain_store(self, store_id: str) -> None: ...
    async def set_low_space_threshold(self, percent: float) -> None: ...
    async def set_region_schedule_limit(self, n: int) -> None: ...

    # Action discovery
    def get_action_definitions(self) -> list[ActionDefinition]: ...
```

**Problem:** This Protocol cannot support non-TiKV subjects.

### Current InvariantViolation Type (operator_tikv/invariants.py)

```python
@dataclass
class InvariantViolation:
    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    store_id: str | None = None
    severity: str = "warning"
```

**This is generic enough** - should move to protocols package.

## Standard Stack

### Existing Patterns to Follow

| Pattern | Used In | Description |
|---------|---------|-------------|
| `typing.Protocol` with `@runtime_checkable` | `operator_core/subject.py` | Structural subtyping for interfaces |
| Dataclasses for data types | `operator_core/types.py` | Simple, immutable data containers |
| Pydantic BaseModel | `operator_tikv/types.py` | API response parsing, validation |
| Type aliases | `operator_core/types.py` | `StoreId = str`, `RegionId = int` |
| Async context managers | `operator_core/db/tickets.py` | Resource lifecycle management |
| `TYPE_CHECKING` imports | `operator_core/agent/context.py` | Avoid circular imports |

### Python Version

- Requires Python >= 3.11 (per pyproject.toml)
- Can use `dict[str, Any]` not `Dict[str, Any]`
- Can use `list[X]` not `List[X]`
- Can use `X | None` not `Optional[X]`

### Build System

- Uses Hatchling (`hatchling.build`)
- Uses UV workspace (`tool.uv.workspace`)
- Source layout: `packages/*/src/*/`

## Architecture Patterns

### Target Package Structure

```
packages/
  operator-protocols/           # NEW: Protocol definitions + base types
    pyproject.toml
    src/operator_protocols/
      __init__.py
      subject.py                # GenericSubject Protocol
      invariant.py              # InvariantCheckerProtocol, InvariantViolation
      types.py                  # Generic types: Store, StoreMetrics, ClusterMetrics

  operator-helpers/             # NEW: Generic utilities (deferred - may not be needed)
    pyproject.toml
    src/operator_helpers/
      __init__.py
      # Future: prometheus.py, http.py, log_reader.py

  operator-core/                # REFACTOR: Subject-agnostic orchestration
    pyproject.toml              # depends on: operator-protocols
    src/operator_core/
      __init__.py
      cli/
        main.py                 # Add --subject flag
        monitor.py              # Generic, delegates to subject factory
        agent.py                # Generic, delegates to subject factory
        ...
      monitor/
        loop.py                 # Generic MonitorLoop[T]
        types.py                # Ticket types (no TiKV imports)
      agent/
        runner.py               # Generic AgentRunner
        context.py              # Generic ContextGatherer
      db/                       # Unchanged (already generic)
      actions/                  # Unchanged (already generic)

  operator-tikv/                # REFACTOR: TiKV-specific implementation
    pyproject.toml              # depends on: operator-core, operator-protocols
    src/operator_tikv/
      __init__.py
      subject.py                # TiKVSubject implements GenericSubject
      invariants.py             # TiKVInvariantChecker implements InvariantCheckerProtocol
      types.py                  # TiKV API types (unchanged)
      pd_client.py              # TiKV-specific (unchanged)
      prom_client.py            # TiKV-specific (unchanged)
      factory.py                # NEW: Factory function for CLI
```

### New Package Dependencies

```
operator-protocols (no dependencies, base package)
    ^
    |
operator-core (depends on: operator-protocols)
    ^
    |
operator-tikv (depends on: operator-core, operator-protocols)
```

### Generic Subject Protocol Design

Per CONTEXT.md decisions:
- Observation type: `dict[str, Any]` for maximum flexibility
- Action type: Protocol-based (anything with `execute()`)

```python
# operator_protocols/subject.py
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class SubjectProtocol(Protocol):
    """Generic interface for monitored systems."""

    # Observations return flexible dict (subject defines schema)
    async def observe(self) -> dict[str, Any]:
        """Gather current state observations."""
        ...

    # Action discovery for AI agent
    def get_action_definitions(self) -> list["ActionDefinition"]:
        """Return available actions for this subject."""
        ...
```

### Generic Invariant Checker Protocol Design

```python
# operator_protocols/invariant.py
from typing import Any, Protocol, runtime_checkable

@dataclass
class InvariantViolation:
    """Generic violation - works for any subject."""
    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    entity_id: str | None = None  # Was store_id, now generic
    severity: str = "warning"

@runtime_checkable
class InvariantCheckerProtocol(Protocol):
    """Interface for checking invariants on observations."""

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """Check invariants against observation, return violations."""
        ...
```

### CLI Subject Selection Pattern

Per CONTEXT.md: Hardcoded switch, `--subject` required flag.

```python
# operator_core/cli/main.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from operator_protocols.subject import SubjectProtocol

def get_subject(subject_name: str, **kwargs) -> "SubjectProtocol":
    """Factory function for subject creation."""
    if subject_name == "tikv":
        from operator_tikv.factory import create_tikv_subject
        return create_tikv_subject(**kwargs)
    # Future: elif subject_name == "ratelimiter": ...
    else:
        available = ["tikv"]  # Hardcoded list
        raise ValueError(f"Unknown subject '{subject_name}'. Available: {available}")

# CLI commands add --subject flag
@app.command()
def monitor(
    subject: str = typer.Option(..., "--subject", "-s", help="Subject to monitor (tikv)")
):
    ...
```

### MonitorLoop Generalization

```python
# operator_core/monitor/loop.py
from operator_protocols.subject import SubjectProtocol
from operator_protocols.invariant import InvariantCheckerProtocol, InvariantViolation

class MonitorLoop:
    def __init__(
        self,
        subject: SubjectProtocol,
        checker: InvariantCheckerProtocol,
        db_path: Path,
        interval_seconds: float = 30.0,
    ) -> None:
        self.subject = subject
        self.checker = checker
        # ...

    async def _check_cycle(self, db: TicketDB) -> None:
        # Generic observation
        observation = await self.subject.observe()

        # Generic invariant checking
        violations = self.checker.check(observation)

        # ... rest unchanged
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Interface definition | Custom ABC class | `typing.Protocol` | Already used in codebase, enables structural subtyping |
| Package management | Manual sys.path | UV workspace | Already configured, handles inter-package deps |
| Type checking at runtime | isinstance() with ABC | `@runtime_checkable` Protocol | Already used, more Pythonic |

## Common Pitfalls

### Pitfall 1: Circular Import Trap

**What goes wrong:** New packages import each other, causing ImportError at startup
**Why it happens:** Protocol definitions reference types from multiple packages
**How to avoid:**
- operator-protocols must have ZERO dependencies on other operator-* packages
- Use `TYPE_CHECKING` guards for type annotations
- Import concrete classes only where instantiated (CLI, factory functions)
**Warning signs:** ImportError mentioning circular import

### Pitfall 2: Breaking Existing TiKV Tests

**What goes wrong:** TiKV tests fail because they import from old locations
**Why it happens:** Types moved to operator-protocols but tests not updated
**How to avoid:**
- Run full test suite after each refactoring step
- Update imports in test files along with source files
- Keep operator_core exports for backward compatibility initially
**Warning signs:** ImportError in test files

### Pitfall 3: Subject Protocol Too Generic

**What goes wrong:** `dict[str, Any]` loses type safety, AI diagnosis degrades
**Why it happens:** Over-generalizing removes useful structure
**How to avoid:**
- Define well-documented observation schemas per subject
- Add runtime validation in subject implementations
- Include example observations in docstrings
**Warning signs:** AI diagnosis quality drops, unclear what observations contain

### Pitfall 4: Forgetting TYPE_CHECKING Guards

**What goes wrong:** Import cycles even with careful dependency ordering
**Why it happens:** Type annotations cause imports to execute at runtime
**How to avoid:**
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from operator_protocols.subject import SubjectProtocol

def my_func(subject: "SubjectProtocol") -> None:  # String annotation
    ...
```
**Warning signs:** ImportError on startup, not just type checking

### Pitfall 5: InvariantViolation.store_id Breaking Change

**What goes wrong:** Existing code expects `store_id`, new protocol uses `entity_id`
**Why it happens:** Renaming for genericity breaks TiKV-specific code
**How to avoid:**
- Option A: Keep as `store_id` (TiKV-centric but compatible)
- Option B: Use `entity_id` but alias `store_id` in TiKV code
- Option C: Keep both, make `entity_id` the generic name with `store_id` as alias
**Recommendation:** Keep `store_id` name for now, rename later if needed

## Migration Approach

### Phase 1: Create operator-protocols Package

1. Create `packages/operator-protocols/` directory structure
2. Add `pyproject.toml` (no dependencies)
3. Move/create:
   - `InvariantViolation` dataclass
   - `InvariantCheckerProtocol`
   - Generic `SubjectProtocol`
   - Generic types (`Store`, `StoreMetrics`, `ClusterMetrics`)
4. **Test:** Package imports without errors

### Phase 2: Update operator-tikv to Use Protocols

1. Update `pyproject.toml` to depend on `operator-protocols`
2. Update imports in `invariants.py`:
   - Import `InvariantViolation` from `operator_protocols`
   - Create `TiKVInvariantChecker` class implementing `InvariantCheckerProtocol`
3. Update imports in `subject.py`:
   - Import types from `operator_protocols`
   - Ensure `TiKVSubject` implements `SubjectProtocol`
4. Add `factory.py` with `create_tikv_subject()` function
5. **Test:** All operator-tikv tests pass

### Phase 3: Update operator-core to Use Protocols

1. Update `pyproject.toml` to depend on `operator-protocols`
2. Remove all `from operator_tikv` imports
3. Update `monitor/loop.py`:
   - Import from `operator_protocols`
   - Change type annotations to Protocol types
4. Update `monitor/types.py`:
   - Import `InvariantViolation` from `operator_protocols`
5. Update `db/tickets.py`:
   - Import `InvariantViolation` from `operator_protocols`
6. Update CLI commands:
   - Add `--subject` flag (required)
   - Use factory function pattern
7. Update agent components:
   - Use Protocol type annotations
8. **Test:** All tests pass (run from workspace root)

### Phase 4: Add Protocol Compliance Tests

1. Create test that verifies `TiKVSubject` implements `SubjectProtocol`
2. Create test that verifies `TiKVInvariantChecker` implements `InvariantCheckerProtocol`
3. Use `isinstance()` with `@runtime_checkable` protocols

```python
def test_tikv_subject_implements_protocol():
    from operator_protocols.subject import SubjectProtocol
    from operator_tikv.subject import TiKVSubject

    # Create minimal instance
    subject = TiKVSubject(pd=mock_pd, prom=mock_prom)

    assert isinstance(subject, SubjectProtocol)
```

### Testing Strategy

| Test Suite | Run After | Validates |
|------------|-----------|-----------|
| `pytest packages/operator-protocols/` | Phase 1 | Protocol definitions importable |
| `pytest packages/operator-tikv/` | Phase 2 | TiKV still works with new imports |
| `pytest packages/operator-core/` | Phase 3 | Core no longer depends on TiKV |
| `pytest packages/` (all) | Phase 4 | Full integration |

### Rollback Plan

Since this is a big-bang refactor on a feature branch:
1. If any phase fails, fix issues before proceeding
2. If unfixable, `git checkout main` and discard branch
3. Only merge when all tests pass on feature branch

## Code Examples

### Generic Subject Implementation Pattern

```python
# operator_protocols/subject.py
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class SubjectProtocol(Protocol):
    """
    Interface for monitored distributed systems.

    Subjects provide observations (system state) and actions (operations).
    Observations are flexible dicts; each subject defines its own schema.

    Example observation from TiKV subject:
        {
            "stores": [{"id": "1", "address": "tikv-0:20160", "state": "Up"}, ...],
            "cluster_metrics": {"store_count": 3, "region_count": 100, ...},
            "store_metrics": {"1": {"qps": 1000, "latency_p99_ms": 25}, ...}
        }
    """

    async def observe(self) -> dict[str, Any]:
        """Gather current system state observations."""
        ...

    def get_action_definitions(self) -> list["ActionDefinition"]:
        """Return available actions for AI agent."""
        ...
```

### TiKV Subject Adapting to Protocol

```python
# operator_tikv/subject.py
from operator_protocols.subject import SubjectProtocol
from operator_protocols.types import Store, StoreMetrics, ClusterMetrics

class TiKVSubject:
    """TiKV implementation of SubjectProtocol."""

    pd: PDClient
    prom: PrometheusClient

    async def observe(self) -> dict[str, Any]:
        """Gather TiKV cluster observations."""
        stores = await self.pd.get_stores()
        cluster_metrics = await self.get_cluster_metrics()

        # Gather store metrics for each up store
        store_metrics = {}
        for store in stores:
            if store.state == "Up":
                try:
                    metrics = await self.get_store_metrics(store.id)
                    store_metrics[store.id] = {
                        "qps": metrics.qps,
                        "latency_p99_ms": metrics.latency_p99_ms,
                        "disk_used_bytes": metrics.disk_used_bytes,
                        "disk_total_bytes": metrics.disk_total_bytes,
                        "cpu_percent": metrics.cpu_percent,
                    }
                except Exception:
                    pass  # Skip failed metrics

        return {
            "stores": [{"id": s.id, "address": s.address, "state": s.state} for s in stores],
            "cluster_metrics": {
                "store_count": cluster_metrics.store_count,
                "region_count": cluster_metrics.region_count,
                "leader_count": cluster_metrics.leader_count,
            },
            "store_metrics": store_metrics,
        }

    # ... existing action methods unchanged
```

### Generic InvariantChecker Adapting to Protocol

```python
# operator_tikv/invariants.py
from operator_protocols.invariant import InvariantCheckerProtocol, InvariantViolation

class TiKVInvariantChecker:
    """TiKV-specific invariant checker implementing InvariantCheckerProtocol."""

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """Check TiKV-specific invariants against observation."""
        violations = []

        # Check store health
        stores = observation.get("stores", [])
        for store_data in stores:
            store = Store(
                id=store_data["id"],
                address=store_data["address"],
                state=store_data["state"],
            )
            violations.extend(self.check_stores_up([store]))

        # Check metrics for up stores
        store_metrics = observation.get("store_metrics", {})
        for store_id, metrics_data in store_metrics.items():
            metrics = StoreMetrics(
                store_id=store_id,
                qps=metrics_data.get("qps", 0),
                latency_p99_ms=metrics_data.get("latency_p99_ms", 0),
                disk_used_bytes=metrics_data.get("disk_used_bytes", 0),
                disk_total_bytes=metrics_data.get("disk_total_bytes", 1),
                cpu_percent=metrics_data.get("cpu_percent", 0),
                raft_lag=0,
            )
            if v := self.check_latency(metrics):
                violations.append(v)
            if v := self.check_disk_space(metrics):
                violations.append(v)

        return violations

    # ... existing check_stores_up, check_latency, check_disk_space unchanged
```

### CLI Factory Pattern

```python
# operator_core/cli/subject_factory.py
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from operator_protocols.subject import SubjectProtocol
    from operator_protocols.invariant import InvariantCheckerProtocol

AVAILABLE_SUBJECTS = ["tikv"]

def create_subject(
    subject_name: str,
    **kwargs: Any
) -> tuple["SubjectProtocol", "InvariantCheckerProtocol"]:
    """
    Factory function to create subject and checker instances.

    Args:
        subject_name: Subject identifier (e.g., "tikv")
        **kwargs: Subject-specific configuration

    Returns:
        Tuple of (subject, checker) instances

    Raises:
        ValueError: If subject_name is not recognized
    """
    if subject_name == "tikv":
        # Import only when needed
        from operator_tikv.factory import create_tikv_subject_and_checker
        return create_tikv_subject_and_checker(**kwargs)
    else:
        raise ValueError(
            f"Unknown subject '{subject_name}'. "
            f"Available subjects: {AVAILABLE_SUBJECTS}"
        )

# operator_tikv/factory.py
import httpx
from operator_tikv.subject import TiKVSubject
from operator_tikv.invariants import TiKVInvariantChecker
from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient

async def create_tikv_subject_and_checker(
    pd_endpoint: str,
    prometheus_url: str,
    pd_http: httpx.AsyncClient | None = None,
    prom_http: httpx.AsyncClient | None = None,
) -> tuple[TiKVSubject, TiKVInvariantChecker]:
    """Create TiKV subject and checker with optional pre-configured clients."""
    if pd_http is None:
        pd_http = httpx.AsyncClient(base_url=pd_endpoint, timeout=10.0)
    if prom_http is None:
        prom_http = httpx.AsyncClient(base_url=prometheus_url, timeout=10.0)

    subject = TiKVSubject(
        pd=PDClient(http=pd_http),
        prom=PrometheusClient(http=prom_http),
    )
    checker = TiKVInvariantChecker()

    return subject, checker
```

## Open Questions

### Question 1: operator-helpers Package Timing

**What we know:** CONTEXT.md mentions operator-helpers for Prometheus/HTTP helpers
**What's unclear:** Are there actually shared utilities that need extraction now?
**Recommendation:** Defer operator-helpers creation. Current PrometheusClient is TiKV-specific (uses TiKV metric names). Create operator-helpers only when a second subject needs shared utilities.

### Question 2: Region Type Migration

**What we know:** `Region` type is TiKV-specific (leader_store_id, peer_store_ids)
**What's unclear:** Should it stay in operator-core for now or move immediately?
**Recommendation:** Move to operator-tikv immediately. It's only used by TiKV code and the generic observation dict pattern means other subjects won't need it.

### Question 3: Backward Compatibility Re-exports

**What we know:** External code may import from operator_core.types
**What's unclear:** Is there external code? How long to maintain re-exports?
**Recommendation:** Keep re-exports in operator_core.__init__.py initially, deprecation warnings can be added later if needed.

## Sources

### Primary (HIGH confidence)
- `/Users/jrtipton/x/operator/packages/operator-core/` - Full source audit
- `/Users/jrtipton/x/operator/packages/operator-tikv/` - Full source audit
- `/Users/jrtipton/x/operator/.planning/phases/16-core-abstraction-refactoring/16-CONTEXT.md` - Implementation decisions

### Files Examined

**operator-core (12 files with TiKV coupling):**
- `src/operator_core/subject.py` - Subject Protocol definition
- `src/operator_core/types.py` - Core data types
- `src/operator_core/monitor/loop.py` - MonitorLoop with TiKV imports
- `src/operator_core/monitor/types.py` - Ticket types with TiKV import
- `src/operator_core/db/tickets.py` - TicketDB with TiKV import
- `src/operator_core/cli/main.py` - CLI entry point
- `src/operator_core/cli/monitor.py` - Monitor CLI with TiKV imports
- `src/operator_core/cli/agent.py` - Agent CLI with TiKV imports
- `src/operator_core/agent/runner.py` - AgentRunner with TiKV import
- `src/operator_core/agent/context.py` - ContextGatherer with TiKV import
- `src/operator_core/demo/chaos.py` - Demo with TiKV imports
- `src/operator_core/__init__.py` - Package exports

**operator-tikv:**
- `src/operator_tikv/subject.py` - TiKVSubject implementation
- `src/operator_tikv/invariants.py` - InvariantChecker implementation
- `src/operator_tikv/types.py` - Pydantic response types
- `src/operator_tikv/pd_client.py` - PD API client
- `src/operator_tikv/prom_client.py` - Prometheus client
- `src/operator_tikv/log_parser.py` - Log parsing utilities
- `tests/test_invariants.py` - Invariant tests

**Configuration:**
- `pyproject.toml` - Root workspace config
- `packages/operator-core/pyproject.toml` - Core package config
- `packages/operator-tikv/pyproject.toml` - TiKV package config

## Metadata

**Confidence breakdown:**
- Current state audit: HIGH - All files read and coupling points identified
- Package structure: HIGH - Based on CONTEXT.md decisions and existing patterns
- Migration approach: HIGH - Standard refactoring patterns
- CLI patterns: MEDIUM - Factory pattern is standard but implementation details need testing

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - stable refactoring patterns)
