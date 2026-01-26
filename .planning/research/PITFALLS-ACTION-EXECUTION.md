# Domain Pitfalls: Adding Action Execution to TiKV Operator

**Domain:** AI-powered distributed database operator (observe-only to action-capable)
**Researched:** 2026-01-25
**Confidence:** HIGH (multiple verified sources, production incidents analyzed)

---

## Critical Pitfalls

Mistakes that cause data loss, extended outages, or require complete redesign.

---

### Pitfall 1: Unbounded Blast Radius

**What goes wrong:** An action intended to fix one TiKV node cascades to affect the entire cluster. Example: restarting a store during region migration causes quorum loss; scaling operations performed concurrently cause tombstoned stores.

**Why it happens:**
- TiKV is a distributed Raft-based system where node actions affect cluster-wide state
- PD (Placement Driver) orchestrates region distribution; actions that don't coordinate with PD can violate Raft safety
- [TiDB Operator does NOT support concurrent cluster operations](https://github.com/pingcap/tidb-operator/issues/720) - performing scale-out while scale-in is in progress can cause stores to go Tombstone unexpectedly

**Consequences:**
- Data unavailability if quorum is lost (need 2 of 3 replicas for reads/writes)
- Permanent data loss if multiple replicas fail before replication completes
- Extended recovery time as PD attempts to rebalance

**Warning Signs (How to detect early):**
- Actions executing without checking `pd-ctl store` status first
- No locking mechanism between concurrent action requests
- Actions that don't verify region health before proceeding
- Design allows multiple actions to run simultaneously

**Prevention Strategy:**
1. Implement action pre-flight checks that query PD state before execution
2. Block concurrent operations at the operator level (action queue with mutual exclusion)
3. Define per-action blast radius limits (e.g., "this action affects at most 1 store")
4. Require explicit cluster health verification before any action

**Phase to address:** Foundation phase - must be in place before ANY action executes

---

### Pitfall 2: AI Hallucination Leading to Destructive Commands

**What goes wrong:** Claude generates a plausible-sounding but incorrect tikv-ctl or pd-ctl command. The command is syntactically valid but semantically destructive (e.g., wrong store ID, incorrect region, unsafe-recover when not needed).

**Why it happens:**
- [2025 research shows hallucination is a systemic incentive issue](https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models) - LLMs are trained to generate confident responses, not calibrated uncertainty
- TiKV CLI tools have similar command patterns that are easy to confuse
- Context window limitations mean Claude may lose track of which store ID corresponds to which issue
- [Average hallucination rates are 2-5% for well-optimized models](https://www.getmaxim.ai/articles/llm-hallucination-detection-and-mitigation-best-techniques/), unacceptable for production database operations

**Consequences:**
- Executing `tikv-ctl unsafe-recover` on wrong region destroys data
- Removing wrong store from cluster causes unnecessary data migration
- Tombstoning healthy store reduces cluster capacity unexpectedly

**Warning Signs (How to detect early):**
- System design allows arbitrary command strings from Claude
- No validation that referenced entities (stores, regions) actually exist
- Claude generates different commands for same diagnosis on retry
- Action parameters not cross-checked against live cluster state

**Prevention Strategy:**
1. **Structured action outputs only** - Never execute free-form commands; require Claude to select from predefined action types with validated parameters
2. **Parameter validation layer** - All store IDs, region IDs verified against live cluster state before execution
3. **Action templates** - Claude fills in parameters for vetted command templates, never constructs raw commands
4. **Confidence thresholds** - If Claude's confidence in diagnosis is below threshold, escalate to human instead of acting

**Phase to address:** Core architecture - action type system must be designed before implementation

---

### Pitfall 3: Approval Workflow That Blocks Incident Response

**What goes wrong:** Human-in-the-loop approval becomes a bottleneck during incidents. Approver is asleep/unavailable, approval UI is too complex, or approval queue backs up during cascading failures.

**Why it happens:**
- [39% of companies report AI agents accessing unintended systems](https://skywork.ai/blog/agentic-ai-safety-best-practices-2025-enterprise/) when guardrails are bypassed due to urgency
- Well-intentioned safety becomes liability when incidents need sub-minute response
- Single approver design creates availability dependency
- [Approval fatigue leads to rubber-stamping](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo), defeating the purpose

**Consequences:**
- Incident extends while waiting for approval (SLA breach)
- Operators bypass approval system entirely ("shadow operations")
- Trust in system erodes, leading to abandonment

**Warning Signs (How to detect early):**
- All actions require same approval level regardless of risk
- Single point of failure in approval chain
- No timeout/escalation mechanism defined
- Approval UI requires context-switching away from incident

**Prevention Strategy:**
1. **Risk-tiered actions** - Low-risk actions (restart single pod) auto-approve; medium-risk require single approval; high-risk require dual approval
2. **Time-bounded escalation** - If approval not received in X minutes, escalate to backup approver or auto-approve with audit
3. **Async approval option** - [Non-blocking parallel feedback pattern](https://zapier.com/blog/human-in-the-loop/) where low-confidence actions proceed but can be reversed
4. **Pre-authorized runbooks** - Common incident patterns can be pre-approved ("if hotspot detected, allow region split")

**Phase to address:** Approval system design phase - before implementing any approval workflows

---

### Pitfall 4: No Rollback Path for Executed Actions

**What goes wrong:** Action executes successfully but causes unexpected problems. There's no way to undo it, and the system doesn't track what was done.

**Why it happens:**
- Database operations are often not reversible (can't un-delete data, can't un-compact)
- Focus on "making it work" rather than "making it recoverable"
- [Changing human behavior is less reliable than changing automated systems](https://sre.google/workbook/postmortem-culture/) - manual rollback procedures will be forgotten

**Consequences:**
- Small mistake becomes permanent damage
- Operators afraid to use system due to irreversibility
- No audit trail for compliance or post-incident analysis

**Warning Signs (How to detect early):**
- No action history/audit log in design
- Actions don't capture pre-execution state
- No documentation of which actions are reversible
- "Undo" not considered in action type design

**Prevention Strategy:**
1. **Categorize action reversibility** - Mark each action type as: reversible (with how), partially-reversible, or irreversible
2. **Automatic state snapshots** - Before irreversible actions, capture cluster state that would be needed for manual recovery
3. **Action audit log** - Every action with: what, when, why (diagnosis), who approved, outcome
4. **Compensation actions** - For each action, define the compensating action if available

**Phase to address:** Action type design phase - reversibility must be per-action-type property

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or require significant rework.

---

### Pitfall 5: Breaking Existing Observe-Only Flow

**What goes wrong:** Adding action execution breaks the working ticket creation and diagnosis flow. Regressions in monitoring, diagnosis quality degrades, or ticket creation stops working.

**Why it happens:**
- Action execution requires changes to agent state management
- New code paths interact unexpectedly with existing diagnosis logic
- Testing focuses on new features, not regression of existing ones
- [CRD schema changes can break existing resources](https://www.linkedin.com/advice/0/how-do-you-handle-versioning-compatibility-migration-issues)

**Consequences:**
- Lose working observe-only functionality during transition
- Users distrust system if basic features regress
- Extended timeline as regressions are discovered and fixed

**Warning Signs (How to detect early):**
- Architecture requires changing diagnosis flow to add actions
- No test coverage for existing ticket creation flow
- "Big bang" migration plan instead of incremental
- No feature flag or rollback mechanism

**Prevention Strategy:**
1. **Additive architecture** - Action execution as new capability layered on, not refactor of existing
2. **Feature flags** - Ability to disable action execution and fall back to observe-only
3. **Regression test suite** - Automated tests for existing functionality run before any merge
4. **Parallel operation** - Run new action-capable system alongside old observe-only initially

**Phase to address:** Architecture design phase - before any implementation begins

---

### Pitfall 6: Testing Actions Only in Non-Production Environments

**What goes wrong:** Actions work perfectly in staging but fail or behave differently in production. Staging doesn't have same scale, data patterns, or failure modes.

**Why it happens:**
- [Always start small in dev and sandbox environments](https://medium.com/@anuradhapal818/ai-for-chaos-engineering-proactively-testing-system-resilience-in-2025-78662de4cf66) is good advice, but stopping there is the pitfall
- Production TiKV clusters have different: region counts, hotspot patterns, network latency, concurrent load
- Staging can't replicate real incidents
- Fear of testing in production leads to untested production code

**Consequences:**
- First real use of action is during actual incident (worst time to discover bugs)
- False confidence from staging tests
- Actions that work at small scale fail at production scale

**Warning Signs (How to detect early):**
- No plan for production validation
- Staging cluster significantly smaller than production
- Actions tested only with happy-path scenarios
- No chaos engineering or fault injection in test plan

**Prevention Strategy:**
1. **Production dry-run mode** - Actions can be "executed" in production but only log what would happen
2. **Chaos engineering integration** - [Use tools like LitmusChaos to inject failures](https://github.com/chaosync-org/awesome-ai-agent-testing) and test action response
3. **Canary actions** - Test new action types on subset of production clusters first
4. **Synthetic incident injection** - Create controlled production issues to validate action response

**Phase to address:** Testing strategy phase - define production validation approach early

---

### Pitfall 7: Overprivileged Operator RBAC

**What goes wrong:** Operator has cluster-admin or broad permissions to execute any action. Single compromise or bug can affect entire cluster.

**Why it happens:**
- [Operators with cluster-admin become single point of failure](https://www.redhat.com/en/blog/kubernetes-operators-good-security-practices)
- Easier to grant broad permissions than figure out minimum required
- Permissions creep as new action types are added
- [59 of 66 Kubernetes CVEs stemmed from ecosystem tools](https://snyk.io/blog/security-implications-of-kubernetes-operators/), not core K8s

**Consequences:**
- Bug in operator can damage entire cluster
- Security vulnerability has maximum blast radius
- Compliance issues in regulated environments

**Warning Signs (How to detect early):**
- Single service account for all operator functions
- ClusterRole with `*` verbs or resources
- No documentation of required permissions per action
- Permissions not reviewed since initial setup

**Prevention Strategy:**
1. **Least privilege per action** - Each action type has minimum RBAC documented and enforced
2. **Separate service accounts** - Different credentials for read (diagnosis) vs write (action) operations
3. **Namespace scoping** - Where possible, scope permissions to specific namespaces
4. **Regular RBAC audit** - Review permissions quarterly, remove unused

**Phase to address:** Security design phase - define RBAC strategy before implementation

---

### Pitfall 8: Demo Mode That Becomes Production Backdoor

**What goes wrong:** Demo/simulation mode that bypasses safety checks gets accidentally enabled in production, or demo credentials leak into production config.

**Why it happens:**
- Need to demonstrate actions without approval delays in demos
- Demo mode implemented as "skip all checks" flag
- Environment detection is fragile or bypassable
- Demo and production share configuration patterns

**Consequences:**
- Actions execute in production without approval
- Safety guardrails bypassed
- Audit log shows demo mode enabled but no one noticed

**Warning Signs (How to detect early):**
- Demo mode is runtime flag in production binary
- Same configuration file used for demo and production
- Demo mode disables logging or audit
- No visual distinction between demo and production

**Prevention Strategy:**
1. **Demo as separate deployment** - Demo mode is different binary/config, not a flag
2. **No shared credentials** - Demo environment has completely different auth
3. **Compile-time separation** - Demo features not present in production build
4. **Prominent UI indication** - Demo mode has unmistakable visual indicator

**Phase to address:** Demo strategy phase - design demo approach before building demo features

---

### Pitfall 9: State Machine Complexity Explosion

**What goes wrong:** Action lifecycle (proposed -> approved -> executing -> completed/failed) interacts badly with ticket state, diagnosis state, and cluster state. Edge cases multiply and bugs emerge from state combinations.

**Why it happens:**
- Multiple independent state machines (ticket, diagnosis, action, cluster) must stay synchronized
- Failure at any point leaves system in inconsistent state
- Concurrent actions create race conditions
- Original observe-only system didn't need this complexity

**Consequences:**
- Actions stuck in "executing" forever after crash
- Tickets show wrong action status
- Cluster state changes invalidate pending actions
- Difficult to debug or recover from inconsistent states

**Warning Signs (How to detect early):**
- Action states stored in multiple places (ticket, database, memory)
- No single source of truth for action lifecycle
- State transitions not atomic
- Recovery from crash/restart not explicitly designed

**Prevention Strategy:**
1. **Single state store** - All action state in one place (likely database)
2. **State machine library** - Use explicit state machine with defined transitions
3. **Idempotent actions** - Actions can be safely retried without side effects
4. **Crash recovery protocol** - On restart, scan for in-progress actions and resolve them

**Phase to address:** Action lifecycle design phase - before implementing action execution

---

## Minor Pitfalls

Mistakes that cause friction or annoyance but are fixable without major rework.

---

### Pitfall 10: Action Results Not Visible in Ticket

**What goes wrong:** Action executes but ticket/diagnosis flow doesn't show what was done or the outcome. Operators have to check multiple systems to understand what happened.

**Why it happens:**
- Action execution built as separate system from ticketing
- Focus on "did it work" not "can humans understand what happened"
- Async action completion not integrated with ticket updates

**Warning Signs:**
- Ticket schema doesn't have fields for action results
- Action system logs to separate location from ticket history
- No notification when action completes

**Prevention Strategy:**
1. Action results automatically appended to originating ticket
2. Include: action taken, parameters, outcome, duration, any errors
3. Link to detailed logs for forensics

**Phase to address:** Integration phase - when connecting actions to existing ticket flow

---

### Pitfall 11: Timeout Handling Ambiguity

**What goes wrong:** Action times out but it's unclear if it partially executed, fully executed but response was lost, or never started.

**Why it happens:**
- Network timeouts don't indicate execution state
- TiKV operations can be slow (compaction, region migration)
- No idempotency design for actions

**Warning Signs:**
- No action execution tracking independent of response
- Timeout just means "give up" rather than "investigate"
- Same action can be triggered multiple times by retries

**Prevention Strategy:**
1. Design actions to be idempotent where possible
2. Implement action status tracking independent of response
3. Clear timeout states: "timed out, definitely did not run" vs "timed out, may have run"

**Phase to address:** Action execution design - timeout semantics per action type

---

### Pitfall 12: Alert Fatigue from Action Notifications

**What goes wrong:** Every action generates notifications. Operators tune out and miss important ones.

**Why it happens:**
- Default to notifying on everything
- No distinction between routine and exceptional
- Multiple notification channels not coordinated

**Warning Signs:**
- Same notification format for all action types
- No configuration for notification preferences
- Operators asking "can we turn these off?"

**Prevention Strategy:**
1. Notification tiers: routine (log only), notable (single channel), critical (all channels)
2. Aggregate routine actions in periodic summary
3. Only alert on failures or unexpected outcomes

**Phase to address:** Notification design - when building approval/notification system

---

## TiKV-Specific Pitfalls

---

### Pitfall 13: Region Leader Transfer During Active Writes

**What goes wrong:** Action transfers region leader while writes are in-flight, causing client-visible errors or timeouts.

**Why it happens:**
- Leader transfer is "safe" from data perspective but not from latency perspective
- Action doesn't wait for write quiescence
- TiKV client retry logic may not handle leader change gracefully

**Warning Signs:**
- Actions don't check region write activity before executing
- No coordination with application layer
- Test environment has no realistic write load

**Prevention Strategy:**
1. Pre-check region write rate before transfer
2. Consider maintenance windows for certain actions
3. Document expected client impact per action type

**Phase to address:** TiKV integration phase - when implementing TiKV-specific actions

---

### Pitfall 14: PD Scheduler Conflict

**What goes wrong:** Operator action and PD scheduler both try to move regions simultaneously. Creates thrashing or suboptimal placement.

**Why it happens:**
- PD runs background scheduling (balance, scatter, etc.)
- Operator action may conflict with PD's current plan
- No coordination protocol between operator and PD

**Warning Signs:**
- Actions don't query PD operator status before executing
- Post-action region distribution is unexpected
- Repeated region movements after action completes

**Prevention Strategy:**
1. Query PD for pending/running operators before action
2. Consider temporarily disabling relevant PD schedulers during action
3. Wait for PD to reach steady state before taking action

**Phase to address:** TiKV integration phase - PD coordination design

---

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|---------------|------------|
| Architecture Design | Breaking observe-only flow | Additive design, feature flags |
| Architecture Design | State machine complexity | Single state store, explicit FSM |
| Action Type Design | No rollback path | Reversibility as required property |
| Action Type Design | AI hallucination risk | Structured outputs, parameter validation |
| Approval System | Blocking workflow | Risk-tiered approvals, timeouts |
| Security Design | Overprivileged RBAC | Least privilege per action type |
| Testing Strategy | Staging-only testing | Production dry-run, chaos engineering |
| Demo Features | Demo becomes backdoor | Separate deployment, no shared config |
| Integration | Results not in ticket | Automatic ticket updates |
| Foundation | Unbounded blast radius | Pre-flight checks, action queue |
| TiKV Integration | PD scheduler conflicts | Query PD state, coordinate actions |

---

## Risk Matrix

| Pitfall | Likelihood | Impact | Risk Score | When to Address |
|---------|------------|--------|------------|-----------------|
| Unbounded Blast Radius | High | Critical | CRITICAL | Phase 1 |
| AI Hallucination | Medium | Critical | HIGH | Phase 1 |
| Approval Blocks Response | High | High | HIGH | Phase 2 |
| No Rollback Path | Medium | High | HIGH | Phase 1 |
| State Machine Complexity | High | High | HIGH | Phase 1 |
| Breaking Observe-Only | Medium | Medium | MEDIUM | Phase 1 |
| Staging-Only Testing | High | Medium | MEDIUM | Phase 3 |
| Overprivileged RBAC | Medium | High | MEDIUM | Phase 1 |
| Demo Backdoor | Low | High | MEDIUM | Phase 4 |
| PD Scheduler Conflict | Medium | Medium | MEDIUM | Phase 2 |
| Results Not Visible | High | Low | LOW | Phase 2 |
| Timeout Ambiguity | Medium | Low | LOW | Phase 2 |
| Alert Fatigue | High | Low | LOW | Phase 3 |
| Leader Transfer Issues | Low | Medium | LOW | Phase 2 |

---

## Integration with Existing System Checklist

Before implementing action execution, verify these integration points won't break:

### Ticket System Integration
- [ ] Ticket creation still works when action execution is disabled
- [ ] Ticket schema changes are backwards compatible
- [ ] Existing tickets don't break when action fields are added

### Agent Diagnosis Integration
- [ ] Diagnosis can complete without proposing action (maintain observe-only capability)
- [ ] Action proposal is additive to diagnosis, not replacing it
- [ ] Claude prompt changes don't regress diagnosis quality

### Monitor Integration
- [ ] Monitor still detects incidents when agent isn't responding
- [ ] Action execution failure doesn't stop monitoring
- [ ] Metrics collection continues during action execution

### Demo (TUI) Integration
- [ ] Demo mode can simulate actions without real execution
- [ ] Existing demo scenarios still work
- [ ] New action scenarios are clearly distinguishable

---

## Recommended Phase Gates

Before proceeding to each phase, verify previous phase addressed its pitfalls:

### Gate 1: Architecture Complete
- [ ] Action type system designed (prevents hallucination)
- [ ] State machine designed (prevents complexity explosion)
- [ ] Feature flags in place (prevents breaking observe-only)
- [ ] RBAC strategy documented (prevents overprivilege)

### Gate 2: Core Actions Working
- [ ] Blast radius controls implemented
- [ ] Pre-flight checks working
- [ ] Audit logging captures all actions
- [ ] At least one reversible and one irreversible action implemented

### Gate 3: Approval System Complete
- [ ] Risk tiers defined and enforced
- [ ] Timeout/escalation working
- [ ] Approval doesn't block incident response
- [ ] Demo mode clearly separated

### Gate 4: Production Ready
- [ ] Dry-run mode tested in production
- [ ] Chaos engineering validated actions
- [ ] Rollback procedures documented
- [ ] All pitfalls have mitigations in place

---

## Sources

### Kubernetes Operator Security
- [Red Hat: Kubernetes Operators Security Practices](https://www.redhat.com/en/blog/kubernetes-operators-good-security-practices)
- [Snyk: Security Implications of Kubernetes Operators](https://snyk.io/blog/security-implications-of-kubernetes-operators/)
- [Kubernetes Blog: Seven Common Pitfalls](https://kubernetes.io/blog/2025/10/20/seven-kubernetes-pitfalls-and-how-to-avoid/)

### AI Agent Safety
- [Skywork: Agentic AI Safety Best Practices 2025](https://skywork.ai/blog/agentic-ai-safety-best-practices-2025-enterprise/)
- [Dextra Labs: Agentic AI Safety Playbook](https://dextralabs.com/blog/agentic-ai-safety-playbook-guardrails-permissions-auditability/)
- [Toloka: Essential AI Agent Guardrails](https://toloka.ai/blog/essential-ai-agent-guardrails-for-safe-and-ethical-implementation/)

### Human-in-the-Loop Patterns
- [Permit.io: HITL Best Practices](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo)
- [Zapier: Human-in-the-Loop Patterns](https://zapier.com/blog/human-in-the-loop/)
- [Orkes: HITL in Agentic Workflows](https://orkes.io/blog/human-in-the-loop/)

### TiKV-Specific
- [TiDB Operator Concurrent Operations Issue](https://github.com/pingcap/tidb-operator/issues/720)
- [TiKV Production Deployment](https://tikv.org/docs/5.1/deploy/install/production/)

### LLM Hallucination
- [Lakera: Guide to LLM Hallucinations](https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models)
- [vLLM: HaluGate Detection](https://blog.vllm.ai/2025/12/14/halugate.html)
- [Maxim: LLM Hallucination Detection](https://www.getmaxim.ai/articles/llm-hallucination-detection-and-mitigation-best-techniques/)

### Testing and Chaos Engineering
- [Chaos Engineering AI Testing Resources](https://github.com/chaosync-org/awesome-ai-agent-testing)
- [Google SRE: Postmortem Culture](https://sre.google/workbook/postmortem-culture/)

### Database Incidents
- [Clerk: Database Incident Postmortem 2025](https://clerk.com/blog/2025-09-18-database-incident-postmortem)
