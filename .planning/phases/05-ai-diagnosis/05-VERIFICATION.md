---
phase: 05-ai-diagnosis
verified: 2026-01-25T02:24:18Z
status: passed
score: 17/17 must-haves verified
human_verification:
  completed: true
  method: scripts/verify-phase5.sh
  result: approved
  notes: "Diagnosis showed all required sections: timeline, affected components, metric readings, primary diagnosis with confidence, 3 alternatives considered with supporting/contradicting evidence, recommended actions with severity and 5 risk warnings"
---

# Phase 5: AI Diagnosis Verification Report

**Phase Goal:** Claude analyzes tickets and produces structured reasoning about distributed system issues.

**Verified:** 2026-01-25T02:24:18Z

**Status:** PASSED

**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Agent picks up undiagnosed tickets and invokes Claude with relevant context | ✓ VERIFIED | AgentRunner polls OPEN tickets, ContextGatherer assembles context, Claude invoked with structured output |
| 2 | Diagnosis output includes observation summary, identified root cause, and supporting evidence | ✓ VERIFIED | DiagnosisOutput has timeline, primary_diagnosis, confidence, supporting_evidence fields |
| 3 | AI correlates multiple metrics (e.g., latency + Raft lag + disk I/O) to pinpoint issues | ✓ VERIFIED | ContextGatherer provides metric_snapshot, stores, cluster_metrics; prompt builder includes all in structured prompt |
| 4 | Diagnosis logs show alternatives considered (e.g., "could be disk I/O, but metrics don't support") | ✓ VERIFIED | DiagnosisOutput.alternatives_considered with Alternative model (hypothesis, supporting, contradicting, conclusion) |
| 5 | Each diagnosis includes recommended action with rationale (even though v1 is observe-only) | ✓ VERIFIED | DiagnosisOutput has recommended_action, action_commands, severity, risks fields |

**Score:** 5/5 truths verified

### Required Artifacts

#### Plan 05-01: Foundation

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `agent/diagnosis.py` | DiagnosisOutput Pydantic model | ✓ VERIFIED | EXISTS (146 lines), SUBSTANTIVE (DiagnosisOutput + Alternative models, format_diagnosis_markdown function), WIRED (imported by runner, CLI) |
| `db/tickets.py` | update_diagnosis method | ✓ VERIFIED | EXISTS, SUBSTANTIVE (async def update_diagnosis at line 336), WIRED (called by AgentRunner, CLI diagnose command) |
| anthropic SDK | Installed dependency | ✓ VERIFIED | EXISTS (anthropic>=0.40.0 in pyproject.toml), version 0.76.0 installed |

#### Plan 05-02: Context and Prompts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `agent/context.py` | DiagnosisContext dataclass, ContextGatherer | ✓ VERIFIED | EXISTS (151 lines), SUBSTANTIVE (DiagnosisContext dataclass, ContextGatherer.gather method, _find_similar_tickets), WIRED (used by AgentRunner) |
| `agent/prompt.py` | SYSTEM_PROMPT, build_diagnosis_prompt | ✓ VERIFIED | EXISTS (126 lines), SUBSTANTIVE (SYSTEM_PROMPT 1188 chars, build_diagnosis_prompt function), WIRED (imported by AgentRunner, CLI) |

#### Plan 05-03: AgentRunner

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `agent/runner.py` | AgentRunner daemon | ✓ VERIFIED | EXISTS (210 lines), SUBSTANTIVE (AgentRunner class, run method, _diagnose_ticket with Claude API integration), WIRED (imported by CLI agent.py) |

#### Plan 05-04: CLI Commands

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `cli/agent.py` | agent subcommand group | ✓ VERIFIED | EXISTS (202 lines), SUBSTANTIVE (start and diagnose commands), WIRED (registered in main.py, creates AgentRunner) |
| `cli/tickets.py` | tickets show command | ✓ VERIFIED | EXISTS (enhanced with show command at line 166), SUBSTANTIVE (displays diagnosis with Rich Markdown), WIRED (registered in main.py) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| diagnosis.py | BaseModel | DiagnosisOutput inherits | ✓ WIRED | Line 27: `class DiagnosisOutput(BaseModel):` |
| tickets.py | status = 'diagnosed' | Status transition | ✓ WIRED | Line 355: `status = 'diagnosed'` in update_diagnosis |
| context.py | TiKVSubject | Observations | ✓ WIRED | Line 91: `await self.subject.get_stores()` |
| context.py | TicketDB | Similar tickets | ✓ WIRED | Line 140: `await self.db.list_tickets(status=TicketStatus.DIAGNOSED)` |
| prompt.py | DiagnosisContext | Prompt builder input | ✓ WIRED | Line 44: `def build_diagnosis_prompt(context: DiagnosisContext)` |
| runner.py | AsyncAnthropic | Claude API | ✓ WIRED | Line 23: `from anthropic import AsyncAnthropic`, line 72: `AsyncAnthropic()` |
| runner.py | beta.messages.parse | Structured output | ✓ WIRED | Line 162: `await self.client.beta.messages.parse(...)` with output_format=DiagnosisOutput |
| runner.py | update_diagnosis | Store diagnosis | ✓ WIRED | Lines 174, 187, 207: `await db.update_diagnosis(...)` |
| runner.py | TicketStatus.OPEN | Filter tickets | ✓ WIRED | Line 129: `tickets = await db.list_tickets(status=TicketStatus.OPEN)` |
| agent.py | AgentRunner.run() | Start daemon | ✓ WIRED | Line 99: `await runner.run()` |
| main.py | agent_app | Subcommand registration | ✓ WIRED | Line 17: `app.add_typer(agent_app, name="agent")` |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| CORE-04: Agent runner | ✓ SATISFIED | AgentRunner polls tickets, invokes Claude, stores diagnosis |
| DIAG-01: Structured tickets | ✓ SATISFIED | DiagnosisOutput with timeline, affected_components, primary_diagnosis, supporting_evidence |
| DIAG-02: Metric correlation | ✓ SATISFIED | ContextGatherer provides metric_snapshot, stores, cluster_metrics; all included in prompt |
| DIAG-03: Options-considered logging | ✓ SATISFIED | alternatives_considered field with Alternative model (hypothesis, supporting, contradicting, conclusion) |
| DIAG-04: Suggested actions | ✓ SATISFIED | recommended_action, action_commands, severity, risks fields |

**Coverage:** 5/5 requirements satisfied

### Anti-Patterns Found

No blocking anti-patterns detected.

**Findings:**

- ✓ No TODO/FIXME in critical paths
- ✓ No placeholder implementations in diagnosis flow
- ✓ Proper error handling for API errors (APIConnectionError, RateLimitError, APIError)
- ✓ No stub patterns in AgentRunner._diagnose_ticket
- ℹ️ Log tail stubbed (returns None) — per plan, deferred to future work

### Human Verification Complete

✓ User ran `scripts/verify-phase5.sh` successfully

**Test performed:**
1. Stopped tikv0 to create store_down violation
2. Monitor detected violation and created ticket
3. Agent diagnosed ticket with Claude
4. Diagnosis verified to contain:
   - Timeline section ✓
   - Affected Components ✓
   - Metric Readings ✓
   - Primary Diagnosis with confidence ✓
   - 3 Alternatives Considered with supporting/contradicting evidence ✓
   - Recommended Action with severity and 5 risk warnings ✓

**Result:** APPROVED

Per 05-04-SUMMARY.md: "Diagnosis showed SRE-quality reasoning" with all required sections present.

## Overall Assessment

### Phase Goal: ACHIEVED ✓

Claude successfully analyzes tickets and produces structured reasoning about distributed system issues. The AI demonstrates differential diagnosis methodology with alternatives considered and evidence-based reasoning.

### Implementation Quality

**Strengths:**
- Complete structured output schema with all required fields
- Robust error handling for API failures
- Context gathering assembles comprehensive information
- CLI integration provides both daemon and one-shot modes
- Human verification confirms diagnosis quality matches expectations

**Architecture:**
- Follows MonitorLoop daemon pattern from Phase 4
- Clean separation: context gathering → prompt building → Claude invocation → storage
- Proper async/await throughout
- Type hints and docstrings present

### Success Criteria Met

1. ✓ Agent picks up undiagnosed tickets and invokes Claude with relevant context
2. ✓ Diagnosis output includes observation summary, identified root cause, and supporting evidence
3. ✓ AI correlates multiple metrics (e.g., latency + Raft lag + disk I/O) to pinpoint issues
4. ✓ Diagnosis logs show alternatives considered (e.g., "could be disk I/O, but metrics don't support")
5. ✓ Each diagnosis includes recommended action with rationale (even though v1 is observe-only)

All 5 success criteria verified.

### Must-Haves Status

**Plan 05-01 (3/3):**
- ✓ DiagnosisOutput model validates Claude's structured response
- ✓ TicketDB can store and retrieve diagnosis markdown
- ✓ anthropic SDK is available for import

**Plan 05-02 (3/3):**
- ✓ Context gatherer assembles metrics, topology, and ticket history
- ✓ Prompt builder creates structured prompt with all context sections
- ✓ System prompt elicits differential diagnosis format

**Plan 05-03 (4/4):**
- ✓ AgentRunner polls for undiagnosed tickets
- ✓ AgentRunner invokes Claude with structured output
- ✓ AgentRunner stores diagnosis and transitions ticket status
- ✓ AgentRunner handles API errors gracefully without crashing

**Plan 05-04 (3/3):**
- ✓ User can start agent daemon with `operator agent start`
- ✓ User can run single diagnosis with `operator agent diagnose <ticket_id>`
- ✓ User can view diagnosis with `operator tickets show <ticket_id>`
- ✓ Agent daemon runs until Ctrl+C

**Total:** 17/17 must-haves verified

---

_Verified: 2026-01-25T02:24:18Z_
_Verifier: Claude (gsd-verifier)_
_Human verification: Completed via scripts/verify-phase5.sh_
