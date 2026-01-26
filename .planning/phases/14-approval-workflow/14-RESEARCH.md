# Phase 14: Approval Workflow - Research

**Researched:** 2026-01-26
**Domain:** Configurable human-in-the-loop approval gate for AI agent action execution
**Confidence:** HIGH

## Summary

This phase implements a configurable approval workflow for action execution. The existing codebase from Phase 12 provides most infrastructure: `ActionProposal` lifecycle states, `ActionExecutor` with `execute_proposal`, `SafetyController` with observe/execute modes, and CLI commands for action management. The key additions are: (1) a configuration option for approval mode (on/off, default off), (2) a workflow that pauses execution at "validated" state until human approval when enabled, and (3) CLI commands to approve/reject pending actions.

The primary architectural decision is whether approval is a *separate dimension* from SafetyMode or *replaces* it. Research indicates approval should be **orthogonal** to observe-only mode: SafetyMode controls whether the agent can act at all (hard gate), while approval controls whether validated actions need human confirmation before execution (soft gate). This allows: observe-only for demos, autonomous execution for production with low-risk actions, and approval-required for high-risk operations.

Per requirements: ACT-03 (general tools with approval) and APR-01/APR-02 (configurable approval on/off, CLI approve/reject). The existing `ActionDefinition.requires_approval` field can drive per-action approval requirements, while a global `approval_mode` config enables/disables the workflow entirely.

**Primary recommendation:** Add `approval_mode: bool` to configuration (default False), implement approval gate in `ActionExecutor.execute_proposal` that checks both global mode and per-action `requires_approval`, add `operator actions approve <id>` and `operator actions reject <id>` CLI commands, persist approval state in existing `action_proposals` table via new `approved_at`/`approved_by` columns.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | 0.12+ | CLI commands for approve/reject | Already used in cli/actions.py for kill-switch/mode/list |
| pydantic | v2 | Configuration model extension | Already used for ActionProposal, consistent pattern |
| aiosqlite | 0.19+ | Async database operations | Already used in ActionDB, TicketDB |
| asyncio.Event | stdlib | Approval waiting mechanism (if implementing async wait) | Python standard, simple signaling |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | 13+ | Formatted CLI output for approval prompts | Already used in cli/actions.py for tables |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Polling in CLI | asyncio.Event with IPC | Simpler polling suffices since CLI is human-triggered, not daemon |
| Database-based approval state | In-memory with Redis | Database simpler, no new dependencies, already have ActionDB |
| Global config file | Environment variable | File more discoverable, but env vars work for container deployments |

**Installation:**
```bash
# No new dependencies - uses existing typer, pydantic, aiosqlite, rich
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/
└── src/
    └── operator_core/
        ├── actions/
        │   ├── executor.py      # Add approval gate to execute_proposal
        │   └── types.py         # Add ApprovalStatus enum (if needed)
        ├── cli/
        │   └── actions.py       # Add approve/reject commands
        ├── config.py            # Add approval_mode to config (or new ApprovalConfig)
        └── db/
            ├── actions.py       # Add approval columns/methods
            └── schema.py        # Add approved_at, approved_by, rejected_at columns
```

### Pattern 1: Approval Gate in Executor
**What:** Check approval requirements before proceeding to execution
**When to use:** In `ActionExecutor.execute_proposal` after validation check
**Example:**
```python
# Source: Existing executor.py pattern + approval extension
async def execute_proposal(
    self,
    proposal_id: int,
    subject: "Subject",
) -> ActionRecord:
    """Execute a validated proposal against the subject."""
    # Check safety mode (existing)
    self._safety.check_can_execute()

    async with ActionDB(self.db_path) as db:
        proposal = await db.get_proposal(proposal_id)

        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        # NEW: Check if approval is required and not yet approved
        if self._requires_approval(proposal):
            if not proposal.approved:
                raise ApprovalRequiredError(
                    f"Proposal {proposal_id} requires approval. "
                    f"Use 'operator actions approve {proposal_id}' to approve."
                )

        if proposal.status != ActionStatus.VALIDATED:
            raise ValueError(
                f"Proposal {proposal_id} is {proposal.status.value}, "
                "expected 'validated'"
            )

        # ... existing execution logic
```

### Pattern 2: Per-Action vs Global Approval
**What:** Two-level approval configuration - global enable and per-action requires_approval
**When to use:** Allows granular control while maintaining simple default
**Example:**
```python
# Source: Derived from existing ActionDefinition.requires_approval field
def _requires_approval(self, proposal: ActionProposal) -> bool:
    """
    Determine if proposal needs human approval.

    Approval is required when:
    1. Global approval_mode is True (APR-01), AND
    2. Either the action definition has requires_approval=True, OR
       approval_mode='all' is configured

    When global approval_mode is False (default), no approval needed.
    """
    if not self._approval_mode_enabled:
        return False  # APR-01: default off = autonomous

    # Check per-action setting from ActionDefinition
    definition = self._registry.get_definition(proposal.action_name)
    if definition and definition.requires_approval:
        return True

    # Or if configured for all actions
    if self._approval_all_actions:
        return True

    return False
```

### Pattern 3: CLI Approve/Reject Commands
**What:** Typer commands for human approval interaction
**When to use:** User approves/rejects pending actions when approval enabled
**Example:**
```python
# Source: Existing cli/actions.py patterns
@actions_app.command("approve")
def approve_action(
    proposal_id: int = typer.Argument(..., help="Proposal ID to approve"),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Approve a pending action proposal for execution."""

    async def _approve():
        path = _get_db_path(db_path)

        async with ActionDB(path) as db:
            proposal = await db.get_proposal(proposal_id)

            if not proposal:
                console.print(f"[red]Proposal {proposal_id} not found.[/red]")
                raise typer.Exit(1)

            if proposal.status != ActionStatus.VALIDATED:
                console.print(
                    f"[red]Proposal {proposal_id} is {proposal.status.value}, "
                    f"expected 'validated'.[/red]"
                )
                raise typer.Exit(1)

            await db.approve_proposal(proposal_id, approved_by="user")

            console.print(
                f"[green]Proposal {proposal_id} approved.[/green]\n"
                f"  Action: {proposal.action_name}\n"
                f"  The action will execute on next agent cycle."
            )

    asyncio.run(_approve())
```

### Pattern 4: Approval State in Database
**What:** Track approval status in action_proposals table
**When to use:** Persist approval decisions for audit trail
**Example:**
```sql
-- Source: Derived from existing schema.py ACTIONS_SCHEMA_SQL pattern
-- Add to action_proposals table:
ALTER TABLE action_proposals ADD COLUMN approved_at TEXT;
ALTER TABLE action_proposals ADD COLUMN approved_by TEXT;
ALTER TABLE action_proposals ADD COLUMN rejected_at TEXT;
ALTER TABLE action_proposals ADD COLUMN rejected_by TEXT;
ALTER TABLE action_proposals ADD COLUMN rejection_reason TEXT;
```

### Anti-Patterns to Avoid
- **Blocking the agent daemon:** Don't make AgentRunner wait synchronously for approval. Proposals should be created, then a separate CLI interaction approves. Agent continues processing other tickets.
- **Approval in observe-only mode:** Don't allow approval commands when in OBSERVE mode. Approval only makes sense when EXECUTE mode is active.
- **Losing approval state on restart:** Always persist approval decisions to database, not in-memory.
- **Requiring approval for autonomous mode:** Per APR-01, default is OFF. Don't change existing behavior unless explicitly enabled.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Approval waiting | Custom asyncio wait loop in agent | Database polling + CLI trigger | Simpler, no IPC complexity, agent daemon shouldn't block |
| Configuration storage | New config file format | Extend existing config.py patterns or use env vars | Consistency with existing project patterns |
| CLI command structure | New CLI app | Extend existing actions_app in cli/actions.py | Already has list/show/cancel/kill-switch/mode |
| Audit trail | Custom logging | Use existing ActionAuditor with new event types | Already logs lifecycle events, just add approved/rejected |

**Key insight:** The approval workflow is primarily a *state machine extension*, not a new system. The existing action lifecycle (proposed -> validated -> executing -> completed) just needs an approval checkpoint between validated and executing.

## Common Pitfalls

### Pitfall 1: Confusing Approval Mode with Safety Mode
**What goes wrong:** Treating approval_mode and SafetyMode as the same thing
**Why it happens:** Both control whether actions execute
**How to avoid:** They are orthogonal:
  - SafetyMode.OBSERVE: Agent doesn't even propose actions (hard gate)
  - SafetyMode.EXECUTE + approval_mode=False: Autonomous execution (current behavior)
  - SafetyMode.EXECUTE + approval_mode=True: Human must approve validated actions
**Warning signs:** Trying to use set_mode(OBSERVE) for approval, or approval checks blocking proposals

### Pitfall 2: Agent Blocking on Approval
**What goes wrong:** Agent daemon hangs waiting for human approval
**Why it happens:** Implementing approval as synchronous wait
**How to avoid:** Agent creates proposal -> validates -> stops. Human approves via CLI. Agent (on next cycle or via trigger) executes approved proposals.
**Warning signs:** Agent process not responding, single-threaded blocking

### Pitfall 3: Approval Without Validation
**What goes wrong:** Allowing approval of proposals that haven't been validated
**Why it happens:** Skipping validation step in approval flow
**How to avoid:** Only VALIDATED status proposals can be approved. Enforce in approve_proposal.
**Warning signs:** Executing proposals with invalid parameters

### Pitfall 4: Not Persisting Approval Decisions
**What goes wrong:** Approved action not executed after agent restart
**Why it happens:** Storing approval state only in memory
**How to avoid:** Store approved_at, approved_by in database. On startup, agent checks for approved proposals.
**Warning signs:** Actions approved but never executed after restart

### Pitfall 5: Breaking Autonomous Mode
**What goes wrong:** Requiring approval when approval_mode is disabled
**Why it happens:** Checking requires_approval without checking global approval_mode first
**How to avoid:** Global approval_mode is the primary gate. Only check per-action requires_approval when global is enabled.
**Warning signs:** Actions not executing in default configuration

## Code Examples

Verified patterns from official sources and existing codebase:

### Typer Boolean Flag for Configuration
```python
# Source: https://typer.tiangolo.com/tutorial/parameter-types/bool/
@actions_app.command("set-approval")
def set_approval_mode(
    enabled: bool = typer.Argument(
        ...,
        help="Enable (true) or disable (false) approval mode"
    ),
    db_path: Path = typer.Option(None),
) -> None:
    """Enable or disable approval mode for action execution."""
    # Store in config or environment
    ...
```

### Asyncio Event for Signaling (If Needed)
```python
# Source: Python docs - asyncio.Event
# For future enhancement: real-time approval notification
import asyncio

class ApprovalWaiter:
    def __init__(self):
        self._approved = asyncio.Event()

    async def wait_for_approval(self, timeout: float = None):
        """Wait until approved or timeout."""
        try:
            await asyncio.wait_for(self._approved.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def approve(self):
        """Signal that approval was granted."""
        self._approved.set()
```

### Database Migration Pattern
```python
# Source: Existing ActionDB pattern
async def _ensure_schema(self) -> None:
    """Create tables and indexes if they don't exist."""
    await self._conn.executescript(SCHEMA_SQL)
    await self._conn.executescript(ACTIONS_SCHEMA_SQL)

    # Add approval columns if not exist (migration)
    try:
        await self._conn.execute(
            "ALTER TABLE action_proposals ADD COLUMN approved_at TEXT"
        )
    except aiosqlite.OperationalError:
        pass  # Column already exists

    await self._conn.commit()
```

### Approval Status Check
```python
# Source: Derived from existing ActionDB patterns
async def is_approved(self, proposal_id: int) -> bool:
    """Check if a proposal has been approved."""
    async with self._conn.execute(
        "SELECT approved_at FROM action_proposals WHERE id = ?",
        (proposal_id,),
    ) as cursor:
        row = await cursor.fetchone()

    return row is not None and row["approved_at"] is not None

async def approve_proposal(
    self,
    proposal_id: int,
    approved_by: str = "user",
) -> None:
    """Mark a validated proposal as approved."""
    now = datetime.now().isoformat()

    await self._conn.execute(
        """
        UPDATE action_proposals SET
            approved_at = ?,
            approved_by = ?
        WHERE id = ? AND status = 'validated'
        """,
        (now, approved_by, proposal_id),
    )
    await self._conn.commit()
```

### ActionExecutor Approval Check
```python
# Source: Derived from existing executor.py patterns
class ApprovalRequiredError(Exception):
    """Raised when action requires approval but hasn't been approved."""

    def __init__(self, proposal_id: int, action_name: str) -> None:
        self.proposal_id = proposal_id
        self.action_name = action_name
        super().__init__(
            f"Action '{action_name}' (proposal {proposal_id}) requires approval. "
            f"Run: operator actions approve {proposal_id}"
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hard-coded approval | Configurable approval_mode | Current phase | Supports autonomous + approval workflows |
| Binary approve/reject | Approve with optional modification | LangGraph HITL 2025 | Future enhancement - allow parameter edits |
| Synchronous approval wait | Async database polling | Standard practice | Agent doesn't block on human interaction |

**Current industry patterns:**
- LangChain/LangGraph interrupt() for workflow pause/resume
- Pydantic-AI deferred tool execution for dangerous operations
- Temporal for durable approval workflows with replay
- Most organizations still maintain human oversight (per LangChain survey)

**Deprecated/outdated:**
- Blocking synchronous approval waits - use async/database state instead
- All-or-nothing approval - per-action granularity preferred

## Open Questions

Things that couldn't be fully resolved:

1. **Configuration storage location**
   - What we know: Project has config.py with dataclasses, CLI uses env vars for some settings
   - What's unclear: Whether to add approval_mode to existing SubjectConfig, new file, or env var
   - Recommendation: Use environment variable `OPERATOR_APPROVAL_MODE=true/false` for simplicity, document in CLI help. Can add config file later.

2. **Execution trigger after approval**
   - What we know: Agent runs on poll interval, CLI commands are synchronous
   - What's unclear: Should approved actions execute immediately (new CLI command) or wait for next agent cycle?
   - Recommendation: Start with next-cycle execution (simpler). Add `operator actions execute <id>` command as enhancement if immediate execution needed.

3. **ACT-03 general tools scope**
   - What we know: ACT-03 says "Agent can use general tools beyond subject-defined actions"
   - What's unclear: What general tools are in scope for Phase 14
   - Recommendation: Phase 14 focus on approval infrastructure. General tools (filesystem, shell, etc.) deferred unless explicitly in scope.

4. **Approval timeout**
   - What we know: LangGraph/Temporal support timeout for approval
   - What's unclear: Whether we need approval expiry (e.g., proposal older than X hours auto-cancelled)
   - Recommendation: Out of scope for Phase 14. Proposals stay pending until manually approved/rejected/cancelled.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `packages/operator-core/src/operator_core/actions/` - executor.py, types.py, safety.py, registry.py
- Existing codebase: `packages/operator-core/src/operator_core/cli/actions.py` - CLI patterns
- Existing codebase: `packages/operator-core/src/operator_core/db/actions.py` - ActionDB patterns
- Phase 12 VERIFICATION.md - Confirmed infrastructure exists

### Secondary (MEDIUM confidence)
- [Typer Boolean CLI Options](https://typer.tiangolo.com/tutorial/parameter-types/bool/) - Boolean flag patterns
- [Python asyncio.Event docs](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Event) - Signaling patterns
- [LangGraph Human-in-the-Loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) - Industry HITL patterns

### Tertiary (LOW confidence)
- [FlowHunt HITL Middleware](https://www.flowhunt.io/blog/human-in-the-loop-middleware-python-safe-ai-agents/) - Concept validation
- [Pydantic-DeepAgents HITL](https://deepwiki.com/vstorm-co/pydantic-deepagents/3.2-human-in-the-loop-(hitl)) - Alternative approach
- [Shubham Vora LangGraph HITL](https://shubhamvora.medium.com/dont-let-your-ai-agents-run-wild-building-a-human-in-the-loop-system-with-langgraph-0189bf0c8e20) - Implementation example

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses only existing project dependencies
- Architecture: HIGH - Extends existing patterns from Phase 12
- CLI patterns: HIGH - Follows existing cli/actions.py conventions
- Database schema: HIGH - Simple column additions to existing table
- Approval flow logic: MEDIUM - Some design decisions remain (config location, execution trigger)

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - straightforward extension of existing patterns)
