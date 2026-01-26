# Phase 13: TiKV Subject Actions - Research

**Researched:** 2026-01-26
**Domain:** TiKV PD API for scheduling operations (transfer-leader, transfer-peer, evict-leader), httpx async HTTP calls
**Confidence:** HIGH

## Summary

This phase implements the action execution layer for TiKV, enabling the Subject to call PD API endpoints for leader transfer, peer transfer, and store drain operations. Research focused on PD API endpoints for scheduling operators and schedulers, the JSON body formats required, and integration patterns with the existing Phase 12 action foundation.

The PD API provides two main approaches for scheduling operations: (1) `POST /pd/api/v1/operators` for immediate region-level operations like transfer-leader and transfer-peer, and (2) `POST /pd/api/v1/schedulers` for persistent scheduling rules like evict-leader-scheduler. The store drain operation is accomplished via the evict-leader-scheduler which moves all leaders away from a store.

Per CONTEXT.md decisions: fire-and-forget execution (return API call success/failure, don't poll for completion), minimal validation (let PD reject invalid requests), and pass-through error handling (return PD error messages directly).

**Primary recommendation:** Implement three actions via existing PDClient httpx instance: `transfer_leader` via POST /operators, `transfer_peer` via POST /operators, and `drain_store` via POST /schedulers with evict-leader-scheduler.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | latest | Async HTTP client for PD API POST requests | Already injected into TiKVSubject via PDClient |
| pydantic | v2 | Response/request validation | Existing pattern in operator-tikv types.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| operator_core.actions.registry | - | ActionDefinition, ParamDef | Define action parameter schemas |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| POST /operators for drain | DELETE /store/{id} | DELETE deletes store permanently; evict-leader-scheduler is reversible |
| Separate scheduler client | Extend PDClient | PDClient already has httpx; keeps subject simple |

**Installation:**
```bash
# No new dependencies - uses existing httpx injected into PDClient
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-tikv/
└── src/
    └── operator_tikv/
        ├── subject.py          # TiKVSubject with action implementations
        ├── pd_client.py        # Extend with POST methods for operators/schedulers
        └── types.py            # Add request types for operator POST bodies
```

### Pattern 1: Action Implementation in Subject
**What:** TiKVSubject methods delegate to PDClient for PD API calls
**When to use:** All action implementations (transfer_leader, transfer_peer, drain_store)
**Example:**
```python
# Source: Phase 12 executor.py pattern - subject methods called via getattr
class TiKVSubject:
    pd: PDClient

    async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
        """
        Transfer region leadership to another store.

        Fire-and-forget: returns on API success, raises on API error.
        Does not wait for actual leader transfer completion.

        Args:
            region_id: The region whose leader should be transferred
            to_store_id: The destination store for leadership

        Raises:
            httpx.HTTPStatusError: On PD API errors (4xx, 5xx)
        """
        await self.pd.add_transfer_leader_operator(region_id, int(to_store_id))
```

### Pattern 2: PDClient Operator Methods
**What:** PDClient methods POST to PD API operator endpoints
**When to use:** All scheduling operations
**Example:**
```python
# Source: PD API docs - POST /pd/api/v1/operators
@dataclass
class PDClient:
    http: httpx.AsyncClient

    async def add_transfer_leader_operator(
        self, region_id: int, to_store_id: int
    ) -> None:
        """
        Add transfer-leader operator via PD API.

        POST /pd/api/v1/operators with:
        {"name": "transfer-leader", "region_id": <id>, "store_id": <id>}

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        response = await self.http.post(
            "/pd/api/v1/operators",
            json={
                "name": "transfer-leader",
                "region_id": region_id,
                "store_id": to_store_id,
            },
        )
        response.raise_for_status()
```

### Pattern 3: Scheduler-Based Actions (Drain Store)
**What:** Use scheduler API for persistent operations like evict-leader
**When to use:** drain_store action (moves all leaders off a store)
**Example:**
```python
# Source: pd-ctl docs - scheduler add evict-leader-scheduler
async def add_evict_leader_scheduler(self, store_id: int) -> None:
    """
    Add evict-leader-scheduler for a store.

    POST /pd/api/v1/schedulers with:
    {"name": "evict-leader-scheduler", "store_id": <id>}

    This is a persistent scheduler - leaders are continuously
    evicted from this store until the scheduler is removed.
    """
    response = await self.http.post(
        "/pd/api/v1/schedulers",
        json={
            "name": "evict-leader-scheduler",
            "store_id": store_id,
        },
    )
    response.raise_for_status()
```

### Pattern 4: ActionDefinition for Registry
**What:** Define action schemas for Phase 12 registry integration
**When to use:** Subject.get_action_definitions() method
**Example:**
```python
# Source: Phase 12 registry.py - ActionDefinition, ParamDef
from operator_core.actions.registry import ActionDefinition, ParamDef

def get_action_definitions(self) -> list[ActionDefinition]:
    return [
        ActionDefinition(
            name="transfer_leader",
            description="Transfer region leadership to another store",
            parameters={
                "region_id": ParamDef(
                    type="int",
                    description="ID of the region to transfer",
                    required=True,
                ),
                "to_store_id": ParamDef(
                    type="str",
                    description="Target store ID for leadership",
                    required=True,
                ),
            },
            risk_level="medium",
            requires_approval=False,
        ),
        # ... other actions
    ]
```

### Anti-Patterns to Avoid
- **Polling for completion:** Per CONTEXT.md, subject returns on API call success - monitor/agent tracks actual completion
- **Pre-validating cluster state:** Let PD reject invalid requests (store doesn't exist, region not on store, etc.)
- **Creating custom error taxonomy:** Pass PD error messages through directly
- **Creating new httpx clients:** Use injected PDClient.http for connection pooling

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Leader eviction from store | Custom loop transferring each leader | evict-leader-scheduler | PD handles scheduling automatically |
| Operator status tracking | Polling GET /operators/{region_id} | Monitor/agent loop | Per CONTEXT.md - separation of concerns |
| Timeout handling | Custom timeout wrapper | httpx timeout parameter | Built into httpx |
| Store validation | Check store exists before POST | Let PD reject | PD is source of truth per CONTEXT.md |

**Key insight:** The PD API handles scheduling complexity. Subject just needs to POST the operator request and let PD schedule it.

## Common Pitfalls

### Pitfall 1: Store ID Type Mismatch
**What goes wrong:** PD API expects integer store_id, but operator-core uses string StoreId
**Why it happens:** Store IDs are strings throughout operator-core for Prometheus label compatibility
**How to avoid:** Convert to int when calling PD API: `int(to_store_id)`
**Warning signs:** PD returns 400 Bad Request or JSON serialization errors

### Pitfall 2: Operator Name Format
**What goes wrong:** Using underscore format "transfer_leader" instead of hyphen "transfer-leader"
**Why it happens:** Python method names use underscores, PD API uses hyphens
**How to avoid:** Operator names in POST body use hyphens: `"name": "transfer-leader"`
**Warning signs:** PD returns "unknown operator" error

### Pitfall 3: Scheduler vs Operator Confusion
**What goes wrong:** Trying to POST transfer-leader to /schedulers endpoint
**Why it happens:** Both create scheduling activities
**How to avoid:** Operators (transfer-leader, transfer-peer) go to POST /operators; Schedulers (evict-leader-scheduler) go to POST /schedulers
**Warning signs:** PD returns "unknown scheduler" or "invalid operator"

### Pitfall 4: Evict-Leader is Persistent
**What goes wrong:** drain_store keeps evicting leaders indefinitely
**Why it happens:** evict-leader-scheduler is a persistent scheduler, not a one-time operation
**How to avoid:** Document this behavior; removal would need DELETE /schedulers/evict-leader-scheduler-{store_id}
**Warning signs:** Store stays drained even after intended drain period

### Pitfall 5: HTTP Error Passthrough
**What goes wrong:** Swallowing or transforming PD API errors
**Why it happens:** Temptation to create friendly error messages
**How to avoid:** Per CONTEXT.md, raise_for_status() and let exception propagate
**Warning signs:** Agent doesn't see actual PD error reason

## Code Examples

Verified patterns from official sources:

### PD API: Transfer Leader Operator
```python
# Source: PD API docs - POST /operators
# Command equivalent: pd-ctl operator add transfer-leader <region_id> <store_id>
async def add_transfer_leader_operator(
    http: httpx.AsyncClient,
    region_id: int,
    to_store_id: int,
) -> None:
    """
    Transfer region leadership to specified store.

    POST /pd/api/v1/operators
    Body: {"name": "transfer-leader", "region_id": <int>, "store_id": <int>}

    Returns 200 on success, 400 on invalid input, 500 on failure.
    """
    response = await http.post(
        "/pd/api/v1/operators",
        json={
            "name": "transfer-leader",
            "region_id": region_id,
            "store_id": to_store_id,
        },
    )
    response.raise_for_status()
```

### PD API: Transfer Peer Operator
```python
# Source: PD API docs - POST /operators
# Command equivalent: pd-ctl operator add transfer-peer <region_id> <from_store_id> <to_store_id>
async def add_transfer_peer_operator(
    http: httpx.AsyncClient,
    region_id: int,
    from_store_id: int,
    to_store_id: int,
) -> None:
    """
    Move region replica from one store to another.

    POST /pd/api/v1/operators
    Body: {"name": "transfer-peer", "region_id": <int>,
           "from_store_id": <int>, "to_store_id": <int>}
    """
    response = await http.post(
        "/pd/api/v1/operators",
        json={
            "name": "transfer-peer",
            "region_id": region_id,
            "from_store_id": from_store_id,
            "to_store_id": to_store_id,
        },
    )
    response.raise_for_status()
```

### PD API: Evict Leader Scheduler (Drain Store)
```python
# Source: pd-ctl docs - scheduler add evict-leader-scheduler <store_id>
async def add_evict_leader_scheduler(
    http: httpx.AsyncClient,
    store_id: int,
) -> None:
    """
    Move all region leaders off a store.

    POST /pd/api/v1/schedulers
    Body: {"name": "evict-leader-scheduler", "store_id": <int>}

    Note: This is a persistent scheduler - leaders are continuously
    evicted until the scheduler is removed via DELETE.
    """
    response = await http.post(
        "/pd/api/v1/schedulers",
        json={
            "name": "evict-leader-scheduler",
            "store_id": store_id,
        },
    )
    response.raise_for_status()
```

### Subject Method Implementation
```python
# Source: Existing subject.py pattern + Phase 12 executor integration
async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
    """
    Transfer region leadership to another store.

    Fire-and-forget: returns when PD API accepts the request.
    Does not wait for the actual transfer to complete.

    Args:
        region_id: The region whose leader should be transferred
        to_store_id: The destination store for leadership

    Raises:
        httpx.HTTPStatusError: On PD API errors (includes error message)
    """
    await self.pd.add_transfer_leader_operator(region_id, int(to_store_id))
```

### ActionDefinition Schema
```python
# Source: Phase 12 registry.py pattern
TIKV_ACTION_DEFINITIONS = [
    ActionDefinition(
        name="transfer_leader",
        description="Transfer region leadership to another store",
        parameters={
            "region_id": ParamDef(
                type="int",
                description="ID of the region to transfer",
                required=True,
            ),
            "to_store_id": ParamDef(
                type="str",
                description="Target store ID for leadership",
                required=True,
            ),
        },
        risk_level="medium",
        requires_approval=False,
    ),
    ActionDefinition(
        name="transfer_peer",
        description="Move region replica from one store to another",
        parameters={
            "region_id": ParamDef(
                type="int",
                description="ID of the region to move",
                required=True,
            ),
            "from_store_id": ParamDef(
                type="str",
                description="Source store ID holding the replica",
                required=True,
            ),
            "to_store_id": ParamDef(
                type="str",
                description="Target store ID for the replica",
                required=True,
            ),
        },
        risk_level="high",
        requires_approval=False,
    ),
    ActionDefinition(
        name="drain_store",
        description="Evict all leaders from a store (continuous until removed)",
        parameters={
            "store_id": ParamDef(
                type="str",
                description="Store ID to drain leaders from",
                required=True,
            ),
        },
        risk_level="high",
        requires_approval=False,
    ),
]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pd-ctl CLI for operators | HTTP API via POST /operators | N/A - both always existed | Programmatic access from Python |
| store delete for drain | evict-leader-scheduler | N/A - different operations | scheduler is reversible, delete is permanent |

**Deprecated/outdated:**
- None identified - PD API v1 is stable

## Open Questions

Things that couldn't be fully resolved:

1. **Exact POST body field names for operators**
   - What we know: PD API docs say `name` is required; pd-ctl uses region_id/store_id pattern
   - What's unclear: Official API reference shows only `{"name": string}` as documented schema
   - Recommendation: Use field names from pd-ctl pattern (region_id, store_id, from_store_id, to_store_id) - these are well-tested by community

2. **HTTP timeout values**
   - What we know: Per CONTEXT.md, this is Claude's discretion
   - What's unclear: What timeouts are appropriate for PD API
   - Recommendation: Use httpx defaults (5s connect, no read timeout) initially; can tune if issues arise

3. **Scheduler removal for drain_store completion**
   - What we know: evict-leader-scheduler is persistent
   - What's unclear: Whether we need a "stop drain" action
   - Recommendation: Out of scope for Phase 13; document behavior and defer stop functionality

## Sources

### Primary (HIGH confidence)
- [PD API Documentation](https://docs-download.pingcap.com/api/pd-api/pd-api-v1.html) - POST /operators requires `name` field
- [pd-ctl Reference](https://tikv.org/docs/6.5/reference/cli/pd-ctl/) - Operator command syntax: `operator add transfer-leader <region_id> <store_id>`
- [PD Control User Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - Scheduler command syntax: `scheduler add evict-leader-scheduler <store_id>`
- [PD GitHub router.go](https://github.com/tikv/pd/blob/master/server/api/router.go) - POST /operators, POST /schedulers endpoints confirmed
- Phase 12 VERIFICATION.md - ActionRegistry, ActionDefinition integration patterns

### Secondary (MEDIUM confidence)
- [PD Go Client](https://pkg.go.dev/github.com/tikv/pd/client/http) - TransferLeaderByID, CreateOperators function signatures
- [Scheduling Introduction Wiki](https://github.com/tikv/pd/wiki/Scheduling-Introduction) - Operator types and scheduling concepts

### Tertiary (LOW confidence)
- GitHub issues discussing operator body formats - not official docs but show working patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses existing httpx/pydantic from Phase 2
- Architecture: HIGH - Follows established PDClient/Subject patterns
- PD API endpoints: HIGH - Verified in router.go and pd-ctl docs
- POST body format: MEDIUM - Derived from pd-ctl command patterns, not official API schema
- Pitfalls: HIGH - Based on Phase 2 research and CONTEXT.md decisions

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - PD API v1 is stable)
