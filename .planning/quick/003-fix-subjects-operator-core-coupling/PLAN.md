# Plan: Fix subjects → operator-core Type Coupling

## Problem

The `tikv_observer` subject imports types from `operator_core.types` instead of proper sources. Additionally, `operator_core` contains dead TiKV-specific code that was superseded by the generic `operator_protocols.SubjectProtocol`.

## Discovery

**Two Subject definitions exist:**
| Package | Protocol | Status |
|---------|----------|--------|
| `operator_protocols.SubjectProtocol` | Generic `observe() -> dict` | ✓ Used by all subjects |
| `operator_core.Subject` | TiKV-specific `get_hot_write_regions() -> list[Region]` | ✗ Dead code, unused |

**Dead code in operator_core:**
- `subject.py` - TiKV-specific Subject protocol (nobody imports it)
- `types.py` - `Region`, `RegionId` (only used by dead Subject)

## Plan

### Step 1: Create tikv_observer/types.py additions

Add `Region` and `RegionId` to existing `tikv_observer/types.py`:

```python
# Add to subjects/tikv/observer/src/tikv_observer/types.py

from operator_protocols.types import StoreId

# TiKV-specific types
RegionId = int
"""Unique identifier for a TiKV region (key range)."""


@dataclass
class Region:
    """Represents a TiKV region (key range)."""
    id: RegionId
    leader_store_id: StoreId
    peer_store_ids: list[StoreId]
```

### Step 2: Update tikv_observer imports

**pd_client.py:**
```python
# Before
from operator_core.types import Region, RegionId, Store

# After
from operator_protocols.types import Store
from tikv_observer.types import Region, RegionId
```

**prom_client.py:**
```python
# Before
from operator_core.types import StoreId, StoreMetrics

# After
from operator_protocols.types import StoreId, StoreMetrics
```

**subject.py:**
```python
# Before
from operator_core.types import Region

# After
from tikv_observer.types import Region
```

### Step 3: Update tikv_observer tests

**test_pd_client.py:**
```python
# Before
from operator_core.types import Store, Region

# After
from operator_protocols.types import Store
from tikv_observer.types import Region
```

**test_prom_client.py:**
```python
# Before
from operator_core.types import StoreMetrics

# After
from operator_protocols.types import StoreMetrics
```

### Step 4: Update tikv_observer exports

In `__init__.py`, export the new types:
```python
from tikv_observer.types import Region, RegionId
```

### Step 5: Delete dead code from operator_core

**Delete `operator_core/subject.py`** - unused TiKV-specific protocol

**Simplify `operator_core/types.py`:**
```python
"""Re-exports generic types from operator_protocols."""

from operator_protocols.types import Store, StoreId, StoreMetrics, ClusterMetrics

__all__ = ["Store", "StoreId", "StoreMetrics", "ClusterMetrics"]
```

**Update `operator_core/__init__.py`:**
- Remove `Subject` import and export
- Remove `Region`, `RegionId` exports

### Step 6: Remove operator-core dependency from tikv_observer

**Update `subjects/tikv/observer/pyproject.toml`:**
```toml
dependencies = [
    "operator-protocols",  # Keep
    "httpx>=0.27.0",       # Keep
    # Remove: "operator-core"
]
```

## Verification

```bash
# 1. No operator_core imports in subjects
grep -r "from operator_core" subjects/ --include="*.py"
# Should return empty

# 2. tikv_observer imports work
python -c "from tikv_observer import Region, RegionId"
python -c "from tikv_observer.types import Region"

# 3. operator_protocols imports work
python -c "from operator_protocols.types import Store, StoreMetrics"

# 4. Run tests
pytest subjects/tikv/observer/tests/
```

## Result

**Before:**
```
subjects/tikv ──→ operator_core ──→ operator_protocols
                       │
                       └── dead Subject protocol
                       └── TiKV-specific Region type
```

**After:**
```
subjects/tikv ──→ operator_protocols (generic types)
              └─→ tikv_observer.types (TiKV-specific types)

operator_core: no TiKV-specific code, no dead protocols
```

## Line Impact

| File | Change |
|------|--------|
| `operator_core/subject.py` | DELETE (103 lines) |
| `operator_core/types.py` | Simplify (68 → ~10 lines) |
| `operator_core/__init__.py` | Remove exports |
| `tikv_observer/types.py` | Add Region, RegionId (~20 lines) |
| 5 tikv_observer files | Update imports |

**Net reduction in operator-core:** ~160 lines of dead/misplaced code
