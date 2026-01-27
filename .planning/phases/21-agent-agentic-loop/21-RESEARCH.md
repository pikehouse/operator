# Phase 21: Agent Agentic Loop - Research

**Researched:** 2026-01-27
**Domain:** Autonomous action execution, post-action verification, agentic control flow
**Confidence:** HIGH

## Summary

This phase implements the final piece of the autonomous agent: closing the loop from diagnosis → action → verification. The research confirms that all foundational infrastructure exists from v2.0 (action framework) and v2.1 (multi-subject support). The agent can already diagnose issues and propose actions, and the executor can validate and execute actions. What's missing is the autonomous flow where the agent immediately executes proposed actions and verifies the outcome.

The primary technical requirements are:
1. Configure demo to run in EXECUTE mode (not OBSERVE mode)
2. Disable approval workflow for autonomous execution
3. Execute actions immediately after proposal (not just schedule them)
4. Wait for action effects to propagate (fixed delay approach)
5. Query subject metrics to verify fix success
6. Log verification results

Research confirms:
- **Action framework is complete**: ActionExecutor can validate and execute proposals against subjects, with fire-and-forget semantics already implemented (v2.0)
- **Approval is configurable**: ActionExecutor accepts `approval_mode` parameter (defaults to False for autonomous) and can be set via `OPERATOR_APPROVAL_MODE` env var
- **Safety modes exist**: SafetyController provides OBSERVE vs EXECUTE modes, with kill switch capability
- **Subject observation methods ready**: All subjects implement `observe()` and specific metric query methods (e.g., `get_store_metrics()`, `get_cluster_metrics()`)
- **Agent runner has executor integration**: AgentRunner accepts optional `executor` parameter and proposes actions from diagnosis, but doesn't execute them immediately

**Primary recommendation:** Extend AgentRunner to execute validated proposals immediately after creation (not just schedule them), wait 5s for effect propagation, query subject metrics via `subject.observe()`, and log verification results. Configure demo with `approval_mode=False` and `SafetyMode.EXECUTE` to enable autonomous execution.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio | stdlib | Async delays (5s wait) and concurrent operations | Project foundation for all async operations |
| operator_core.actions | internal | ActionExecutor for proposal and execution | Built in v2.0, production-ready |
| operator_core.actions.safety | internal | SafetyController for OBSERVE/EXECUTE modes | Built in v2.0 for safety controls |
| operator_protocols | internal | SubjectProtocol.observe() for verification | Built in v2.1, multi-subject support |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Verification result logging | Standard Python logging for audit trail |
| datetime | stdlib | Timestamp verification events | Already used throughout codebase |
| operator_core.db.actions | internal | ActionDB for proposal queries | Built in v2.0 for persistence |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Fixed 5s delay | Adaptive polling with timeout | Fixed delay is simpler, sufficient for demo (v2.2 scope) |
| subject.observe() | Subject-specific metric methods | observe() returns complete state, works for all subjects |
| Logging verification | Store in ActionRecord.result_data | Logging is immediate feedback, result_data for persistence |

**Installation:**
No new dependencies required - all infrastructure exists.

## Architecture Patterns

### Pattern 1: Immediate Execution After Proposal
**What:** Execute validated proposals immediately in autonomous mode, rather than waiting for approval or scheduling
**When to use:** Autonomous agent mode (EXECUTE mode, approval_mode=False)
**Example:**
```python
# Source: AgentRunner pattern extended with immediate execution
async def _propose_and_execute_actions(
    self,
    diagnosis_output: DiagnosisOutput,
    ticket_id: int,
) -> None:
    """Propose and immediately execute actions in autonomous mode."""
    if self.executor is None:
        return  # No executor - observe-only mode

    for rec in diagnosis_output.recommended_actions:
        # Propose action (validates and creates proposal)
        proposal = await self.executor.propose_action(rec, ticket_id=ticket_id)
        print(f"Proposed action: {proposal.action_name} (id={proposal.id})")

        # Validate proposal (transitions to VALIDATED status)
        await self.executor.validate_proposal(proposal.id)

        # Execute immediately (if not in approval mode)
        record = await self.executor.execute_proposal(proposal.id, self.subject)

        if record.success:
            print(f"Action {proposal.id} executed successfully")
            # Verify fix after delay
            await self._verify_action_result(proposal.id, ticket_id)
        else:
            print(f"Action {proposal.id} failed: {record.error_message}")
```

### Pattern 2: Fixed Delay Before Verification
**What:** Wait fixed duration (5s) after action execution before verifying fix
**When to use:** Fire-and-forget action semantics where effects take time to propagate
**Example:**
```python
# Source: Standard asyncio delay pattern
async def _verify_action_result(
    self,
    proposal_id: int,
    ticket_id: int,
) -> None:
    """Verify action result after fixed delay."""
    # Wait for action effects to propagate
    await asyncio.sleep(5.0)  # 5s delay per AGENT-02

    # Query subject metrics
    observation = await self.subject.observe()

    # Check if issue is resolved (simplified - real check depends on invariant)
    # Could query original invariant that triggered ticket
    is_resolved = self._check_invariant_resolved(observation, ticket_id)

    # Log verification result
    if is_resolved:
        print(f"✓ Verification passed: Action {proposal_id} resolved issue")
    else:
        print(f"✗ Verification failed: Issue persists after action {proposal_id}")
```

### Pattern 3: Subject Observation for Verification
**What:** Use SubjectProtocol.observe() to gather comprehensive metrics for verification
**When to use:** Post-action verification across different subject types
**Example:**
```python
# Source: SubjectProtocol pattern from v2.1
async def _check_invariant_resolved(
    self,
    observation: dict[str, Any],
    ticket_id: int,
) -> bool:
    """Check if invariant violation is resolved."""
    # Fetch original ticket to get invariant name
    async with TicketDB(self.db_path) as db:
        ticket = await db.get_ticket(ticket_id)

    # Re-run invariant check using same checker
    # (In full implementation, would use InvariantCheckerProtocol)
    # For demo: simplified check based on observation

    # Example: Check if latency is back under threshold
    cluster_metrics = observation.get("cluster_metrics", {})
    p99_latency = cluster_metrics.get("write_latency_p99", 0)

    # Return true if metric is healthy
    return p99_latency < 100.0  # Threshold from SLO
```

### Pattern 4: Demo Configuration for Autonomous Mode
**What:** Configure demo to run agent in EXECUTE mode with approval disabled
**When to use:** Autonomous demo requiring end-to-end action execution
**Example:**
```python
# Source: TUIDemoController pattern + ActionExecutor configuration
async def run_autonomous_demo():
    """Run demo with autonomous agent execution."""
    # Create executor with approval disabled
    auditor = ActionAuditor(db_path)
    safety = SafetyController(
        db_path,
        auditor,
        mode=SafetyMode.EXECUTE  # Enable execution
    )
    registry = ActionRegistry(subject)
    executor = ActionExecutor(
        db_path,
        registry,
        safety,
        auditor,
        approval_mode=False,  # Disable approval (autonomous)
    )

    # Create agent runner with executor
    runner = AgentRunner(
        subject=subject,
        db_path=db_path,
        executor=executor,  # Provide executor for autonomous mode
        poll_interval=5.0,
    )

    # Agent will now: diagnose → propose → execute → verify
    await runner.run()
```

### Anti-Patterns to Avoid
- **Executing before validation:** Always validate proposals before execution to catch parameter errors
- **No delay before verification:** Fire-and-forget actions need time to propagate (5s minimum)
- **Subject-specific verification:** Use SubjectProtocol.observe() for reusable verification across subjects
- **Synchronous execution:** All action execution must be async to avoid blocking agent loop

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Approval workflow bypass | Custom execute without checks | ActionExecutor with approval_mode=False | Executor handles validation, safety checks, audit logging |
| Verification polling | Custom loop with backoff | Fixed delay (5s) + observe() | Fire-and-forget semantics don't need polling, effects are eventual |
| Safety mode switching | Direct execution flag | SafetyController.set_mode() | Controller provides kill switch, audit events, graceful mode changes |
| Metric comparison | Custom threshold checks | Re-run InvariantCheckerProtocol | Invariant checkers already implement correct threshold logic |

**Key insight:** The action execution infrastructure from v2.0 already handles validation, safety checks, audit logging, and fire-and-forget execution. Don't bypass it with custom execution paths - configure it correctly (approval_mode=False) and extend the agent to use it immediately after proposal.

## Common Pitfalls

### Pitfall 1: Executing Without Validation
**What goes wrong:** Proposal execution fails if parameters are invalid, causing agent to retry indefinitely
**Why it happens:** Developer assumes propose_action() validates everything, skips explicit validate_proposal()
**How to avoid:** Always call validate_proposal() after propose_action() and before execute_proposal()
**Warning signs:** ActionProposal status stays "proposed", execution raises ValidationError

### Pitfall 2: No Delay Before Verification
**What goes wrong:** Verification runs immediately, before action effects propagate, always reports failure
**Why it happens:** Misunderstanding fire-and-forget semantics - PD API returns success before effects complete
**How to avoid:** Use fixed 5s delay (asyncio.sleep) before querying metrics for verification
**Warning signs:** Verification consistently fails even when action eventually succeeds

### Pitfall 3: Approval Mode Confusion
**What goes wrong:** Actions proposed but never executed, agent appears to "do nothing"
**Why it happens:** approval_mode defaults to reading OPERATOR_APPROVAL_MODE env var, which may be unset or "true"
**How to avoid:** Explicitly set approval_mode=False when creating ActionExecutor for autonomous demos
**Warning signs:** Proposals created with status "validated" but never transition to "executing"

### Pitfall 4: Subject Method Calls in Verification
**What goes wrong:** Verification code becomes subject-specific, breaks for other subjects
**Why it happens:** Developer uses TiKV-specific methods like get_store_metrics() instead of observe()
**How to avoid:** Use SubjectProtocol.observe() which returns complete state dict for all subjects
**Warning signs:** Verification code imports subject-specific types or calls non-protocol methods

### Pitfall 5: Missing Executor in AgentRunner
**What goes wrong:** Agent diagnoses issues but never proposes or executes actions
**Why it happens:** AgentRunner.executor is optional, defaults to None (observe-only mode)
**How to avoid:** Always provide ActionExecutor instance when creating AgentRunner for demos
**Warning signs:** Agent logs diagnosis but no "Proposed action:" messages appear

## Code Examples

Verified patterns from existing codebase:

### Example 1: Creating Executor for Autonomous Mode
```python
# Source: ActionExecutor initialization pattern
from pathlib import Path
from operator_core.actions.executor import ActionExecutor
from operator_core.actions.registry import ActionRegistry
from operator_core.actions.safety import SafetyController, SafetyMode
from operator_core.actions.audit import ActionAuditor

db_path = Path.home() / ".operator" / "operator.db"

# Create components
auditor = ActionAuditor(db_path)
safety = SafetyController(db_path, auditor, mode=SafetyMode.EXECUTE)
registry = ActionRegistry(subject)

# Create executor with approval disabled
executor = ActionExecutor(
    db_path=db_path,
    registry=registry,
    safety=safety,
    auditor=auditor,
    approval_mode=False,  # Autonomous execution
)
```

### Example 2: AgentRunner with Executor
```python
# Source: AgentRunner initialization with executor
from operator_core.agent.runner import AgentRunner

runner = AgentRunner(
    subject=subject,
    db_path=db_path,
    executor=executor,  # Enable action execution
    poll_interval=5.0,
)

# Runner will:
# 1. Poll for open tickets
# 2. Diagnose via Claude
# 3. Propose actions from diagnosis
# 4. Validate proposals
# 5. Execute immediately (if approval_mode=False)
await runner.run()
```

### Example 3: Verification After Action
```python
# Source: Pattern to add to AgentRunner
import asyncio

async def _verify_action_result(
    self,
    proposal_id: int,
    ticket_id: int,
) -> None:
    """
    Verify action resolved the issue.

    Per AGENT-02/03/04: Wait 5s, query metrics, log result.
    """
    # Wait for action effects to propagate
    await asyncio.sleep(5.0)

    # Query subject metrics
    observation = await self.subject.observe()

    # Fetch ticket to get invariant
    async with TicketDB(self.db_path) as db:
        ticket = await db.get_ticket(ticket_id)

    # Simplified verification (production would re-run checker)
    is_resolved = self._check_metrics_healthy(observation)

    # Log verification result (AGENT-04)
    if is_resolved:
        print(f"✓ VERIFICATION PASSED: Action {proposal_id} resolved ticket {ticket_id}")
        # Could update ticket status to RESOLVED
    else:
        print(f"✗ VERIFICATION FAILED: Ticket {ticket_id} issue persists")
        # Could create follow-up ticket or retry action
```

### Example 4: Immediate Execution Flow
```python
# Source: Pattern to add to AgentRunner._propose_actions_from_diagnosis
async def _propose_and_execute_actions(
    self,
    diagnosis_output: DiagnosisOutput,
    ticket_id: int,
) -> None:
    """Propose and execute actions immediately (autonomous mode)."""
    if self.executor is None:
        return  # No executor available

    for rec in diagnosis_output.recommended_actions:
        try:
            # 1. Propose action (validates params, creates proposal)
            proposal = await self.executor.propose_action(rec, ticket_id=ticket_id)
            self._actions_proposed += 1
            print(f"Proposed: {proposal.action_name} (id={proposal.id})")

            # 2. Validate proposal (transitions to VALIDATED)
            await self.executor.validate_proposal(proposal.id)
            print(f"Validated: {proposal.id}")

            # 3. Execute immediately (AGENT-01)
            record = await self.executor.execute_proposal(proposal.id, self.subject)

            if record.success:
                print(f"✓ Executed: {proposal.action_name}")
                # 4. Verify after delay (AGENT-02/03)
                await self._verify_action_result(proposal.id, ticket_id)
            else:
                print(f"✗ Execution failed: {record.error_message}")

        except Exception as e:
            print(f"Error executing action {rec.action_name}: {e}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual approval workflow | Configurable approval_mode | v2.0 (Phase 12) | Enables autonomous execution when approval_mode=False |
| Observe-only agent | Agent with optional executor | v2.0 (Phase 12) | Agent can propose and execute actions when executor provided |
| Subject-specific actions | SubjectProtocol with get_action_definitions() | v2.1 (Phase 16) | Actions work across multiple subjects |
| No verification | Fire-and-forget execution | v2.0 (Phase 12) | Actions return immediately, effects are eventual |
| TiKV-only | Multi-subject protocol | v2.1 (Phase 16) | Same agent code works for TiKV, rate limiter, future subjects |

**Deprecated/outdated:**
- **Approval required by default:** v2.0 originally defaulted to approval_mode=True, now defaults to False (autonomous) when explicitly set
- **No executor in demos:** Early demos (v1.x) only demonstrated diagnosis, not action execution
- **Synchronous verification:** Early patterns assumed immediate effect verification - fire-and-forget requires delay

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal verification delay**
   - What we know: Fire-and-forget actions take time to propagate (PD scheduler runs periodically)
   - What's unclear: Is 5s sufficient for all action types, or should drain_store wait longer?
   - Recommendation: Start with fixed 5s delay (AGENT-02), make configurable per-action in future if needed

2. **Verification success criteria**
   - What we know: Need to re-check the original invariant that triggered the ticket
   - What's unclear: Should verification re-run full InvariantCheckerProtocol, or simplified metric check?
   - Recommendation: For v2.2 demo, use simplified metric check (query observe()). Full checker integration in future phase.

3. **Multi-action verification**
   - What we know: Diagnosis can recommend multiple actions (workflows)
   - What's unclear: Verify after each action, or only after all actions complete?
   - Recommendation: For v2.2, execute and verify first recommended action only. Workflow verification in future.

4. **Failed verification handling**
   - What we know: Verification can fail if action didn't resolve issue
   - What's unclear: Retry action, escalate to human, or create follow-up ticket?
   - Recommendation: For v2.2, log failure only. Auto-retry/escalation in future phase.

## Sources

### Primary (HIGH confidence)
- ActionExecutor implementation: `/packages/operator-core/src/operator_core/actions/executor.py`
- AgentRunner implementation: `/packages/operator-core/src/operator_core/agent/runner.py`
- SafetyController implementation: `/packages/operator-core/src/operator_core/actions/safety.py`
- SubjectProtocol definition: `/packages/operator-protocols/src/operator_protocols/subject.py`
- TiKVSubject implementation: `/packages/operator-tikv/src/operator_tikv/subject.py`

### Secondary (MEDIUM confidence)
- Demo infrastructure: `/demo/tui_integration.py` - Shows current demo setup without executor
- Phase 20 research: `.planning/phases/20-e2e-demo-chaos/20-RESEARCH.md` - Multi-subject demo patterns

### Tertiary (LOW confidence)
- None - all findings verified against existing codebase implementation

## Metadata

**Confidence breakdown:**
- Action execution flow: HIGH - Complete implementation exists in ActionExecutor
- Approval mode configuration: HIGH - Explicitly documented in ActionExecutor.__init__
- Verification pattern: MEDIUM - Pattern inferred from fire-and-forget semantics and observe() method
- Demo integration: HIGH - TUIDemoController pattern established in Phase 20

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - stable codebase, minimal churn expected)
