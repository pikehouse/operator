# Stack Research: Agent Action Execution

**Focus:** Action execution framework for TiKV operator (leader transfer, region scheduling, dry-run mode, approval workflow)
**Researched:** 2026-01-25
**Overall Confidence:** HIGH (verified with official PD documentation, GitHub sources, PyPI)

---

## Current Stack (Existing - DO NOT CHANGE)

These are already in use and validated:

| Package | Version | Purpose |
|---------|---------|---------|
| Python | 3.11+ | Runtime |
| httpx | >=0.27.0 | Async HTTP client (PD API, Prometheus) |
| Pydantic | >=2.0.0 | Data validation, structured outputs |
| aiosqlite | >=0.20.0 | Async SQLite for tickets |
| anthropic | >=0.40.0 | Claude API integration |
| Typer | >=0.21.0 | CLI framework |
| Rich | >=14.0.0 | TUI, panels, live display |
| python-on-whales | >=0.70.0 | Docker/Compose orchestration |

**Existing Patterns Already Suitable for Actions:**
- `PDClient` with injected `httpx.AsyncClient` - extend for POST endpoints
- `Subject` Protocol with action method signatures - implement the stubs
- `DiagnosisOutput` Pydantic model - pattern for action request/result models
- `TicketDB` async context manager - pattern for action audit logging

---

## Additions for v2.0 (Action Execution)

### Core Finding: NO NEW DEPENDENCIES REQUIRED

The existing stack already provides everything needed for action execution:

| Capability | Provided By | Notes |
|------------|-------------|-------|
| HTTP POST to PD API | httpx (existing) | Already used for GET, just add POST methods |
| Action validation | Pydantic (existing) | Already used for DiagnosisOutput |
| Audit logging | aiosqlite (existing) | Extend tickets schema for action log |
| Dry-run mode | Python stdlib | No library needed - simple flag pattern |
| Approval workflow | asyncio.Event (stdlib) | Human-in-the-loop with async pause/resume |

**Why no drypy/dryable library:**
- These libraries add global state management complexity
- Our actions are method calls on Subject, not decorated functions
- A simple `dry_run: bool` parameter is cleaner and more explicit
- Keeps action behavior visible in the call site

---

## PD API Endpoints for Actions

**Source:** [tikv/pd router.go](https://github.com/tikv/pd/blob/master/server/api/router.go), [PD Control Guide](https://docs.pingcap.com/tidb/stable/pd-control/)

### Operator Endpoints (for immediate actions)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/pd/api/v1/operators` | POST | Create operator (transfer-leader, add-peer, etc.) |
| `/pd/api/v1/operators` | GET | List active operators |
| `/pd/api/v1/operators/{region_id}` | GET | Get operator for specific region |
| `/pd/api/v1/operators/{region_id}` | DELETE | Cancel operator for region |

**POST `/pd/api/v1/operators` body format:**
```json
{
  "name": "transfer-leader",
  "region_id": 1,
  "to_store_id": 2
}
```

Other operator names:
- `add-peer` - requires `region_id`, `to_store_id`
- `remove-peer` - requires `region_id`, `from_store_id`
- `split-region` - requires `region_id`

### Scheduler Endpoints (for ongoing policies)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/pd/api/v1/schedulers` | POST | Add scheduler (evict-leader, balance-region) |
| `/pd/api/v1/schedulers` | GET | List active schedulers |
| `/pd/api/v1/schedulers/{name}` | DELETE | Remove scheduler |
| `/pd/api/v1/schedulers/{name}` | POST | Pause/resume scheduler |

**POST `/pd/api/v1/schedulers` body format (evict-leader):**
```json
{
  "name": "evict-leader-scheduler",
  "store_id": 1
}
```

### Config Endpoints (for tuning)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/pd/api/v1/config` | GET | Get current config |
| `/pd/api/v1/config` | POST | Update config values |
| `/pd/api/v1/config/schedule` | GET/POST | Schedule-specific config |

**POST `/pd/api/v1/config` body format:**
```json
{
  "leader-schedule-limit": 4,
  "replica-schedule-limit": 8
}
```

### Store State Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/pd/api/v1/store/{store_id}/state` | POST | Change store state (for drain) |

**POST body (query param):** `?state=Offline` or `?state=Tombstone`

---

## Implementation Patterns

### Pattern 1: Action Models (Pydantic)

Extend existing Pydantic pattern from `diagnosis.py`:

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Literal

class ActionType(str, Enum):
    TRANSFER_LEADER = "transfer-leader"
    SPLIT_REGION = "split-region"
    ADD_PEER = "add-peer"
    REMOVE_PEER = "remove-peer"
    EVICT_LEADER = "evict-leader-scheduler"
    SET_CONFIG = "set-config"

class ActionRequest(BaseModel):
    """Request to execute an action on the cluster."""
    action_type: ActionType
    region_id: int | None = None
    store_id: str | None = None
    to_store_id: str | None = None
    config_key: str | None = None
    config_value: int | float | None = None

    rationale: str = Field(description="Why this action is recommended")
    ticket_id: int | None = Field(default=None, description="Associated ticket")

class ActionResult(BaseModel):
    """Result of an action execution."""
    success: bool
    action_type: ActionType
    dry_run: bool
    message: str
    pd_response: dict | None = None
    error: str | None = None
    executed_at: str | None = None

class ActionApproval(BaseModel):
    """Human approval decision."""
    approved: bool
    approver: str | None = None
    reason: str | None = None
    modified_request: ActionRequest | None = None  # Allow edits
```

### Pattern 2: Dry-Run Mode (No Library Needed)

Simple parameter-based approach:

```python
class PDClient:
    async def create_operator(
        self,
        name: str,
        region_id: int,
        to_store_id: str | None = None,
        dry_run: bool = False,
    ) -> ActionResult:
        """Create a PD operator (transfer-leader, split-region, etc.)."""
        body = {"name": name, "region_id": region_id}
        if to_store_id:
            body["to_store_id"] = int(to_store_id)

        if dry_run:
            return ActionResult(
                success=True,
                action_type=ActionType(name),
                dry_run=True,
                message=f"[DRY RUN] Would POST to /pd/api/v1/operators: {body}",
                pd_response=None,
            )

        response = await self.http.post("/pd/api/v1/operators", json=body)
        response.raise_for_status()

        return ActionResult(
            success=True,
            action_type=ActionType(name),
            dry_run=False,
            message=f"Created operator: {name}",
            pd_response=response.json(),
            executed_at=datetime.now().isoformat(),
        )
```

### Pattern 3: Human-in-the-Loop Approval (asyncio.Event)

Based on [FlowHunt patterns](https://www.flowhunt.io/blog/human-in-the-loop-middleware-python-safe-ai-agents/):

```python
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Awaitable

@dataclass
class PendingApproval:
    """Tracks a pending action awaiting human approval."""
    request: ActionRequest
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: ActionApproval | None = None

class ApprovalManager:
    """Manages human-in-the-loop approval workflow."""

    def __init__(self, timeout_seconds: float = 300.0):
        self.timeout = timeout_seconds
        self.pending: dict[str, PendingApproval] = {}
        self._on_approval_requested: Callable[[ActionRequest], Awaitable[None]] | None = None

    def on_approval_requested(self, callback: Callable[[ActionRequest], Awaitable[None]]):
        """Register callback for when approval is requested (e.g., update TUI)."""
        self._on_approval_requested = callback

    async def request_approval(self, request: ActionRequest) -> ActionApproval:
        """Request human approval, blocking until decision or timeout."""
        approval_id = f"{request.action_type.value}-{request.region_id}-{id(request)}"
        pending = PendingApproval(request=request)
        self.pending[approval_id] = pending

        # Notify UI that approval is needed
        if self._on_approval_requested:
            await self._on_approval_requested(request)

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self.timeout)
            return pending.result or ActionApproval(approved=False, reason="No decision recorded")
        except asyncio.TimeoutError:
            return ActionApproval(approved=False, reason=f"Approval timed out after {self.timeout}s")
        finally:
            del self.pending[approval_id]

    def approve(self, approval_id: str, approver: str, modified: ActionRequest | None = None):
        """Human approves the action."""
        if approval_id in self.pending:
            pending = self.pending[approval_id]
            pending.result = ActionApproval(
                approved=True,
                approver=approver,
                modified_request=modified,
            )
            pending.event.set()

    def reject(self, approval_id: str, reason: str):
        """Human rejects the action."""
        if approval_id in self.pending:
            pending = self.pending[approval_id]
            pending.result = ActionApproval(approved=False, reason=reason)
            pending.event.set()
```

### Pattern 4: Action Executor (Orchestrates Everything)

```python
class ActionExecutor:
    """Executes actions with dry-run, approval, and audit support."""

    def __init__(
        self,
        subject: TiKVSubject,
        approval_manager: ApprovalManager,
        db: TicketDB,
        dry_run: bool = False,
        require_approval: bool = True,
    ):
        self.subject = subject
        self.approval = approval_manager
        self.db = db
        self.dry_run = dry_run
        self.require_approval = require_approval

    async def execute(self, request: ActionRequest) -> ActionResult:
        """Execute an action with full workflow."""

        # 1. Dry-run short-circuit
        if self.dry_run:
            result = await self._execute_dry_run(request)
            await self._audit_log(request, result)
            return result

        # 2. Request approval if required
        if self.require_approval:
            approval = await self.approval.request_approval(request)
            if not approval.approved:
                result = ActionResult(
                    success=False,
                    action_type=request.action_type,
                    dry_run=False,
                    message=f"Action rejected: {approval.reason}",
                )
                await self._audit_log(request, result, approval)
                return result

            # Use modified request if provided
            if approval.modified_request:
                request = approval.modified_request

        # 3. Execute the action
        result = await self._execute_real(request)

        # 4. Audit log
        await self._audit_log(request, result)

        return result

    async def _execute_real(self, request: ActionRequest) -> ActionResult:
        """Execute action against real PD API."""
        match request.action_type:
            case ActionType.TRANSFER_LEADER:
                await self.subject.transfer_leader(request.region_id, request.to_store_id)
                return ActionResult(success=True, ...)
            case ActionType.SPLIT_REGION:
                await self.subject.split_region(request.region_id)
                return ActionResult(success=True, ...)
            # ... other cases
```

### Pattern 5: Audit Logging (Extend Existing Schema)

```sql
-- Add to existing schema.py
CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    approval_json TEXT,
    ticket_id INTEGER REFERENCES tickets(id),
    dry_run INTEGER NOT NULL DEFAULT 0,
    executed_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_action_log_ticket ON action_log(ticket_id);
CREATE INDEX IF NOT EXISTS idx_action_log_executed ON action_log(executed_at);
```

---

## What NOT to Add

| Library | Why Not |
|---------|---------|
| **drypy / dryable** | Global state pattern doesn't fit our method-based actions. Simple `dry_run: bool` parameter is cleaner. |
| **LangChain / LangGraph** | Overkill for single-action approval. Our workflow is simpler than multi-agent orchestration. Already have Claude API directly. |
| **Temporal / Prefect** | Workflow engines for complex pipelines. Our actions are single operations, not sagas. |
| **django-approval-workflow** | Django-specific. We're not using Django. |
| **SpiffWorkflow** | BPMN workflow engine is overkill. Our approval is binary (approve/reject). |
| **requests** | httpx already handles sync and async. No need for second HTTP library. |
| **aiohttp** | httpx is already in use and working well. Switching provides no benefit. |

---

## Integration Points

### With Existing PDClient

Extend `pd_client.py` with POST methods:

```python
# Add to existing PDClient class
async def create_operator(self, name: str, region_id: int, **kwargs) -> dict:
    """POST /pd/api/v1/operators"""
    body = {"name": name, "region_id": region_id, **kwargs}
    response = await self.http.post("/pd/api/v1/operators", json=body)
    response.raise_for_status()
    return response.json()

async def add_scheduler(self, name: str, store_id: int | None = None) -> dict:
    """POST /pd/api/v1/schedulers"""
    body = {"name": name}
    if store_id:
        body["store_id"] = store_id
    response = await self.http.post("/pd/api/v1/schedulers", json=body)
    response.raise_for_status()
    return response.json()

async def update_config(self, config: dict) -> dict:
    """POST /pd/api/v1/config"""
    response = await self.http.post("/pd/api/v1/config", json=config)
    response.raise_for_status()
    return response.json()
```

### With Existing TiKVSubject

Implement the stubbed action methods:

```python
# Replace NotImplementedError with actual implementation
async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
    await self.pd.create_operator(
        name="transfer-leader",
        region_id=region_id,
        to_store_id=int(to_store_id),
    )

async def split_region(self, region_id: int) -> None:
    await self.pd.create_operator(
        name="split-region",
        region_id=region_id,
    )

async def drain_store(self, store_id: str) -> None:
    # Use evict-leader-scheduler for safe drain
    await self.pd.add_scheduler(
        name="evict-leader-scheduler",
        store_id=int(store_id),
    )
```

### With TUI (Approval Workflow)

```python
# In tui/controller.py - add approval panel
class ApprovalPanel:
    def __init__(self, approval_manager: ApprovalManager):
        self.manager = approval_manager
        self.manager.on_approval_requested(self._on_request)

    async def _on_request(self, request: ActionRequest):
        """Called when agent proposes an action."""
        # Update TUI to show pending approval
        self.current_request = request
        self.show_approval_prompt()

    def handle_keypress(self, key: str):
        if key == "y":  # Approve
            self.manager.approve(self._current_id(), approver="human")
        elif key == "n":  # Reject
            self.manager.reject(self._current_id(), reason="Human rejected")
```

---

## Installation

**No new packages to install.** Existing dependencies cover all requirements:

```toml
# Already in pyproject.toml - no changes needed
dependencies = [
    "typer>=0.21.0",
    "rich>=14.0.0",
    "python-on-whales>=0.70.0",
    "httpx>=0.27.0",      # Already supports POST
    "pydantic>=2.0.0",    # Already used for models
    "aiosqlite>=0.20.0",  # Already used for audit
    "anthropic>=0.40.0",
]
```

---

## Version Verification

| Package | Current Version | Required | Status |
|---------|-----------------|----------|--------|
| httpx | 0.28.1 (Jan 2026) | >=0.27.0 | OK - POST support exists |
| Pydantic | 2.12.5 (Jan 2026) | >=2.0.0 | OK - BaseModel, Field work |
| aiosqlite | 0.20.0 | >=0.20.0 | OK - async context managers |

---

## Sources

### PD API Documentation
- [PD Control User Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - pd-ctl commands (HIGH confidence)
- [tikv/pd router.go](https://github.com/tikv/pd/blob/master/server/api/router.go) - HTTP endpoints (HIGH confidence)
- [PD HTTP Client Package](https://pkg.go.dev/github.com/tikv/pd/client/http) - Go client reference (HIGH confidence)
- [Scheduling Introduction Wiki](https://github.com/tikv/pd/wiki/Scheduling-Introduction) - Operator concepts (HIGH confidence)

### Human-in-the-Loop Patterns
- [FlowHunt: Human in the Loop Middleware](https://www.flowhunt.io/blog/human-in-the-loop-middleware-python-safe-ai-agents/) - asyncio.Event pattern (MEDIUM confidence)
- [LangChain HITL](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) - Interrupt pattern reference (MEDIUM confidence)

### Dry-Run Libraries (Evaluated, Rejected)
- [drypy](https://github.com/dzanotelli/drypy) - Decorator pattern, not suitable for methods
- [dryable](https://github.com/haarcuba/dryable) - Global state pattern, too implicit

### Version Verification
- [httpx PyPI](https://pypi.org/project/httpx/) - Version 0.28.1
- [Pydantic PyPI](https://pypi.org/project/pydantic/) - Version 2.12.5
- [httpx Releases](https://github.com/encode/httpx/releases) - Changelog verification
