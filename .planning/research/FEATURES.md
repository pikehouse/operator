# Feature Landscape: Agent Action Execution

**Domain:** AI-powered distributed systems operator with action execution
**Researched:** 2026-01-25
**Confidence:** HIGH (verified against PD API docs, Kubernetes operator patterns, AIOps best practices)

## Context

This research addresses the v2.0 milestone: enabling the AI agent to execute actions on TiKV clusters, not just observe and recommend. The existing v1.0 system already has:

- Subject adapter interface with action method signatures (transfer_leader, split_region, etc.)
- PD API client for cluster observation
- AI diagnosis producing structured recommendations
- Monitor loop detecting invariant violations

The gap: actions are defined in the Subject Protocol but not implemented or executed.

---

## Table Stakes

Features users expect from any autonomous operator with action execution. Missing any of these makes the system unsafe or unusable in production.

### Action Framework

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Action type registry** | Operators need a defined vocabulary of actions. Without it, the AI can't specify what to do in a structured way. Every Kubernetes operator defines CRDs; we need action types. | Low | Existing `Subject` Protocol |
| **Action validation before execution** | Prevent invalid actions (e.g., transfer leader to non-existent store). This is basic safety - don't execute garbage. | Low | PD API client for validation |
| **Action result tracking** | Know if an action succeeded, failed, or is pending. Without this, the operator is blind to its own effects. | Low | Ticket database |
| **Action timeout handling** | PD operations can hang. Without timeouts, the operator blocks forever. | Low | asyncio timeout patterns |
| **Idempotency awareness** | Re-executing "transfer leader to store 2" when leader is already on store 2 should be a no-op. Prevents unnecessary churn. | Medium | State checking before action |

### PD API Actions

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Leader transfer execution** | The most common rebalancing action. `operator add transfer-leader <region_id> <store_id>` via PD API. | Low | PDClient, existing Subject interface |
| **Region peer scheduling** | Move replicas between stores. `operator add transfer-peer <region_id> <from> <to>`. Required for node evacuation. | Medium | PDClient |
| **Store drain initiation** | Mark store offline to evacuate regions. Essential for maintenance. | Low | PDClient |
| **Scheduler limit adjustment** | Control rebalancing speed. Useful during incidents to prevent cascading changes. | Low | PDClient config API |

### Dry-Run Mode

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Dry-run flag for all actions** | Show what would happen without doing it. Every serious infrastructure tool has this (Terraform, Pulumi, kubectl). | Low | Action type system |
| **Dry-run output with expected changes** | Not just "would transfer leader" but "would transfer region 123 leader from store 1 to store 2, affecting 0.3% of traffic". | Medium | Metrics integration |
| **Dry-run as default mode** | New operators should default to safe behavior. Explicit opt-in to execution. | Low | Config/CLI flag |

### Approval Workflow

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Human approval gate** | High-risk actions require human confirmation before execution. This is the "critical safety lock" on autonomy per AIOps best practices. | Medium | CLI interaction, state machine |
| **Approval timeout with auto-decline** | Pending approvals can't wait forever. If no response in N minutes, treat as declined. | Low | Timer logic |
| **Approval context display** | Show the human what they're approving: action, reasoning, expected impact, risk level. | Low | Rich formatting |
| **Approval audit trail** | Who approved what, when. Required for compliance and post-incident review. | Low | Ticket database, logging |

### Safety Mechanisms

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Action rate limiting** | Don't execute 100 leader transfers per second. Cluster stability requires pacing. | Low | Rate limiter |
| **Blast radius limits** | "Don't affect more than X% of regions in one action batch." Prevents cascading failures. | Medium | Impact estimation |
| **Kill switch** | Immediate halt of all pending actions. Every autonomous system needs an emergency stop. | Low | Global flag |
| **Rollback for reversible actions** | If transfer-leader fails partway, undo what was done. | High | Compensating transactions |

---

## Differentiators

Features that set this operator apart from basic automation. These create competitive advantage and demonstrate AI sophistication.

### Intelligent Action Planning

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| **Action dependency ordering** | "Split region first, then transfer leader" - AI understands action prerequisites. Most operators execute blind sequences. | Medium | Action graph analysis |
| **Multi-step action plans** | AI proposes a sequence: "1. Reduce schedule limit, 2. Drain store 3, 3. Restore schedule limit." More sophisticated than single actions. | Medium | Plan representation |
| **Impact prediction** | "This action will reduce latency by ~15% based on similar past situations." Moves beyond "what" to "why this will help." | High | Historical analysis, ML |
| **Action alternatives comparison** | "Option A: Transfer leaders (fast, low risk). Option B: Split hot regions (slower, addresses root cause). Recommending A because incident is ongoing." | Medium | Multi-option diagnosis |

### Confidence-Based Autonomy

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| **Graduated autonomy levels** | Level 1: Human approves every action. Level 2: Auto-approve low-risk. Level 3: Full autopilot. Aligns with Kubernetes Operator Capability Levels. | Medium | Risk classification |
| **Risk-based approval routing** | Low-risk: auto-approve. Medium-risk: notify and proceed unless vetoed. High-risk: require explicit approval. | Medium | Risk scoring |
| **Confidence threshold for action** | "I'm 95% confident this is the right action" vs "I'm 60% confident, please review." AI self-assesses. | Low | Structured diagnosis output |
| **Learning from approval decisions** | If humans consistently reject certain actions, adjust future recommendations. | High | Feedback loop, ML |

### Operational Intelligence

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| **Action timing optimization** | "Wait 30 seconds - a leader transfer is already in progress. Executing now would interfere." | Medium | Cluster state awareness |
| **Maintenance window awareness** | "It's 3am Sunday - approved time for aggressive rebalancing." vs "Peak traffic hours - conservative mode." | Low | Config, time awareness |
| **Cascading effect detection** | "This action might trigger automatic PD scheduling. Account for that." | High | PD behavior modeling |
| **Post-action verification** | After executing, verify the expected outcome occurred. If not, diagnose why. | Medium | State comparison |

### Integration Patterns

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| **Slack/PagerDuty approval integration** | Approve actions from where on-call engineers already work. Better UX than switching to CLI. | Medium | Webhook integration |
| **GitOps action proposals** | Propose actions as PRs to a config repo. Merge = approve. Full audit trail via git. | High | Git integration |
| **Runbook attachment** | "This action follows runbook RB-123: TiKV Node Drain Procedure." Links AI actions to documented procedures. | Low | Runbook registry |

---

## Anti-Features

Things to deliberately NOT build. These either add complexity without value, violate safety principles, or contradict the design philosophy.

### Avoid: Fully Autonomous Mode Without Guardrails

- **Why not:** The research consistently emphasizes human-in-the-loop as "the critical safety lock." Autonomous systems that can make unlimited changes to production without any human oversight are recipes for cascading failures.
- **What instead:** Graduated autonomy with clear boundaries. Even "Level 5 Autopilot" operators have emergency overrides and audit trails.

### Avoid: Complex Undo/Rollback for All Actions

- **Why not:** Not all actions are reversible. Leader transfer can be undone, but region split cannot (easily). Promising rollback creates false confidence. The SAGA pattern shows that some transactions are "pivot points" after which compensation is impossible.
- **What instead:** Clearly classify actions as reversible/irreversible. For reversible actions, implement targeted rollback. For irreversible, require higher approval thresholds.

### Avoid: Real-Time Action Streaming to TUI

- **Why not:** Showing every PD operator add command scrolling by creates noise, not insight. The TUI should show outcomes, not implementation details.
- **What instead:** Show action summaries ("Transferred 3 leaders") and state changes (store health improvement). Log details for post-incident review.

### Avoid: Custom Action DSL

- **Why not:** Creating a new language for expressing actions adds learning curve without benefit. The existing PD API commands are well-documented. Custom DSLs create maintenance burden.
- **What instead:** Use structured Python/JSON action types that map directly to PD API operations. Transparent, not clever.

### Avoid: Action Batching Across Multiple Clusters

- **Why not:** Cross-cluster operations introduce distributed transaction complexity. Each cluster has its own state, and coordinating actions across them is a different (much harder) problem.
- **What instead:** Single-cluster scope per operator instance. Multi-cluster coordination is a higher-level concern for future work.

### Avoid: ML-Based Action Selection Without Explanation

- **Why not:** "The model said do this" is not acceptable justification for production changes. The core value prop is AI that explains its reasoning.
- **What instead:** All AI-selected actions must include reasoning chain. If the AI can't explain why, it shouldn't recommend.

### Avoid: Blocking Approval UI

- **Why not:** If the operator blocks waiting for approval, the system becomes unresponsive. Meanwhile, new issues might arise.
- **What instead:** Asynchronous approval flow. Pending approvals are queued, the operator continues monitoring, and approved actions execute when safe.

### Avoid: Automatic PD Scheduler Override

- **Why not:** PD has its own schedulers (balance-region, balance-leader, hot-region). Overriding them without understanding creates conflicts. The operator should complement PD scheduling, not fight it.
- **What instead:** Understand when manual intervention is needed vs. when PD will handle it. Actions for situations PD doesn't address (e.g., AI-detected anomalies requiring specific responses).

---

## Feature Dependencies

Understanding which features depend on which existing capabilities.

```
Existing v1.0 Features:
  Subject Protocol (actions defined) ─────┐
  PDClient (observation) ─────────────────┤
  Ticket Database ────────────────────────┤
  AI Diagnosis (structured output) ───────┤
  Monitor Loop ───────────────────────────┘
                                          │
                                          v
                          ┌───────────────────────────┐
                          │   Action Type Registry    │
                          │   (New in v2.0)           │
                          └───────────────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
              v                           v                           v
    ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
    │  PD API Actions │       │   Dry-Run Mode  │       │ Approval System │
    │  (implements)   │       │   (wraps)       │       │ (gates)         │
    └─────────────────┘       └─────────────────┘       └─────────────────┘
              │                           │                           │
              └───────────────────────────┼───────────────────────────┘
                                          │
                                          v
                          ┌───────────────────────────┐
                          │   Action Executor         │
                          │   (orchestrates all)      │
                          └───────────────────────────┘
                                          │
                                          v
                          ┌───────────────────────────┐
                          │   Safety Layer            │
                          │   (rate limits, blast     │
                          │    radius, kill switch)   │
                          └───────────────────────────┘
```

### Build Order Implications

1. **Action Type Registry** - Foundation, enables all else
2. **PD API Action Implementation** - Requires registry, uses existing PDClient
3. **Dry-Run Mode** - Wraps action execution, relatively independent
4. **Approval System** - Can be built in parallel with actions
5. **Action Executor** - Integrates all above
6. **Safety Layer** - Final integration, wraps executor

---

## TiKV/PD-Specific Considerations

### PD Operator Commands

Based on [PD Control documentation](https://docs.pingcap.com/tidb/stable/pd-control/), the key operators:

| Command | What It Does | Timing |
|---------|--------------|--------|
| `operator add transfer-leader <region_id> <store_id>` | Move leader to specified store | Milliseconds (no snapshot) |
| `operator add transfer-peer <region_id> <from_store> <to_store>` | Move replica between stores | Tens of seconds (involves snapshot) |
| `operator add add-peer <region_id> <store_id>` | Add replica to store | Tens of seconds |
| `operator add remove-peer <region_id> <store_id>` | Remove replica from store | Milliseconds |
| `operator add split-region <region_id>` | Split region in half | Varies |

### Scheduling Limits

| Config | Purpose | Default |
|--------|---------|---------|
| `leader-schedule-limit` | Max leader transfers per cycle | 4 |
| `region-schedule-limit` | Max region moves per cycle | 2048 |
| `replica-schedule-limit` | Max replica changes per cycle | 64 |

These limits affect how fast the operator can execute actions. Understanding them is important for action timing.

### Hot Region Handling

The `balance-hot-region-scheduler` runs automatically. Before manually intervening on hot regions:
1. Check if PD is already addressing it
2. Check `hot-region-cache-hits-threshold` (how long before PD acts)
3. Manual intervention for immediate response, let PD handle gradual rebalancing

---

## MVP Recommendation

For v2.0 action execution milestone:

### Must Have (Table Stakes)

1. **Action type registry** with transfer-leader, transfer-peer, drain-store
2. **PD API action implementation** for the three core actions
3. **Dry-run mode** as the default
4. **Human approval gate** for all actions initially
5. **Action result tracking** in ticket database
6. **Kill switch** to halt all actions
7. **Basic rate limiting** (1 action per N seconds)

### Should Have (High-Impact Differentiators)

8. **Confidence-based approval routing** (high confidence = notify, low = require approval)
9. **Action validation** before execution
10. **Post-action verification** to confirm expected outcome

### Can Defer

- Multi-step action plans (v2.1)
- Slack/PagerDuty integration (v2.1)
- Impact prediction with historical data (v2.2)
- Graduated autonomy levels beyond binary (v2.2)
- GitOps action proposals (v3.0)

### Out of Scope for v2.0

- Automatic PD scheduler integration
- Cross-cluster operations
- ML-based action selection
- Complex rollback/compensation

---

## Sources

### TiKV/PD Documentation

- [PD Scheduling Introduction](https://github.com/tikv/pd/wiki/Scheduling-Introduction) - How PD scheduling works
- [PD Control User Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - pd-ctl command reference
- [Best Practices for PD Scheduling](https://docs.pingcap.com/tidb/stable/pd-scheduling-best-practices/) - Scheduling configuration
- [Balance Scheduling](https://github.com/tikv/pd/wiki/Balance-Scheduling) - Leader and region balancing

### Kubernetes Operator Patterns

- [Operator Capability Levels](https://sdk.operatorframework.io/docs/overview/operator-capabilities/) - Level 1-5 maturity model
- [Kubernetes Operators in 2025](https://outerbyte.com/kubernetes-operators-2025-guide/) - Current best practices
- [Portworx Action Approvals](https://docs.portworx.com/portworx-enterprise/operations/operate-kubernetes/autopilot/how-to-use/approvals/walkthrough) - Approval workflow pattern

### AIOps and Human-in-the-Loop

- [Human-in-the-Loop for AI Agents](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo) - HITL best practices
- [Agentic AIOps Human-in-the-Loop Workflows](https://dzone.com/articles/agentic-aiops-human-in-the-loop-workflows) - AIOps-specific HITL
- [Human-in-the-Loop in AI Workflows](https://zapier.com/blog/human-in-the-loop/) - Approval patterns

### Dry-Run and Safety Patterns

- [Pulumi Kubernetes Operator Preview Mode](https://www.pulumi.com/blog/pulumi-kubernetes-operator-2-3/) - Dry-run implementation
- [MongoDB Atlas Operator Dry Run](https://www.mongodb.com/docs/atlas/operator/current/ak8so-dry-run/) - Event-based dry-run
- [Chaos Toolkit Execution Flow](https://chaostoolkit.org/reference/tutorials/run-flow/) - Rollback strategies

### Rollback and Recovery

- [SAGA Design Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga) - Compensating transactions
- [Runbook Automation Best Practices](https://engini.io/blog/runbook-automation/) - Audit trails
