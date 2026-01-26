# Phase 15: Workflow Actions - Research

**Researched:** 2026-01-26
**Domain:** Workflow orchestration, action chaining, scheduled follow-ups, retry with backoff
**Confidence:** HIGH

## Summary

This phase extends the existing action execution foundation (Phase 12-14) to support multi-action workflows, scheduled follow-up actions, and automatic retry with exponential backoff. Research focused on patterns that integrate naturally with the existing SQLite-based action persistence model, asyncio-based agent loop, and fire-and-forget execution semantics.

The existing codebase provides a solid foundation: `ActionProposal` with status lifecycle, `ActionExecutor` for execution orchestration, `ActionDB` for persistence, and `ActionAuditor` for logging. Phase 15 extends this with three new capabilities:

1. **Workflow chaining (WRK-01):** Multiple actions grouped as a single workflow, executed sequentially with dependency tracking
2. **Scheduled follow-ups (WRK-02):** Actions scheduled for future execution (e.g., "check again in 5 minutes")
3. **Retry with backoff (WRK-03):** Failed actions automatically retry with configurable exponential backoff

The research recommends a database-driven approach over external schedulers (APScheduler, Celery) for simplicity and consistency with existing patterns. Workflows are persisted as linked proposals with a `workflow_id`, scheduled actions use a `scheduled_at` timestamp, and retries add `retry_count` / `max_retries` fields to the existing schema.

**Primary recommendation:** Extend existing ActionProposal/ActionDB with workflow_id, scheduled_at, and retry fields. Use the agent's existing poll loop to check for ready-to-execute scheduled actions and retry eligible failed actions. Use tenacity for retry logic within individual action execution.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tenacity | 8.2+ | Retry with exponential backoff for action execution | Industry standard, async support, configurable backoff strategies |
| aiosqlite | 0.19+ | Async database operations (already used) | Existing project pattern |
| pydantic | v2 | Workflow/action models (already used) | Existing project pattern |
| asyncio | stdlib | Task scheduling and delayed execution | Python standard, no new dependencies |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| datetime | stdlib | Timestamp calculations for scheduling | Schedule time comparisons |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Database polling | APScheduler | APScheduler adds complexity, requires separate process; existing poll loop suffices |
| SQLite for scheduling | Redis/Celery | Overkill for single-node; SQLite aligns with existing architecture |
| tenacity | backoff | backoff is lighter but tenacity has better async support and jitter options |
| In-memory workflow state | Database persistence | Memory is faster but loses state on restart; database aligns with approval/audit patterns |

**Installation:**
```bash
pip install tenacity  # Only new dependency
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/
└── src/
    └── operator_core/
        ├── actions/
        │   ├── types.py          # Add WorkflowProposal, extend ActionProposal
        │   ├── executor.py       # Add workflow/retry/schedule logic
        │   └── retry.py          # NEW: Retry configuration and helpers
        ├── db/
        │   ├── schema.py         # Add workflow and scheduling columns
        │   └── actions.py        # Add workflow/scheduled queries
        └── agent/
            └── runner.py         # Check for scheduled/retry-eligible actions
```

### Pattern 1: Workflow as Linked Proposals
**What:** A workflow is a group of ActionProposals sharing a workflow_id, with execution_order tracking
**When to use:** Agent recommends multiple related actions (WRK-01)
**Example:**
```python
# Source: Derived from existing ActionProposal pattern
class WorkflowProposal(BaseModel):
    """Group of related actions to execute as a workflow."""

    id: int | None = Field(default=None)
    name: str = Field(..., description="Workflow name (e.g., 'drain_and_verify')")
    description: str = Field(..., description="What this workflow accomplishes")
    ticket_id: int | None = Field(default=None)
    status: WorkflowStatus = Field(default=WorkflowStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.now)

class WorkflowStatus(str, Enum):
    PENDING = "pending"       # Not started
    IN_PROGRESS = "in_progress"  # At least one action executing
    COMPLETED = "completed"   # All actions completed successfully
    FAILED = "failed"         # At least one action failed
    CANCELLED = "cancelled"   # Manually cancelled

# ActionProposal gets new fields:
class ActionProposal(BaseModel):
    # ... existing fields ...
    workflow_id: int | None = Field(default=None, description="Parent workflow if part of chain")
    execution_order: int = Field(default=0, description="Order within workflow (0-indexed)")
    depends_on_proposal_id: int | None = Field(
        default=None, description="Must complete before this action runs"
    )
```

### Pattern 2: Database-Driven Scheduling
**What:** Actions with scheduled_at timestamp are picked up by poll loop when time arrives
**When to use:** Schedule follow-up verification (WRK-02)
**Example:**
```python
# Source: Derived from existing ActionDB patterns
# Add to ActionProposal:
scheduled_at: datetime | None = Field(
    default=None, description="Execute at this time (None = immediate)"
)

# ActionDB method:
async def list_ready_scheduled(self) -> list[ActionProposal]:
    """Get approved actions ready for scheduled execution."""
    now = datetime.now().isoformat()

    async with self._conn.execute(
        """
        SELECT * FROM action_proposals
        WHERE status = 'validated'
          AND scheduled_at IS NOT NULL
          AND scheduled_at <= ?
          AND (approved_at IS NOT NULL OR workflow_id IS NOT NULL)
        ORDER BY scheduled_at ASC
        """,
        (now,),
    ) as cursor:
        rows = await cursor.fetchall()

    return [self._row_to_proposal(row) for row in rows]

# In AgentRunner._process_cycle:
# After processing tickets, check for scheduled actions
scheduled_actions = await db.list_ready_scheduled()
for action in scheduled_actions:
    await self._execute_scheduled_action(action)
```

### Pattern 3: Retry with Exponential Backoff
**What:** Failed actions automatically retry with configurable backoff
**When to use:** Transient failures (network, rate limiting) (WRK-03)
**Example:**
```python
# Source: tenacity documentation + existing executor pattern
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)

# Add to ActionProposal:
retry_count: int = Field(default=0, description="Number of retry attempts so far")
max_retries: int = Field(default=3, description="Maximum retry attempts")
next_retry_at: datetime | None = Field(default=None, description="When to retry next")
last_error: str | None = Field(default=None, description="Error from last attempt")

# Retry configuration in executor:
class RetryConfig:
    """Configuration for action retry behavior."""

    max_attempts: int = 3
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 60.0
    exponential_base: float = 2.0

    def calculate_next_retry(self, attempt: int) -> datetime:
        """Calculate next retry time with exponential backoff + jitter."""
        import random

        # Exponential backoff: base^attempt
        wait = min(
            self.max_wait_seconds,
            self.min_wait_seconds * (self.exponential_base ** attempt),
        )
        # Add jitter (0-50% of wait time)
        jitter = random.uniform(0, wait * 0.5)
        delay = wait + jitter

        return datetime.now() + timedelta(seconds=delay)
```

### Pattern 4: Workflow Execution Orchestration
**What:** Execute workflow actions in order, respecting dependencies
**When to use:** Processing a multi-action workflow
**Example:**
```python
# Source: Derived from LangGraph orchestrator patterns
async def execute_workflow(
    self,
    workflow_id: int,
    subject: "Subject",
) -> list[ActionRecord]:
    """Execute all actions in a workflow in order."""
    async with ActionDB(self.db_path) as db:
        actions = await db.list_workflow_actions(workflow_id)

        if not actions:
            raise ValueError(f"Workflow {workflow_id} has no actions")

        # Sort by execution_order
        actions.sort(key=lambda a: a.execution_order)

        results = []
        for action in actions:
            # Check if dependency completed
            if action.depends_on_proposal_id:
                dep = await db.get_proposal(action.depends_on_proposal_id)
                if dep.status != ActionStatus.COMPLETED:
                    raise ValueError(
                        f"Dependency {action.depends_on_proposal_id} not completed"
                    )

            # Execute this action
            try:
                record = await self.execute_proposal(action.id, subject)
                results.append(record)
            except Exception as e:
                # Mark workflow as failed, don't continue
                await db.update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                raise

        # All completed successfully
        await db.update_workflow_status(workflow_id, WorkflowStatus.COMPLETED)

        return results
```

### Pattern 5: General Tools Extension (ACT-03)
**What:** Allow agent to use tools beyond subject-defined actions
**When to use:** Agent needs to perform operations not specific to TiKV
**Example:**
```python
# Source: Derived from ActionType enum in types.py
class ActionType(str, Enum):
    SUBJECT = "subject"    # Subject-defined action (existing)
    TOOL = "tool"          # General tool (NEW)
    WORKFLOW = "workflow"  # Multi-step workflow (NEW)

# General tools could include:
GENERAL_TOOLS = [
    ActionDefinition(
        name="wait",
        description="Wait for a specified duration before next action",
        parameters={
            "seconds": ParamDef(type="int", description="Seconds to wait", required=True),
        },
        action_type=ActionType.TOOL,
        risk_level="low",
        requires_approval=False,
    ),
    ActionDefinition(
        name="log_message",
        description="Log a message for audit trail",
        parameters={
            "message": ParamDef(type="str", description="Message to log", required=True),
            "level": ParamDef(type="str", description="Log level", required=False),
        },
        action_type=ActionType.TOOL,
        risk_level="low",
        requires_approval=False,
    ),
]
```

### Anti-Patterns to Avoid
- **External scheduler dependencies:** Don't add APScheduler/Celery when database polling suffices
- **Blocking retries:** Don't use synchronous retry loops; use database state + poll cycle
- **Memory-only workflow state:** Always persist workflow state for restart recovery
- **Retry without backoff:** Always use exponential backoff with jitter for distributed systems
- **Unlimited retries:** Always cap max_retries to prevent infinite loops
- **Tight coupling to Subject:** General tools (ActionType.TOOL) should not require Subject

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff calculation | Custom math | tenacity.wait_exponential_jitter | Handles jitter, overflow, edge cases |
| Async retry decorator | Custom wrapper | tenacity.AsyncRetrying | Production-tested, configurable |
| Task scheduling | Custom timer threads | Database scheduled_at + poll loop | Survives restarts, aligns with existing patterns |
| Workflow state machine | Custom enum transitions | Existing ActionStatus pattern | Consistency with Phase 12 patterns |
| Follow-up scheduling | asyncio.call_later | Database scheduled_at field | Persistence, survives restarts |

**Key insight:** The existing architecture (database-driven state, poll loop, asyncio) already provides scheduling primitives. Phase 15 extends the schema rather than introducing new infrastructure.

## Common Pitfalls

### Pitfall 1: Retry During Approval Wait
**What goes wrong:** Retrying an action that's waiting for human approval
**Why it happens:** Confusing "failed execution" with "awaiting approval"
**How to avoid:** Only retry actions with status=FAILED, not status=VALIDATED awaiting approval
**Warning signs:** Duplicate proposals appearing, approval confusion

### Pitfall 2: Thundering Herd on Retry
**What goes wrong:** All failed actions retry at the same time, overwhelming the target
**Why it happens:** Using fixed delays instead of jitter
**How to avoid:** Always use `wait_exponential_jitter` or add random jitter manually
**Warning signs:** Spike in PD API errors after retry wave

### Pitfall 3: Workflow Partial Failure
**What goes wrong:** Later actions execute after earlier ones failed
**Why it happens:** Not checking dependency status before executing
**How to avoid:** Check depends_on_proposal_id status before executing each action
**Warning signs:** Inconsistent cluster state, confusing audit trail

### Pitfall 4: Scheduled Action Never Executes
**What goes wrong:** Action with scheduled_at sits forever in validated status
**Why it happens:** Forgot to check scheduled actions in poll loop, or approval gate blocks
**How to avoid:** Scheduled actions in workflows bypass individual approval (workflow approved as unit)
**Warning signs:** Actions stuck in validated status past scheduled_at time

### Pitfall 5: Retry Count Overflow
**What goes wrong:** Action retries forever, never gives up
**Why it happens:** No max_retries limit, or retry count not persisted
**How to avoid:** Persist retry_count, check against max_retries before each retry
**Warning signs:** Same action appearing in failed status repeatedly, audit log full of retries

### Pitfall 6: Lost Workflow Context
**What goes wrong:** Individual actions in workflow don't know they're part of a workflow
**Why it happens:** Not propagating workflow_id to all proposals
**How to avoid:** Set workflow_id on all proposals in the workflow at creation time
**Warning signs:** Orphaned proposals, workflow status doesn't reflect actual state

## Code Examples

Verified patterns from official sources and existing codebase:

### Tenacity Async Retry with Exponential Backoff
```python
# Source: https://tenacity.readthedocs.io/
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)
import httpx

async def execute_with_retry(
    subject: "Subject",
    action_name: str,
    parameters: dict,
    max_attempts: int = 3,
) -> Any:
    """Execute action with exponential backoff retry."""

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    ):
        with attempt:
            method = getattr(subject, action_name)
            return await method(**parameters)
```

### Database Schema Extensions
```sql
-- Source: Derived from existing ACTIONS_SCHEMA_SQL
-- Add to action_proposals table:
ALTER TABLE action_proposals ADD COLUMN workflow_id INTEGER;
ALTER TABLE action_proposals ADD COLUMN execution_order INTEGER DEFAULT 0;
ALTER TABLE action_proposals ADD COLUMN depends_on_proposal_id INTEGER;
ALTER TABLE action_proposals ADD COLUMN scheduled_at TEXT;
ALTER TABLE action_proposals ADD COLUMN retry_count INTEGER DEFAULT 0;
ALTER TABLE action_proposals ADD COLUMN max_retries INTEGER DEFAULT 3;
ALTER TABLE action_proposals ADD COLUMN next_retry_at TEXT;
ALTER TABLE action_proposals ADD COLUMN last_error TEXT;

-- Workflows table
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    ticket_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

-- Index for finding workflow actions
CREATE INDEX IF NOT EXISTS idx_action_proposals_workflow
ON action_proposals(workflow_id);

-- Index for finding scheduled actions
CREATE INDEX IF NOT EXISTS idx_action_proposals_scheduled
ON action_proposals(scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Index for finding retry-eligible actions
CREATE INDEX IF NOT EXISTS idx_action_proposals_retry
ON action_proposals(next_retry_at) WHERE next_retry_at IS NOT NULL;
```

### ActionDB Workflow Methods
```python
# Source: Derived from existing ActionDB patterns
async def create_workflow(
    self,
    name: str,
    description: str,
    actions: list[ActionProposal],
    ticket_id: int | None = None,
) -> int:
    """Create a workflow with its actions."""
    # Insert workflow
    cursor = await self._conn.execute(
        """
        INSERT INTO workflows (name, description, ticket_id, status)
        VALUES (?, ?, ?, 'pending')
        """,
        (name, description, ticket_id),
    )
    workflow_id = cursor.lastrowid

    # Insert actions with workflow_id
    for i, action in enumerate(actions):
        action.workflow_id = workflow_id
        action.execution_order = i
        await self.create_proposal(action)

    await self._conn.commit()
    return workflow_id

async def list_workflow_actions(
    self, workflow_id: int
) -> list[ActionProposal]:
    """Get all actions for a workflow in execution order."""
    async with self._conn.execute(
        """
        SELECT * FROM action_proposals
        WHERE workflow_id = ?
        ORDER BY execution_order ASC
        """,
        (workflow_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    return [self._row_to_proposal(row) for row in rows]

async def list_retry_eligible(self) -> list[ActionProposal]:
    """Get failed actions ready for retry."""
    now = datetime.now().isoformat()

    async with self._conn.execute(
        """
        SELECT * FROM action_proposals
        WHERE status = 'failed'
          AND retry_count < max_retries
          AND next_retry_at IS NOT NULL
          AND next_retry_at <= ?
        ORDER BY next_retry_at ASC
        """,
        (now,),
    ) as cursor:
        rows = await cursor.fetchall()

    return [self._row_to_proposal(row) for row in rows]
```

### AgentRunner Workflow Integration
```python
# Source: Derived from existing AgentRunner pattern
async def _process_cycle(self, db: TicketDB) -> None:
    """Process one cycle: tickets, scheduled actions, retries."""
    # Existing: Process open tickets
    tickets = await db.list_tickets(status=TicketStatus.OPEN)
    for ticket in tickets:
        if self._shutdown.is_set():
            break
        await self._diagnose_ticket(db, ticket)

    # NEW: Execute scheduled actions
    if self.executor:
        async with ActionDB(self.db_path) as action_db:
            scheduled = await action_db.list_ready_scheduled()
            for action in scheduled:
                if self._shutdown.is_set():
                    break
                await self._execute_scheduled_action(action)

            # NEW: Retry eligible failed actions
            retry_eligible = await action_db.list_retry_eligible()
            for action in retry_eligible:
                if self._shutdown.is_set():
                    break
                await self._retry_failed_action(action)

async def _retry_failed_action(self, action: ActionProposal) -> None:
    """Retry a failed action with updated retry count."""
    print(f"Retrying action {action.id}: {action.action_name} (attempt {action.retry_count + 1})")

    try:
        # Reset status to validated for re-execution
        async with ActionDB(self.db_path) as db:
            await db.update_proposal_status(action.id, ActionStatus.VALIDATED)
            await db.increment_retry_count(action.id)

        # Execute
        record = await self.executor.execute_proposal(action.id, self.subject)

        if record.success:
            print(f"Retry succeeded for action {action.id}")
        else:
            # Will be picked up on next cycle if retries remain
            await self._schedule_next_retry(action)

    except Exception as e:
        print(f"Retry failed for action {action.id}: {e}")
        await self._schedule_next_retry(action)
```

### Workflow Creation from Diagnosis
```python
# Source: Derived from existing ActionRecommendation pattern
class WorkflowRecommendation(BaseModel):
    """Multi-action workflow recommendation from diagnosis."""

    workflow_name: str = Field(..., description="Name for the workflow")
    description: str = Field(..., description="What this workflow accomplishes")
    actions: list[ActionRecommendation] = Field(
        ..., description="Actions to execute in order"
    )
    urgency: str = Field(default="soon")

# In executor:
async def propose_workflow(
    self,
    recommendation: WorkflowRecommendation,
    ticket_id: int | None = None,
) -> int:
    """Create a workflow from a multi-action recommendation."""
    self._safety.check_can_execute()

    # Validate all actions exist
    for action_rec in recommendation.actions:
        definition = self._registry.get_definition(action_rec.action_name)
        if definition is None:
            raise ValueError(f"Unknown action '{action_rec.action_name}'")
        validate_action_params(definition, action_rec.parameters)

    # Create proposals
    proposals = [
        ActionProposal(
            action_name=rec.action_name,
            parameters=rec.parameters,
            reason=rec.reason,
            status=ActionStatus.PROPOSED,
        )
        for rec in recommendation.actions
    ]

    # Create workflow in database
    async with ActionDB(self.db_path) as db:
        workflow_id = await db.create_workflow(
            name=recommendation.workflow_name,
            description=recommendation.description,
            actions=proposals,
            ticket_id=ticket_id,
        )

    await self._auditor.log_workflow_created(workflow_id, recommendation.workflow_name)

    return workflow_id
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| External scheduler (APScheduler) | Database-driven scheduling | 2024+ | Simpler deployment, no extra processes |
| Fixed retry delays | Exponential backoff with jitter | Standard practice | Prevents thundering herd |
| In-memory workflow state | Persistent database state | Standard practice | Survives restarts |
| Synchronous retry loops | Async retry with poll cycle | asyncio patterns | Non-blocking, scalable |

**Current industry patterns:**
- LangGraph uses state machines for workflow orchestration with built-in retry
- Temporal provides durable workflows with automatic retry and scheduling
- Prefect/Dagster use database-backed task persistence
- tenacity is the go-to library for Python retry logic

**Deprecated/outdated:**
- Synchronous retry with `time.sleep()` - use async patterns
- APScheduler for simple delays - database polling is simpler for this use case
- All-or-nothing workflow execution - partial completion with recovery is preferred

## Open Questions

Things that couldn't be fully resolved:

1. **Workflow approval granularity**
   - What we know: Phase 14 has global approval mode and per-action requires_approval
   - What's unclear: Should workflows require single approval for all actions, or per-action approval?
   - Recommendation: Single approval for entire workflow (simpler UX, atomic decision)

2. **Retry state on restart**
   - What we know: retry_count and next_retry_at are persisted
   - What's unclear: Should agent resume retries immediately on restart or respect next_retry_at?
   - Recommendation: Respect next_retry_at - if in past, retry immediately; if future, wait

3. **Scheduled action approval**
   - What we know: Scheduled actions need to be validated before scheduled_at time
   - What's unclear: Can user schedule then approve, or must approve then schedule?
   - Recommendation: Require validation before scheduling; approval can happen any time before scheduled_at

4. **Workflow cancellation semantics**
   - What we know: kill_switch cancels all pending actions
   - What's unclear: Should cancelling a workflow cancel all its actions, or just mark workflow cancelled?
   - Recommendation: Cancel workflow AND all its non-completed actions (atomic)

## Sources

### Primary (HIGH confidence)
- [Tenacity Documentation](https://tenacity.readthedocs.io/) - Retry patterns, async support, exponential backoff
- [Python asyncio Documentation](https://docs.python.org/3/library/asyncio-task.html) - Task scheduling, coroutine chaining
- Existing codebase: ActionExecutor, ActionProposal, ActionDB patterns from Phase 12-14
- [Asyncio Coroutine Chaining](https://superfastpython.com/asyncio-coroutine-chaining/) - Sequential workflow patterns

### Secondary (MEDIUM confidence)
- [LangGraph Workflows](https://docs.langchain.com/oss/python/langgraph/workflows-agents) - Multi-agent workflow patterns
- [APScheduler Documentation](https://apscheduler.readthedocs.io/en/latest/) - Database-backed scheduling patterns
- [Snappea Task Queue Design](https://www.bugsink.com/blog/snappea-design/) - SQLite as task queue

### Tertiary (LOW confidence)
- WebSearch results on workflow orchestration patterns - general guidance, not library-specific

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - tenacity is well-documented, existing libs reused
- Architecture: HIGH - Extends existing Phase 12-14 patterns naturally
- Retry patterns: HIGH - tenacity documentation is authoritative
- Workflow patterns: MEDIUM - Some design decisions remain (approval granularity)
- Database schema: HIGH - Simple extensions to existing schema

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - stable patterns)
