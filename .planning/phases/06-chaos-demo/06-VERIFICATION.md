---
phase: 06-chaos-demo
verified: 2026-01-25T03:13:00Z
status: passed
score: 9/9 must-haves verified
---

# Phase 6: Chaos Demo Verification Report

**Phase Goal:** End-to-end demonstration showing AI diagnosis of injected faults.
**Verified:** 2026-01-25T03:13:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                 | Status     | Evidence                                                                                          |
| --- | ----------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------- |
| 1   | ChaosDemo can orchestrate full demo lifecycle         | ✓ VERIFIED | chaos.py contains run() method sequencing 7 stages with try/finally cleanup                       |
| 2   | Demo stages are visually distinct with Rich formatting| ✓ VERIFIED | _stage_banner() uses console.rule(), Rich Panel for diagnosis, Live display for countdown         |
| 3   | Random TiKV store is selected and killed              | ✓ VERIFIED | _inject_fault() uses random.choice() on tikv_containers, docker.kill() with SIGKILL               |
| 4   | Detection countdown shows live progress               | ✓ VERIFIED | _wait_for_detection() uses Rich Live with 2-second polling, elapsed time display                  |
| 5   | AI diagnosis is invoked and displayed                 | ✓ VERIFIED | _run_diagnosis() calls AsyncAnthropic().beta.messages.parse(), _display_diagnosis() uses Panel   |
| 6   | User can run `operator demo chaos` to start the demo  | ✓ VERIFIED | CLI command exists, imports ChaosDemo, instantiates and runs via asyncio.run()                    |
| 7   | Demo runs full cycle from healthy cluster through diagnosis | ✓ VERIFIED | run() method sequences all stages, checkpoint approved by human                             |
| 8   | User sees detection countdown and AI reasoning output | ✓ VERIFIED | Rich Live for countdown (line 303), Panel with Markdown for diagnosis (line 441)                  |
| 9   | Cluster is restored to healthy state after demo       | ✓ VERIFIED | _cleanup() in finally block restarts killed container via compose.start()                         |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact                                                    | Expected                                     | Status     | Details                                                                                 |
| ----------------------------------------------------------- | -------------------------------------------- | ---------- | --------------------------------------------------------------------------------------- |
| `packages/operator-core/src/operator_core/demo/__init__.py` | Demo module exports                          | ✓ VERIFIED | Exists, 11 lines, exports ChaosDemo                                                     |
| `packages/operator-core/src/operator_core/demo/chaos.py`    | Chaos demo orchestration (min 150 lines)     | ✓ VERIFIED | Exists, 482 lines, contains class ChaosDemo, all methods implemented                    |
| `packages/operator-core/src/operator_core/cli/demo.py`      | Demo CLI subcommands                         | ✓ VERIFIED | Exists, 90 lines, exports demo_app, contains @demo_app.command("chaos")                 |
| `packages/operator-core/src/operator_core/cli/main.py`      | Main CLI with demo subcommand                | ✓ VERIFIED | Modified, imports demo_app, registers via app.add_typer(demo_app, name="demo")          |

**All artifacts:**
- Level 1 (Existence): 4/4 PASS
- Level 2 (Substantive): 4/4 PASS (no stubs, adequate length, proper exports)
- Level 3 (Wired): 4/4 PASS (imported and used)

### Key Link Verification

| From                    | To                                          | Via                           | Status     | Details                                                                                  |
| ----------------------- | ------------------------------------------- | ----------------------------- | ---------- | ---------------------------------------------------------------------------------------- |
| demo/chaos.py           | operator_core.deploy.LocalDeployment        | compose file operations       | ✓ WIRED    | Uses DockerClient(compose_files=[...]) line 76, _docker.compose.ps/up/kill/start used   |
| demo/chaos.py           | operator_core.db.tickets.TicketDB           | ticket queries                | ✓ WIRED    | Imports TicketDB line 35, used in _wait_for_detection (lines 327, 346) and _run_diagnosis (line 385) |
| demo/chaos.py           | rich.console.Console                        | terminal output               | ✓ WIRED    | Imports Console line 29, used as dataclass field line 62, console.print/rule/input throughout |
| demo/chaos.py           | InvariantChecker                            | active checking               | ✓ WIRED    | Imports and instantiates line 278-301, calls check_stores_up() line 323                 |
| demo/chaos.py           | AsyncAnthropic                              | Claude API diagnosis          | ✓ WIRED    | Imports line 27, instantiates and calls beta.messages.parse() lines 413-421              |
| cli/demo.py             | operator_core.demo.ChaosDemo                | instantiation and run         | ✓ WIRED    | Imports ChaosDemo line 18, instantiates with params lines 71-76, runs via asyncio.run() |
| cli/main.py             | cli/demo.py                                 | add_typer                     | ✓ WIRED    | Imports demo_app line 6, registers via app.add_typer(demo_app, name="demo") line 19     |

**All key links:** 7/7 WIRED

### Requirements Coverage

| Requirement | Description                                              | Status      | Blocking Issue |
| ----------- | -------------------------------------------------------- | ----------- | -------------- |
| CHAOS-01    | Node kill — hard failure of a store via Docker stop/kill | ✓ SATISFIED | None           |

**Evidence for CHAOS-01:**
- `_inject_fault()` uses `self._docker.kill(container_name)` with SIGKILL (line 222)
- Random TiKV container selection via `random.choice(tikv_containers)` (line 215)
- Container kill is immediate, not graceful shutdown
- Demo verified by human with full cycle: healthy -> fault -> detect -> diagnose -> cleanup

### Anti-Patterns Found

**None** — No blockers, warnings, or concerning patterns detected.

Scan results:
- ✓ No TODO/FIXME comments
- ✓ No placeholder content
- ✓ No empty implementations (return null/undefined/{}/[])
- ✓ No console.log-only implementations
- ✓ No stub patterns

### Human Verification Required

Per user prompt: **Human already verified the demo works correctly (checkpoint approved).**

Checkpoint verification from 06-02-PLAN.md confirmed:
- Demo runs full cycle: healthy cluster → fault injection → detection → AI diagnosis → cleanup
- Detection occurs within 2-4 seconds of fault injection
- AI diagnosis correctly identifies killed store as root cause
- Cluster returns to healthy state after demo

No additional human verification needed.

### Implementation Quality Notes

**Strengths:**
1. **Comprehensive orchestration:** 482-line implementation covers all demo stages with proper error handling
2. **Active invariant checking:** Detection loop actively runs `InvariantChecker.check_stores_up()` instead of passive polling (critical bug fix from 06-02)
3. **Rich terminal UX:** Stage banners, live countdown, colored output, Markdown panels
4. **Proper cleanup:** try/finally ensures killed container is restarted
5. **One-shot diagnosis:** Correctly bypasses AgentRunner daemon for demo context
6. **Container-to-store mapping:** Robust logic to map Docker container names to PD store IDs

**Critical fixes applied:**
- Fix from commit 0db240b: Changed from passive ticket polling to active invariant checking during detection wait
- This fix was essential — without it, detection would never trigger because no invariant checks would run

**Patterns established:**
- Demo CLI namespace with typer.Typer()
- asyncio.run() bridge for CLI-to-async code
- Rich Live for async progress displays
- Stage banner pattern for multi-step demos
- try/finally cleanup for fault injection demos

## Verification Summary

**Phase 6 goal ACHIEVED.**

All must-haves verified:
- ✓ ChaosDemo orchestrator class exists and is substantive (482 lines, all methods implemented)
- ✓ CLI command `operator demo chaos` registered and functional
- ✓ Full demo lifecycle works: healthy → inject fault → detect → diagnose → cleanup
- ✓ Detection uses active invariant checking (not passive polling)
- ✓ AI diagnosis invokes Claude with structured output
- ✓ Rich terminal output with stage banners, live countdown, diagnosis panels
- ✓ Cluster restored to healthy state after demo
- ✓ CHAOS-01 requirement satisfied (random TiKV kill via Docker)

**Human verification:** Checkpoint approved. Demo confirmed working end-to-end.

**No gaps found.** Phase ready to mark complete.

---

_Verified: 2026-01-25T03:13:00Z_
_Verifier: Claude (gsd-verifier)_
