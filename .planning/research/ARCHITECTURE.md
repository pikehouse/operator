# Architecture Research: Action Execution Integration

**Project:** Operator v2.0 Action Execution
**Researched:** 2026-01-25
**Confidence:** HIGH (verified with PD API router, existing codebase)

## Executive Summary

Action execution extends the existing operator architecture by adding an action proposal/approval/execution flow after diagnosis. The integration is surgical: new types in `monitor/types.py`, new methods in `TicketDB`, a new `ActionExecutor` component, and PD API action methods in `TiKVSubject`. The existing flow (detect -> ticket -> diagnose) remains unchanged.

**Key design decision:** Actions are first-class objects with explicit approval gates. No action executes without human approval. Dry-run mode allows validation before execution.

## Current Architecture

```
Monitor Loop                   Agent Runner
    |                               |
    v                               v
[Check Invariants] -----> [Create Ticket] -----> [Diagnose]
    |                               |                  |
    v                               v                  v
TiKVSubject.get_*()          TicketDB           Claude API
    |                               |                  |
    v                               v                  v
PD API / Prometheus          SQLite              DiagnosisOutput
```

### Existing Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `Subject` Protocol | `operator_core/subject.py` | Interface with action stubs |
| `TiKVSubject` | `operator_tikv/subject.py` | Observations work, actions raise NotImplementedError |
| `PDClient` | `operator_tikv/pd_client.py` | GET endpoints only (stores, regions) |
| `AgentRunner` | `operator_core/agent/runner.py` | Diagnosis flow, no action handling |
| `TicketDB` | `operator_core/db/tickets.py` | Ticket CRUD, no action tracking |
| `DiagnosisOutput` | `operator_core/agent/diagnosis.py` | Includes `recommended_action` field |

### Current Data Flow

1. **MonitorLoop** checks invariants every N seconds
2. **TiKVSubject** observations detect violations
3. **TicketDB** creates/deduplicates tickets (status: `open`)
4. **AgentRunner** picks up open tickets
5. **ContextGatherer** collects metrics/logs
6. **Claude** produces `DiagnosisOutput` with `recommended_action`
7. **TicketDB** stores diagnosis (status: `diagnosed`)
8. **Human** reads diagnosis (no action taken)

## v2.0 Extended Architecture

```
Monitor Loop                   Agent Runner                    Action Executor
    |                               |                                |
    v                               v                                v
[Check Invariants] -----> [Create Ticket] -----> [Diagnose] -----> [Propose Action]
    |                               |                  |                  |
    v                               v                  v                  v
TiKVSubject.get_*()          TicketDB           Claude API         ActionProposal
    |                               |                  |                  |
    v                               |                  |                  |
PD API / Prometheus              SQLite           DiagnosisOutput   [Await Approval]
                                    |                                     |
                                    v                                     v
                              actions table <---------------------- [Human Approve]
                                    |                                     |
                                    v                                     v
                              ActionRecord    <---------------- [Execute Action]
                                    |                                     |
                                    v                                     v
                              Audit Log       <----------------- TiKVSubject.action_*()
                                                                          |
                                                                          v
                                                                    PD API POST
```

### New Components Needed

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `ActionProposal` | `operator_core/monitor/types.py` | Proposed action data structure |
| `ActionRecord` | `operator_core/monitor/types.py` | Executed action audit trail |
| `ActionStatus` | `operator_core/monitor/types.py` | Status enum for action lifecycle |
| `ActionExecutor` | `operator_core/agent/executor.py` | Execute approved actions |
| PD write methods | `operator_tikv/pd_client.py` | POST endpoints for operators |
| Action implementations | `operator_tikv/subject.py` | Replace NotImplementedError stubs |

### Modified Components

| Component | Change |
|-----------|--------|
| `TicketDB` | Add action CRUD methods, new `actions` table |
| `DiagnosisOutput` | Add structured `proposed_action` field |
| `AgentRunner` | After diagnosis, create `ActionProposal` if action recommended |
| `schema.py` | Add `actions` table schema |

## Component Design

### ActionProposal Type

```python
# operator_core/monitor/types.py

class ActionStatus(str, Enum):
    """Valid action status values."""
    PROPOSED = "proposed"      # Awaiting human approval
    APPROVED = "approved"      # Human approved, ready to execute
    REJECTED = "rejected"      # Human rejected
    EXECUTING = "executing"    # Currently running
    COMPLETED = "completed"    # Successfully executed
    FAILED = "failed"          # Execution failed
    DRY_RUN = "dry_run"        # Dry-run completed (no actual execution)

@dataclass
class ActionProposal:
    """
    Proposed action from diagnosis.

    Actions require explicit human approval before execution.
    The dry_run field allows validation without actual execution.
    """
    id: int | None
    ticket_id: int                    # Links to source ticket
    action_type: str                  # e.g., "transfer_leader", "split_region"
    action_params: dict[str, Any]     # e.g., {"region_id": 123, "to_store_id": "5"}
    rationale: str                    # Why this action was recommended
    risks: list[str]                  # Potential risks from diagnosis
    status: ActionStatus = ActionStatus.PROPOSED
    dry_run: bool = False             # If True, validate but don't execute
    proposed_at: datetime | None = None
    approved_by: str | None = None    # Who approved (user ID or "system")
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    result: str | None = None         # Execution result or error message
```

### ActionRecord Type (Audit Trail)

```python
@dataclass
class ActionRecord:
    """
    Immutable record of an executed action.

    Provides audit trail for all actions taken by the operator.
    Never modified after creation.
    """
    id: int
    proposal_id: int
    ticket_id: int
    action_type: str
    action_params: dict[str, Any]
    executed_at: datetime
    executed_by: str                  # "agent" or user ID
    dry_run: bool
    success: bool
    result_message: str
    cluster_state_before: dict[str, Any] | None  # Snapshot for rollback info
    cluster_state_after: dict[str, Any] | None
```

### TicketDB Extensions

```python
# operator_core/db/tickets.py additions

class TicketDB:
    # ... existing methods ...

    # Action proposal CRUD
    async def create_action_proposal(
        self,
        ticket_id: int,
        action_type: str,
        action_params: dict[str, Any],
        rationale: str,
        risks: list[str],
    ) -> ActionProposal:
        """Create a new action proposal from diagnosis."""

    async def get_action_proposal(self, proposal_id: int) -> ActionProposal | None:
        """Get action proposal by ID."""

    async def list_pending_actions(self) -> list[ActionProposal]:
        """Get all actions awaiting approval."""

    async def approve_action(
        self,
        proposal_id: int,
        approved_by: str,
        dry_run: bool = False,
    ) -> None:
        """Approve an action for execution."""

    async def reject_action(
        self,
        proposal_id: int,
        rejected_by: str,
        reason: str,
    ) -> None:
        """Reject an action proposal."""

    async def update_action_status(
        self,
        proposal_id: int,
        status: ActionStatus,
        result: str | None = None,
    ) -> None:
        """Update action execution status."""

    # Audit trail
    async def record_action_execution(
        self,
        proposal: ActionProposal,
        success: bool,
        result_message: str,
        state_before: dict | None,
        state_after: dict | None,
    ) -> ActionRecord:
        """Create immutable audit record of action execution."""
```

### Database Schema Extension

```sql
-- Add to operator_core/db/schema.py

-- Action proposals table
CREATE TABLE IF NOT EXISTS action_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    action_type TEXT NOT NULL,
    action_params TEXT NOT NULL,           -- JSON
    rationale TEXT NOT NULL,
    risks TEXT NOT NULL,                   -- JSON array
    status TEXT NOT NULL DEFAULT 'proposed',
    dry_run BOOLEAN NOT NULL DEFAULT 0,
    proposed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by TEXT,
    approved_at TEXT,
    rejected_by TEXT,
    rejected_at TEXT,
    rejection_reason TEXT,
    executed_at TEXT,
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for finding pending actions
CREATE INDEX IF NOT EXISTS idx_actions_pending
ON action_proposals(status) WHERE status IN ('proposed', 'approved');

-- Index for ticket lookup
CREATE INDEX IF NOT EXISTS idx_actions_ticket
ON action_proposals(ticket_id);

-- Action execution audit trail (immutable)
CREATE TABLE IF NOT EXISTS action_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES action_proposals(id),
    ticket_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_params TEXT NOT NULL,           -- JSON
    executed_at TEXT NOT NULL,
    executed_by TEXT NOT NULL,
    dry_run BOOLEAN NOT NULL,
    success BOOLEAN NOT NULL,
    result_message TEXT NOT NULL,
    cluster_state_before TEXT,             -- JSON snapshot
    cluster_state_after TEXT,              -- JSON snapshot
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Trigger for action_proposals updated_at
CREATE TRIGGER IF NOT EXISTS action_proposals_updated_at
AFTER UPDATE ON action_proposals
BEGIN
    UPDATE action_proposals SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
```

### ActionExecutor Component

```python
# operator_core/agent/executor.py

@dataclass
class ActionExecutor:
    """
    Executes approved actions against the subject system.

    Handles:
    - Dry-run validation (check action is valid without executing)
    - State capture before/after execution
    - Error handling and rollback hints
    - Audit trail recording
    """

    subject: TiKVSubject
    db: TicketDB

    async def execute(self, proposal: ActionProposal) -> ActionRecord:
        """
        Execute an approved action.

        Args:
            proposal: Approved ActionProposal to execute

        Returns:
            ActionRecord with execution result

        Raises:
            ValueError: If proposal is not approved
        """
        if proposal.status != ActionStatus.APPROVED:
            raise ValueError(f"Cannot execute {proposal.status} action")

        # Update status to executing
        await self.db.update_action_status(proposal.id, ActionStatus.EXECUTING)

        # Capture state before
        state_before = await self._capture_cluster_state(proposal)

        try:
            if proposal.dry_run:
                result = await self._dry_run(proposal)
                status = ActionStatus.DRY_RUN
            else:
                result = await self._execute_action(proposal)
                status = ActionStatus.COMPLETED

            success = True

        except Exception as e:
            result = f"Execution failed: {type(e).__name__}: {e}"
            status = ActionStatus.FAILED
            success = False

        # Capture state after (even on failure, for debugging)
        state_after = await self._capture_cluster_state(proposal)

        # Update proposal status
        await self.db.update_action_status(proposal.id, status, result)

        # Create audit record
        return await self.db.record_action_execution(
            proposal=proposal,
            success=success,
            result_message=result,
            state_before=state_before,
            state_after=state_after,
        )

    async def _dry_run(self, proposal: ActionProposal) -> str:
        """
        Validate action without executing.

        Checks:
        - Action type is valid
        - Parameters are well-formed
        - Target resources exist
        - Preconditions are met
        """
        action_type = proposal.action_type
        params = proposal.action_params

        # Validate action type
        valid_actions = {
            "transfer_leader": self._validate_transfer_leader,
            "split_region": self._validate_split_region,
            "set_leader_schedule_limit": self._validate_schedule_limit,
            "set_replica_schedule_limit": self._validate_schedule_limit,
            "drain_store": self._validate_drain_store,
            "set_low_space_threshold": self._validate_threshold,
            "set_region_schedule_limit": self._validate_schedule_limit,
        }

        if action_type not in valid_actions:
            return f"DRY RUN FAILED: Unknown action type '{action_type}'"

        return await valid_actions[action_type](params)

    async def _validate_transfer_leader(self, params: dict) -> str:
        """Validate transfer_leader preconditions."""
        region_id = params.get("region_id")
        to_store_id = params.get("to_store_id")

        if region_id is None or to_store_id is None:
            return "DRY RUN FAILED: Missing region_id or to_store_id"

        # Check region exists
        try:
            region = await self.subject.pd.get_region(region_id)
        except Exception as e:
            return f"DRY RUN FAILED: Region {region_id} not found: {e}"

        # Check target store exists and is Up
        stores = await self.subject.get_stores()
        target_store = next((s for s in stores if s.id == to_store_id), None)

        if target_store is None:
            return f"DRY RUN FAILED: Store {to_store_id} not found"

        if target_store.state != "Up":
            return f"DRY RUN FAILED: Store {to_store_id} is {target_store.state}, not Up"

        # Check target is a peer
        if to_store_id not in region.peer_store_ids:
            return f"DRY RUN FAILED: Store {to_store_id} is not a peer of region {region_id}"

        return f"DRY RUN OK: Can transfer leader of region {region_id} to store {to_store_id}"

    async def _execute_action(self, proposal: ActionProposal) -> str:
        """Execute the actual action."""
        action_type = proposal.action_type
        params = proposal.action_params

        # Dispatch to subject method
        if action_type == "transfer_leader":
            await self.subject.transfer_leader(
                region_id=params["region_id"],
                to_store_id=params["to_store_id"],
            )
            return f"Transferred leader of region {params['region_id']} to store {params['to_store_id']}"

        elif action_type == "split_region":
            await self.subject.split_region(region_id=params["region_id"])
            return f"Split region {params['region_id']}"

        # ... other actions ...

        else:
            raise ValueError(f"Unknown action type: {action_type}")

    async def _capture_cluster_state(self, proposal: ActionProposal) -> dict:
        """Capture relevant cluster state for audit trail."""
        state = {
            "timestamp": datetime.now().isoformat(),
            "stores": [],
        }

        # Capture store states
        stores = await self.subject.get_stores()
        state["stores"] = [
            {"id": s.id, "address": s.address, "state": s.state}
            for s in stores
        ]

        # For region-specific actions, capture region state
        region_id = proposal.action_params.get("region_id")
        if region_id:
            try:
                region = await self.subject.pd.get_region(region_id)
                state["region"] = {
                    "id": region.id,
                    "leader_store_id": region.leader_store_id,
                    "peer_store_ids": region.peer_store_ids,
                }
            except Exception:
                pass  # Region might not exist in error cases

        return state
```

## PD API Action Endpoints

Based on [PD API Router](https://github.com/tikv/pd/blob/master/server/api/router.go):

### Operators Endpoint (for transfer-leader, split-region)

```
POST /pd/api/v1/operators
Body: {"name": "<operator_type>", "region_id": <id>, ...params}
```

| Operator | Request Body | Notes |
|----------|--------------|-------|
| transfer-leader | `{"name": "transfer-leader", "region_id": 1, "to_store_id": 2}` | Schedule leader to store 2 |
| split-region | `{"name": "split-region", "region_id": 1, "policy": "approximate"}` | Split region in half |
| add-peer | `{"name": "add-peer", "region_id": 1, "store_id": 2}` | Add replica on store 2 |
| remove-peer | `{"name": "remove-peer", "region_id": 1, "store_id": 2}` | Remove replica from store 2 |

### Config Endpoints (for schedule limits)

```
POST /pd/api/v1/config/schedule
Body: {"leader-schedule-limit": 4}
```

| Config | Request Body |
|--------|--------------|
| leader-schedule-limit | `{"leader-schedule-limit": <n>}` |
| region-schedule-limit | `{"region-schedule-limit": <n>}` |
| replica-schedule-limit | `{"replica-schedule-limit": <n>}` |
| low-space-ratio | `{"low-space-ratio": 0.8}` |

### Store Endpoints (for drain)

```
DELETE /pd/api/v1/store/{id}
```

Setting store state to "Offline" triggers draining:
```
POST /pd/api/v1/store/{id}/state?state=Offline
```

## PDClient Extensions

```python
# operator_tikv/pd_client.py additions

@dataclass
class PDClient:
    http: httpx.AsyncClient

    # ... existing GET methods ...

    # Operator creation
    async def create_operator(
        self,
        operator_name: str,
        **params: Any,
    ) -> None:
        """
        Create a scheduling operator.

        POST /pd/api/v1/operators

        Args:
            operator_name: Operator type (transfer-leader, split-region, etc.)
            **params: Operator-specific parameters
        """
        body = {"name": operator_name, **params}
        response = await self.http.post("/pd/api/v1/operators", json=body)
        response.raise_for_status()

    async def transfer_leader(self, region_id: int, to_store_id: int) -> None:
        """Schedule leader transfer for a region."""
        await self.create_operator(
            "transfer-leader",
            region_id=region_id,
            to_store_id=to_store_id,
        )

    async def split_region(self, region_id: int, policy: str = "approximate") -> None:
        """Schedule region split."""
        await self.create_operator(
            "split-region",
            region_id=region_id,
            policy=policy,
        )

    # Schedule configuration
    async def set_schedule_config(self, **config: Any) -> None:
        """
        Update schedule configuration.

        POST /pd/api/v1/config/schedule
        """
        response = await self.http.post("/pd/api/v1/config/schedule", json=config)
        response.raise_for_status()

    async def set_leader_schedule_limit(self, limit: int) -> None:
        """Set max leader transfers per scheduling cycle."""
        await self.set_schedule_config(**{"leader-schedule-limit": limit})

    async def set_replica_schedule_limit(self, limit: int) -> None:
        """Set max replica moves per scheduling cycle."""
        await self.set_schedule_config(**{"replica-schedule-limit": limit})

    async def set_region_schedule_limit(self, limit: int) -> None:
        """Set max region moves per scheduling cycle."""
        await self.set_schedule_config(**{"region-schedule-limit": limit})

    async def set_low_space_ratio(self, ratio: float) -> None:
        """Set low disk space ratio (0.0-1.0)."""
        await self.set_schedule_config(**{"low-space-ratio": ratio})

    # Store management
    async def set_store_state(self, store_id: int, state: str) -> None:
        """
        Set store state (Up, Offline, Tombstone).

        POST /pd/api/v1/store/{id}/state?state={state}
        """
        response = await self.http.post(
            f"/pd/api/v1/store/{store_id}/state",
            params={"state": state},
        )
        response.raise_for_status()

    async def drain_store(self, store_id: int) -> None:
        """Mark store as Offline to trigger draining."""
        await self.set_store_state(store_id, "Offline")
```

## TiKVSubject Action Implementations

```python
# operator_tikv/subject.py - replace NotImplementedError stubs

@dataclass
class TiKVSubject:
    pd: PDClient
    prom: PrometheusClient

    # ... existing observation methods ...

    async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
        """Transfer region leadership to another store."""
        await self.pd.transfer_leader(
            region_id=region_id,
            to_store_id=int(to_store_id),  # PD API uses int
        )

    async def split_region(self, region_id: int) -> None:
        """Split a region into two smaller regions."""
        await self.pd.split_region(region_id=region_id)

    async def set_leader_schedule_limit(self, n: int) -> None:
        """Set the maximum leader transfers per scheduling cycle."""
        await self.pd.set_leader_schedule_limit(n)

    async def set_replica_schedule_limit(self, n: int) -> None:
        """Set the maximum replica moves per scheduling cycle."""
        await self.pd.set_replica_schedule_limit(n)

    async def drain_store(self, store_id: str) -> None:
        """Evacuate all regions from a store."""
        await self.pd.drain_store(int(store_id))

    async def set_low_space_threshold(self, percent: float) -> None:
        """Set the low disk space threshold percentage."""
        # PD uses ratio (0-1), we accept percent (0-100)
        ratio = percent / 100.0
        await self.pd.set_low_space_ratio(ratio)

    async def set_region_schedule_limit(self, n: int) -> None:
        """Set the maximum region moves per scheduling cycle."""
        await self.pd.set_region_schedule_limit(n)
```

## Dry-Run Mode Implementation

Dry-run mode validates actions without executing them against PD. This is crucial for:

1. **Demo safety**: Show action proposals without affecting cluster
2. **Validation**: Ensure preconditions are met before committing
3. **Testing**: Verify action execution flow without side effects

### Dry-Run Validation Checks

| Action | Dry-Run Checks |
|--------|----------------|
| transfer_leader | Region exists, target store exists and is Up, target is peer of region |
| split_region | Region exists, region has data (not empty) |
| drain_store | Store exists, store is Up, store has regions |
| set_*_limit | Value is non-negative integer |
| set_low_space_threshold | Value is between 0-100 |

### Dry-Run Response Format

```python
class DryRunResult:
    """Result of dry-run validation."""
    valid: bool               # Can action be executed?
    message: str              # Human-readable result
    preconditions: list[str]  # What was checked
    warnings: list[str]       # Non-blocking concerns
```

## Action Flow: Diagnosis to Execution

### Extended DiagnosisOutput

```python
# operator_core/agent/diagnosis.py addition

class ProposedAction(BaseModel):
    """Structured action proposal from diagnosis."""
    action_type: str = Field(description="Action to take (transfer_leader, split_region, etc.)")
    params: dict[str, Any] = Field(description="Action parameters")
    rationale: str = Field(description="Why this action addresses the issue")
    urgency: str = Field(description="immediate / soon / when_convenient")

class DiagnosisOutput(BaseModel):
    # ... existing fields ...

    # Replace string recommended_action with structured proposal
    proposed_action: ProposedAction | None = Field(
        default=None,
        description="Specific action to take, or None if no action needed"
    )
```

### AgentRunner Extension

```python
# operator_core/agent/runner.py extension

class AgentRunner:
    # ... existing fields ...

    async def _diagnose_ticket(self, db: TicketDB, ticket: Ticket) -> None:
        """Diagnose ticket and create action proposal if recommended."""
        # ... existing diagnosis code ...

        diagnosis_output = response.parsed_output

        # Store diagnosis
        diagnosis_md = format_diagnosis_markdown(diagnosis_output)
        await db.update_diagnosis(ticket.id, diagnosis_md)

        # Create action proposal if recommended
        if diagnosis_output.proposed_action:
            action = diagnosis_output.proposed_action
            await db.create_action_proposal(
                ticket_id=ticket.id,
                action_type=action.action_type,
                action_params=action.params,
                rationale=action.rationale,
                risks=diagnosis_output.risks,
            )
            print(f"Action proposed for ticket {ticket.id}: {action.action_type}")
```

### Approval Flow (CLI)

```bash
# List pending actions
operator actions list

# Show action details
operator actions show 42

# Approve action (real execution)
operator actions approve 42

# Approve with dry-run
operator actions approve 42 --dry-run

# Reject action
operator actions reject 42 --reason "Not safe during peak traffic"
```

### Action Execution Loop

```python
# New daemon or integrated into AgentRunner

async def process_approved_actions(db: TicketDB, executor: ActionExecutor) -> None:
    """Process all approved actions."""
    proposals = await db.list_actions(status=ActionStatus.APPROVED)

    for proposal in proposals:
        print(f"Executing action {proposal.id}: {proposal.action_type}")
        record = await executor.execute(proposal)

        if record.success:
            print(f"Action {proposal.id} completed: {record.result_message}")
        else:
            print(f"Action {proposal.id} failed: {record.result_message}")
```

## Data Flow Summary

```
1. Diagnosis produces ProposedAction
   |
2. AgentRunner creates ActionProposal (status: proposed)
   |
3. Human reviews via CLI (operator actions list/show)
   |
4. Human approves or rejects
   |-- approve --> status: approved, dry_run: false
   |-- approve --dry-run --> status: approved, dry_run: true
   |-- reject --> status: rejected
   |
5. ActionExecutor picks up approved actions
   |
6. If dry_run: validate preconditions, return result
   |
7. If not dry_run: execute against PD API
   |
8. Create ActionRecord (immutable audit trail)
   |
9. Update ActionProposal status (completed/failed/dry_run)
```

## Integration Points Summary

| Existing Component | Integration Point | Change Type |
|--------------------|-------------------|-------------|
| `monitor/types.py` | Add ActionProposal, ActionRecord, ActionStatus | New types |
| `db/tickets.py` | Add action CRUD methods | Extended class |
| `db/schema.py` | Add actions/action_records tables | New schema |
| `agent/diagnosis.py` | Add ProposedAction model | Extended model |
| `agent/runner.py` | Create action proposal after diagnosis | Extended flow |
| `agent/executor.py` | New ActionExecutor class | New module |
| `tikv/pd_client.py` | Add POST methods for operators/config | Extended class |
| `tikv/subject.py` | Replace NotImplementedError stubs | Implementation |
| `cli/` | Add actions subcommand | New CLI |

## Build Order

Based on dependencies:

### Phase 1: Types and Schema
1. Add `ActionStatus`, `ActionProposal`, `ActionRecord` to `monitor/types.py`
2. Add tables to `db/schema.py`
3. Write type tests

### Phase 2: Database Layer
1. Add action CRUD to `TicketDB`
2. Write database tests with fixtures

### Phase 3: PD API Actions
1. Add POST methods to `PDClient`
2. Implement action methods in `TiKVSubject`
3. Write integration tests (against real PD)

### Phase 4: Executor
1. Create `ActionExecutor` class
2. Implement dry-run validation
3. Implement real execution
4. Write executor tests

### Phase 5: Agent Integration
1. Add `ProposedAction` to `DiagnosisOutput`
2. Update prompt to request structured actions
3. Extend `AgentRunner` to create proposals
4. Write agent tests

### Phase 6: CLI
1. Add `actions` subcommand group
2. Implement list/show/approve/reject commands
3. Manual verification with real cluster

## Sources

### Primary (HIGH confidence)
- [PD API Router](https://github.com/tikv/pd/blob/master/server/api/router.go) - Complete API route definitions
- [PD HTTP Client Package](https://pkg.go.dev/github.com/tikv/pd/client/http) - HTTP API constants and methods
- [pd-ctl Documentation](https://tikv.org/docs/3.0/reference/tools/pd-ctl/) - Operator command reference
- Existing codebase: `operator_tikv/pd_client.py`, `operator_core/agent/runner.py`, `operator_core/db/tickets.py`

### Secondary (MEDIUM confidence)
- [PD Scheduling Best Practices](https://docs.pingcap.com/tidb/stable/pd-scheduling-best-practices/) - Scheduling configuration guidance
- [PD Control Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - Schedule limit explanations
