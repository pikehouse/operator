# Phase 22: Demo Integration - Research

**Researched:** 2026-01-27
**Domain:** Demo chapter updates, narrative refinement, E2E agentic loop display
**Confidence:** HIGH

## Summary

This phase integrates the agentic loop (from Phase 21) into both TiKV and rate limiter demos by updating chapter narratives and ensuring the complete diagnosis -> action -> verification sequence is visible in the agent panel. The research confirms that all infrastructure is ready: the AgentRunner executes actions immediately after diagnosis and logs verification results, the TUIDemoController already spawns the agent subprocess with EXECUTE mode enabled, and both demos have chaos injection working.

The primary work is updating chapter narratives (in `demo/tikv.py` and `demo/ratelimiter.py`) to describe the agentic flow instead of observe-only behavior, and verifying the agent panel output shows the complete loop. No new infrastructure is needed.

Key findings:
1. **Agent output already structured for TUI**: AgentRunner prints diagnosis summary, action execution, and verification results with consistent formatting (lines 278-338 in runner.py)
2. **Demo chapters need narrative updates**: Current narratives say "observe-only" and "manual recovery" which must change to describe autonomous remediation
3. **TiKV action available**: `transfer_leader` action is implemented and registered - AI diagnosis can recommend it
4. **Rate limiter action available**: `reset_counter` action is implemented and registered - AI diagnosis can recommend it
5. **No code changes to agent infrastructure**: Phase 21 completed all agent-side work; Phase 22 is demo narrative/verification

**Primary recommendation:** Update demo chapter narratives in both `demo/tikv.py` and `demo/ratelimiter.py` to describe agentic remediation flow. Verify E2E demo shows complete loop by running both demos and observing agent panel output.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| demo.types | internal | Chapter dataclass for demo definitions | Project standard for chapter-based demos |
| demo.tui_integration | internal | TUIDemoController with 5-panel layout | Phase 20 infrastructure, production-ready |
| demo.tikv | internal | TiKV demo chapters and chaos | Phase 20 demo infrastructure |
| demo.ratelimiter | internal | Rate limiter demo chapters and chaos | Phase 20 demo infrastructure |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| demo.tikv_chaos | internal | TiKV chaos injection (node kill) | TiKV fault scenario |
| demo.ratelimiter_chaos | internal | Rate limiter chaos (counter drift) | Rate limiter fault scenario |
| Rich markup | via rich | Terminal formatting in narrations | Already used in narratives |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Chapter narration updates | On-screen annotations | Narrations are simpler, already established pattern |
| Fixed chapter order | Dynamic chapter injection | Fixed order is sufficient for demo purposes |
| Manual verification | Automated E2E tests | Manual run is faster for demo verification |

**Installation:**
No new dependencies required - all infrastructure exists.

## Architecture Patterns

### Pattern 1: Chapter Narrative Structure for Agentic Flow
**What:** Chapter narrations that explain what the agent is doing (detect, diagnose, act, verify)
**When to use:** Any chapter describing agent behavior
**Example:**
```python
# Source: demo/tikv.py pattern extended for agentic flow
Chapter(
    title="Stage 6: AI Remediation",
    narration=(
        "Claude is analyzing the violation and will act autonomously.\n\n"
        "Watch the Agent panel for:\n"
        "1. Diagnosis: root cause and recommended action\n"
        "2. Action: transfer-leader to rebalance regions\n"
        "3. Verification: metrics checked after 5s delay\n\n"
        "[dim]The agent operates in EXECUTE mode (no human approval).[/dim]"
    ),
)
```

### Pattern 2: Post-Chaos Detection Flow
**What:** Chapter narrations that explain what happens after chaos is injected
**When to use:** Detection and diagnosis chapters
**Example:**
```python
# Source: demo/ratelimiter.py pattern extended for agentic flow
Chapter(
    title="Stage 4: Detection",
    narration=(
        "Watch Monitor panel -> should show [bold red]violation detected[/bold red]\n"
        "The invariant checker detects counter drift anomaly.\n\n"
        "Next: Agent will diagnose and remediate automatically."
    ),
),
```

### Pattern 3: Agent Panel Output Verification
**What:** The agent panel shows diagnosis summary, action execution, and verification
**When to use:** Verifying E2E demo behavior
**Example output in agent panel:**
```
━━━ Ticket 1 Diagnosis ━━━
🟡 Severity: Warning

Root Cause: TiKV store tikv0 is in Down state...

Recommended: transfer_leader to redistribute leaders...

Proposed action: transfer_leader (id=1, urgency=high)
Validated: 1
✓ Executed: transfer_leader
Waiting 5s for action effects to propagate...

━━━ Verification for Action 1 ━━━
Ticket: 1
Metrics observed: 3 keys
✓ VERIFICATION COMPLETE: Action 1 executed
  (Full invariant re-check is future work)
```

### Anti-Patterns to Avoid
- **Outdated narrations:** Don't leave "observe-only" or "manual recovery" text in chapters
- **Missing action context:** Always explain what action the agent might take
- **Verification mystery:** Always explain the 5s wait before verification
- **Panel confusion:** Clarify which panel shows what (Monitor=detection, Agent=diagnosis+action)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chapter progression | Custom state machine | DemoState from demo.types | Already handles advance, progress, etc. |
| Agent output formatting | Custom print statements | Existing AgentRunner._print_diagnosis_summary | Consistent formatting already implemented |
| Panel updates | Direct layout modification | TUIDemoController._refresh_panels | Already polls subprocess buffers |
| Health display | Custom health formatter | TUIDemoController._format_health_panel | Subject-agnostic formatting exists |

**Key insight:** Phase 21 completed all agent infrastructure. Phase 22 is purely narrative updates and verification that the E2E flow works. Don't add new agent code - the loop is complete.

## Common Pitfalls

### Pitfall 1: Leaving Observe-Only Text in Narratives
**What goes wrong:** Demo narration says "observe-only" but agent actually executes actions, confusing viewers
**Why it happens:** Copy-paste from v1.x demos without updating for v2.2
**How to avoid:** Search for "observe" and "manual" in all Chapter narrations and update
**Warning signs:** Narration text contradicts what agent panel shows

### Pitfall 2: Missing Action Name in Narrative
**What goes wrong:** Viewer doesn't know what action to expect, can't verify agent executed correctly
**Why it happens:** Generic "the agent will remediate" instead of specific action name
**How to avoid:** State the expected action explicitly: "transfer_leader" for TiKV, "reset_counter" for rate limiter
**Warning signs:** Viewer asks "what is the agent doing?" during demo

### Pitfall 3: Unclear Panel Mapping
**What goes wrong:** Viewer watches wrong panel, misses the key events
**Why it happens:** Not explaining which panel shows what
**How to avoid:** Include panel references in narrations: "Watch Agent panel for..."
**Warning signs:** Viewer stares at Cluster panel when action happens in Agent panel

### Pitfall 4: Chaos Not Triggering Diagnosis
**What goes wrong:** Chaos injected but agent never diagnoses (no ticket created)
**Why it happens:** Monitor not detecting invariant violation, or agent poll interval too long
**How to avoid:** Ensure chaos creates a real violation the invariant checker detects
**Warning signs:** Agent panel shows "Found 0 open ticket(s)" repeatedly

### Pitfall 5: Action Fails Silently
**What goes wrong:** Agent proposes action but execution fails, demo appears stuck
**Why it happens:** PD API not available, or action parameters invalid
**How to avoid:** Ensure Docker Compose has all services running, verify PD API responds
**Warning signs:** "Execution failed" in agent panel, or no "Executed" message appears

## Code Examples

Verified patterns from existing codebase:

### Example 1: TiKV Chapter Narrative Update
```python
# Source: demo/tikv.py - Update Stage 6 (AI Diagnosis) for agentic flow
Chapter(
    title="Stage 6: AI Remediation",
    narration=(
        "Claude is analyzing the violation.\n\n"
        "Watch the Agent panel for the complete loop:\n"
        "1. [bold]Diagnosis[/bold]: Root cause identification\n"
        "2. [bold]Action[/bold]: transfer_leader to healthy store\n"
        "3. [bold]Verify[/bold]: Metrics checked after 5s delay\n\n"
        "[dim]Agent runs in EXECUTE mode (no approval needed).[/dim]"
    ),
)
```

### Example 2: Rate Limiter Chapter Narrative Update
```python
# Source: demo/ratelimiter.py - Update Stage 5 (AI Diagnosis) for agentic flow
Chapter(
    title="Stage 5: AI Remediation",
    narration=(
        "Watch Agent panel -> AI diagnosing and acting\n\n"
        "The agent will:\n"
        "1. Identify counter drift as root cause\n"
        "2. Execute [bold]reset_counter[/bold] action\n"
        "3. Verify counters are aligned after 5s\n\n"
        "[dim]Autonomous remediation - no human approval.[/dim]"
    ),
)
```

### Example 3: TiKV Recovery Chapter Update
```python
# Source: demo/tikv.py - Update Stage 7 (Recovery) to remove "manual" language
Chapter(
    title="Stage 7: Verification",
    narration=(
        "The agent executed the remediation action.\n"
        "Watch the Agent panel for verification result.\n\n"
        "After 5 seconds, the agent will query metrics\n"
        "and report whether the fix resolved the issue.\n\n"
        "[dim]Cluster should return to healthy state.[/dim]"
    ),
    on_enter=on_enter,  # Keep existing recovery callback
    auto_advance=True,
)
```

### Example 4: Rate Limiter Ghost Allowing Narrative
```python
# Source: demo/ratelimiter.py - Update Stage 9 (second AI Diagnosis)
Chapter(
    title="Stage 9: AI Remediation",
    narration=(
        "Watch Agent panel -> AI diagnosing ghost allowing\n\n"
        "Same autonomous loop, different anomaly:\n"
        "1. Detect: Counter exceeds limit\n"
        "2. Diagnose: Ghost allowing root cause\n"
        "3. Act: [bold]reset_counter[/bold]\n"
        "4. Verify: Counters back to normal"
    ),
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Observe-only demo | Agentic remediation demo | v2.2 (Phase 21-22) | Agent executes actions automatically |
| Manual recovery chapter | Agent-driven recovery | v2.2 (Phase 22) | No human intervention needed in demo |
| "Coming in v2" text | Action execution shown | v2.2 (Phase 22) | Demo proves full agentic capability |

**Deprecated/outdated:**
- **"[dim](Agent action execution coming in v2...)[/dim]"** - Must be removed from all chapter narratives
- **"observe-only"** language - Must be replaced with agentic flow description
- **Manual recovery references** - Recovery is now agent-driven for TiKV (rate limiter auto-recovers via Redis)

## Open Questions

Things that couldn't be fully resolved:

1. **TiKV node restart timing**
   - What we know: TiKV demo currently restarts killed node in recovery chapter
   - What's unclear: Should the restart happen before or after agent's transfer_leader?
   - Recommendation: Keep restart in recovery chapter; agent's transfer_leader rebalances while node is down, then restart brings it back for full recovery visual

2. **Rate limiter action vs auto-recovery**
   - What we know: Counter drift eventually resolves as old entries expire from sliding window
   - What's unclear: Does reset_counter provide visible benefit if counters already recovering?
   - Recommendation: Chaos injection spreads entries across 50s window; agent action (reset_counter) provides immediate fix visible in Workload panel

3. **Verification success criteria display**
   - What we know: Agent logs "VERIFICATION COMPLETE" but doesn't re-check full invariant
   - What's unclear: Should narrative explain this limitation?
   - Recommendation: Include "[dim]Full invariant re-check is future work[/dim]" matches agent output

4. **Demo timing and chapter pacing**
   - What we know: Agent poll interval is 5s, detection may take 2-10s
   - What's unclear: Optimal chapter timing to not rush past agent output
   - Recommendation: Keep manual chapter advance; presenter controls pacing

## Sources

### Primary (HIGH confidence)
- AgentRunner implementation: `/packages/operator-core/src/operator_core/agent/runner.py`
  - Lines 278-338: _propose_actions_from_diagnosis with execute + verify
  - Lines 305-341: _verify_action_result with 5s delay and output
  - Lines 470-505: _print_diagnosis_summary formatting
- TUIDemoController: `/demo/tui_integration.py`
  - Lines 159-162: EXECUTE mode environment variables
  - Lines 381-391: Agent panel output display
- TiKV demo: `/demo/tikv.py`
  - Current chapter structure and narratives
- Rate limiter demo: `/demo/ratelimiter.py`
  - Current chapter structure and narratives

### Secondary (MEDIUM confidence)
- Phase 21 verification: `.planning/phases/21-agent-agentic-loop/21-VERIFICATION.md`
  - Confirms agentic loop is complete and wired
- REQUIREMENTS.md: `.planning/REQUIREMENTS.md`
  - Defines TIKV-01/02/03 and RLIM-01/02/03 requirements

### Tertiary (LOW confidence)
- None - all findings verified against existing codebase implementation

## Metadata

**Confidence breakdown:**
- Chapter narrative patterns: HIGH - Simple text updates to existing Chapter definitions
- Agent output visibility: HIGH - Verified agent print statements format correctly
- Action availability: HIGH - Both transfer_leader and reset_counter are implemented and tested
- E2E demo flow: MEDIUM - Requires manual E2E run to fully verify timing and visibility

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - stable codebase, demo-only changes)
