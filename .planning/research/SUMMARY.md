# Project Research Summary

**Project:** Operator v2.0 - Agent Action Execution
**Domain:** AI-powered distributed database operator (observe-only to action-capable)
**Researched:** 2026-01-25
**Confidence:** HIGH

## Executive Summary

The v2.0 milestone adds action execution to the existing observe-only TiKV operator. Research shows this transition is remarkably clean: the existing stack (httpx, Pydantic, aiosqlite) already provides everything needed. No new dependencies required. The Subject Protocol already defines action method signatures (transfer_leader, split_region, etc.) - they just need implementation. The core challenge is not technical capability but safety: preventing AI hallucinations from executing destructive commands, managing approval workflows that don't block incident response, and limiting blast radius.

The recommended architecture is additive, not a refactor. Action execution layers on top of existing diagnosis flow: after Claude produces a diagnosis with a recommended action, the system creates an ActionProposal that awaits human approval. Once approved, the ActionExecutor calls PD API endpoints via extended PDClient methods. This preserves the working observe-only functionality while adding controlled action capability. The design uses structured action types (preventing hallucinations), risk-tiered approval (preventing bottlenecks), and comprehensive audit trails (enabling rollback guidance).

Critical risks center on unbounded blast radius and state management complexity. Without pre-flight checks and action queuing, a single action could cascade cluster-wide. Without proper state machine design, actions get stuck in "executing" forever after crashes. The mitigation strategy prioritizes safety gates at the foundation layer before implementing any actual execution. Dry-run mode enables production validation without risk. The research confidence is high because PD API endpoints are well-documented in official sources, and the action execution patterns are verified against multiple production operator implementations.

## Key Findings

### Recommended Stack

The existing stack requires no additions for v2.0. Python 3.11+, httpx (async HTTP), Pydantic (validation), and aiosqlite (audit storage) already handle action execution needs. httpx supports POST methods for PD API operators and config changes. Pydantic models extend naturally to ActionProposal and ActionResult. The tickets database extends to store action proposals and execution records.

**Core technologies:**
- httpx >=0.27.0: Async HTTP client for PD API — already in use for GET endpoints, extend for POST
- Pydantic >=2.0.0: Data validation for action models — already used for DiagnosisOutput, pattern applies to actions
- aiosqlite >=0.20.0: Async SQLite for action audit — existing TicketDB extends to action_proposals and action_records tables

**What NOT to add:**
- drypy/dryable: Global state pattern doesn't fit method-based actions. Simple `dry_run: bool` parameter is cleaner.
- LangChain/LangGraph: Overkill for single-action approval. Existing Claude API integration suffices.
- Temporal/Prefect: Workflow engines for complex pipelines. Actions are single operations, not sagas.

### Expected Features

Action execution requires table stakes features to be production-safe, plus differentiators that leverage AI capabilities. The MVP should prioritize safety over sophistication.

**Must have (table stakes):**
- Action type registry: Structured vocabulary preventing hallucinated commands
- PD API actions: transfer-leader, split-region, drain-store via POST endpoints
- Dry-run mode: Validate without executing, must be default mode
- Human approval gate: All actions require explicit approval initially
- Action audit trail: Who approved what, when, with outcome
- Kill switch: Immediate halt of all pending actions
- Blast radius limits: Pre-flight checks ensuring actions are safe

**Should have (competitive):**
- Confidence-based approval routing: High-confidence actions notify-and-proceed, low-confidence require blocking approval
- Action validation: Check preconditions (region exists, store is Up, target is peer) before execution
- Post-action verification: Confirm expected outcome occurred
- Multi-step action plans: AI proposes sequences like "reduce schedule limit, drain store, restore limit"

**Defer (v2+):**
- Slack/PagerDuty approval integration: v2.1
- Impact prediction with historical data: v2.2
- Graduated autonomy levels beyond binary: v2.2
- GitOps action proposals: v3.0

### Architecture Approach

Action execution extends the existing architecture additively. The current flow (detect -> ticket -> diagnose) remains unchanged. After diagnosis produces a recommendation, a new flow branch creates ActionProposal (status: proposed) and awaits approval. Once approved, ActionExecutor orchestrates execution: capture state before, call Subject action method, capture state after, record audit trail. The Subject methods delegate to extended PDClient POST endpoints.

**Major components:**
1. ActionProposal/ActionRecord types: Data structures for proposed and executed actions with full lifecycle tracking
2. TicketDB extensions: CRUD methods for action proposals, action records, approval tracking
3. ActionExecutor: Orchestrates dry-run validation, state capture, execution, and audit
4. PDClient POST methods: create_operator, set_schedule_config, set_store_state
5. TiKVSubject implementations: Replace NotImplementedError stubs with PD API calls

**Key design decisions:**
- Structured action outputs only: Claude selects from predefined action types, never generates arbitrary commands
- Single state store: All action lifecycle state in database, not split across memory and storage
- Additive architecture: New capability layered on, existing observe-only flow unchanged
- Dry-run as validation: Not just logging "would do X" but checking preconditions and target state

### Critical Pitfalls

1. **Unbounded blast radius**: Action intended for one node cascades cluster-wide due to Raft interactions. Prevention: Pre-flight checks verify cluster state before execution, action queue prevents concurrent operations, explicit blast radius limits per action type. Address in Phase 1 (foundation).

2. **AI hallucination leading to destructive commands**: Claude generates plausible but incorrect store/region IDs. 2-5% hallucination rate unacceptable for production database operations. Prevention: Structured action outputs only (no free-form commands), parameter validation against live cluster state, action templates Claude fills in. Address in Phase 1 (architecture).

3. **Approval workflow blocking incident response**: Human-in-the-loop becomes bottleneck when approver unavailable. 39% of companies report bypassed guardrails during urgency. Prevention: Risk-tiered actions (low-risk auto-approve, high-risk require explicit approval), time-bounded escalation, async approval option with reversal capability. Address in Phase 2 (approval system).

4. **No rollback path for executed actions**: Action executes but causes unexpected problems with no undo mechanism. Prevention: Categorize action reversibility (reversible/partial/irreversible), automatic state snapshots before irreversible actions, action audit log with pre/post state, compensation actions defined. Address in Phase 1 (action type design).

5. **State machine complexity explosion**: Action lifecycle (proposed -> approved -> executing -> completed/failed) interacts with ticket state, diagnosis state, cluster state creating edge cases. Prevention: Single state store in database, explicit state machine with defined transitions, idempotent actions, crash recovery protocol. Address in Phase 1 (lifecycle design).

## Implications for Roadmap

Based on research, action execution breaks into four natural phases prioritizing safety before capability.

### Phase 1: Foundation - Types, Schema, Safety Gates
**Rationale:** Safety infrastructure must exist before ANY action executes. This phase establishes data structures, database schema, and pre-flight checks that prevent unbounded blast radius and hallucination risks.

**Delivers:**
- ActionProposal, ActionRecord, ActionStatus types
- Database schema (action_proposals, action_records tables)
- Action type registry with structured outputs
- Blast radius limits and pre-flight validation framework
- State machine design with single source of truth

**Addresses:**
- Critical pitfall #1 (unbounded blast radius): Pre-flight checks prevent unsafe execution
- Critical pitfall #2 (AI hallucination): Structured action types prevent arbitrary commands
- Critical pitfall #4 (no rollback): Reversibility classification per action type
- Critical pitfall #5 (state complexity): Single state store, explicit FSM

**Research flag:** Standard patterns - database schema and type design are well-established. No additional research needed.

### Phase 2: PD API Action Implementation
**Rationale:** With safety gates in place, implement actual PD API interactions. Start with lowest-risk actions (leader transfer) before higher-risk ones (drain store).

**Delivers:**
- PDClient POST methods: create_operator, set_schedule_config, set_store_state
- TiKVSubject action implementations: transfer_leader, split_region, set_leader_schedule_limit
- Dry-run validation for each action type (precondition checks)
- Action execution audit trail with state snapshots

**Addresses:**
- Table stakes: PD API actions, dry-run mode, action audit trail
- Feature from FEATURES.md: transfer-leader, region peer scheduling, scheduler limit adjustment
- Pitfall #11 (timeout ambiguity): Idempotent action design

**Uses:**
- httpx for POST endpoints
- Pydantic for ActionResult validation
- Existing PDClient async client

**Research flag:** May need deeper research - PD API operator status query patterns for pre-flight checks (pitfall #14: PD scheduler conflict). Consider using /gsd:research-phase to investigate PD operator coordination.

### Phase 3: Approval Workflow
**Rationale:** With actions implementable, add human approval gates. Risk-tiered design prevents approval from blocking incident response.

**Delivers:**
- TicketDB approval CRUD methods
- Risk classification per action type (low/medium/high)
- Approval timeout with escalation
- CLI commands: actions list/show/approve/reject
- AgentRunner integration to create proposals after diagnosis

**Addresses:**
- Critical pitfall #3 (approval blocks response): Risk-tiered approvals, timeouts
- Table stakes: human approval gate, approval audit trail
- Feature from FEATURES.md: approval workflow with context display

**Research flag:** Standard patterns - approval workflows well-documented in operator best practices. No additional research needed.

### Phase 4: Action Executor Integration
**Rationale:** Orchestrate all components into complete flow. This phase integrates types, PD API, approval, and audit into end-to-end action execution.

**Delivers:**
- ActionExecutor class with dry-run, state capture, execution, audit
- ProposedAction in DiagnosisOutput (structured action from Claude)
- AgentRunner creates ActionProposal after diagnosis
- Action execution loop processing approved actions
- Complete audit trail with pre/post state snapshots

**Addresses:**
- Integration pitfall #10 (results not visible): Automatic ticket updates with action outcome
- Feature from FEATURES.md: confidence-based approval routing, post-action verification
- Pitfall #6 (staging-only testing): Production dry-run mode enables safe validation

**Research flag:** May need deeper research - Production validation strategies and chaos engineering integration. Consider using /gsd:research-phase for testing approach.

### Phase Ordering Rationale

- **Safety first:** Phase 1 establishes guardrails before any execution capability exists. Without pre-flight checks and structured outputs, even dry-run validation is unsafe.
- **Incremental risk:** Phase 2 implements lowest-risk action (leader transfer) first. Dry-run mode enables testing without cluster impact.
- **Approval integration:** Phase 3 adds human gates after actions are implementable but before automatic execution. Enables manual testing of actions.
- **Complete flow:** Phase 4 integrates all components only after each layer is validated independently.

**Dependency chain:** Types -> Database -> PD API -> Approval -> Executor. Each phase depends on previous, but has minimal internal dependencies enabling focused implementation.

**Pitfall avoidance:**
- Additive architecture (Phase 1) prevents breaking observe-only flow
- Structured outputs (Phase 1) prevent hallucination risks
- Risk-tiered approval (Phase 3) prevents workflow bottlenecks
- Dry-run mode throughout enables production validation

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (PD API):** PD operator status query patterns for scheduler conflict detection (pitfall #14). Research needed: how to coordinate manual operator creation with PD background schedulers.
- **Phase 4 (Testing):** Production validation strategies and chaos engineering integration (pitfall #6). Research needed: safe methods for testing actions in production environment.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Foundation):** Database schema, type design, state machines are well-documented patterns
- **Phase 3 (Approval):** Human-in-the-loop workflows extensively documented in operator best practices

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | No new dependencies needed. httpx, Pydantic, aiosqlite already in use and sufficient. PD API endpoints verified in official tikv/pd router.go source. |
| Features | HIGH | Table stakes and differentiators validated against Kubernetes operator capability levels and AIOps best practices. MVP scope clear. |
| Architecture | HIGH | Additive design preserves existing functionality. Component boundaries well-defined. PD API integration points documented in official sources. |
| Pitfalls | HIGH | Critical pitfalls verified across multiple production incident reports and operator security audits. Mitigation strategies sourced from operator best practices. |

**Overall confidence:** HIGH

### Gaps to Address

- **PD scheduler coordination protocol:** Research identifies potential conflicts between manual operator actions and PD background schedulers, but specific coordination mechanism needs validation. Recommend /gsd:research-phase in Phase 2 for PD operator status query patterns.

- **Production testing strategy:** Dry-run mode provides validation without execution, but research shows staging-only testing insufficient. Need specific approach for production validation that's safe but realistic. Recommend /gsd:research-phase in Phase 4 for chaos engineering integration.

- **Action reversibility catalog:** Research identifies need to categorize actions as reversible/partial/irreversible, but specific reversibility for each action type needs determination during implementation. Document during Phase 1 action type design.

- **RBAC requirements per action:** Research recommends least privilege per action type, but specific permissions needed for each PD API endpoint need enumeration. Document during Phase 2 PD API implementation.

## Sources

### Primary (HIGH confidence)
- [tikv/pd router.go](https://github.com/tikv/pd/blob/master/server/api/router.go) - Complete PD API route definitions
- [PD HTTP Client Package](https://pkg.go.dev/github.com/tikv/pd/client/http) - HTTP API constants and methods
- [PD Control User Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - pd-ctl commands and operator reference
- [PD Scheduling Introduction Wiki](https://github.com/tikv/pd/wiki/Scheduling-Introduction) - Operator concepts and scheduling behavior
- [TiDB Operator Concurrent Operations Issue](https://github.com/pingcap/tidb-operator/issues/720) - Production incident: concurrent operations causing tombstone
- Existing codebase: operator_tikv/pd_client.py, operator_core/agent/runner.py, operator_core/db/tickets.py

### Secondary (MEDIUM confidence)
- [Kubernetes Operator Capability Levels](https://sdk.operatorframework.io/docs/overview/operator-capabilities/) - Operator maturity model
- [Red Hat: Kubernetes Operators Security Practices](https://www.redhat.com/en/blog/kubernetes-operators-good-security-practices) - RBAC and privilege guidance
- [Snyk: Security Implications of Kubernetes Operators](https://snyk.io/blog/security-implications-of-kubernetes-operators/) - 59 of 66 K8s CVEs from ecosystem
- [Skywork: Agentic AI Safety Best Practices 2025](https://skywork.ai/blog/agentic-ai-safety-best-practices-2025-enterprise/) - 39% bypass guardrails stat
- [Permit.io: Human-in-the-Loop Best Practices](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo) - Approval workflow patterns
- [Lakera: Guide to LLM Hallucinations](https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models) - 2-5% hallucination rates
- [FlowHunt: Human in the Loop Middleware](https://www.flowhunt.io/blog/human-in-the-loop-middleware-python-safe-ai-agents/) - asyncio.Event pattern for approval

### Tertiary (LOW confidence)
- [Chaos Engineering AI Testing Resources](https://github.com/chaosync-org/awesome-ai-agent-testing) - Testing framework options

---
*Research completed: 2026-01-25*
*Ready for roadmap: yes*
