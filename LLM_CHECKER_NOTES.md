# LLM-Based Invariant Checker — Experiment Notes

## What We Built

An `LLMInvariantChecker` that replaces the deterministic threshold-based checker
with Claude reasoning about system health from a rolling window of observations.
Drop-in replacement for `InvariantCheckerProtocol` — same interface, same ticket
pipeline, different detection approach.

## Results: A/B Comparison (Campaign 3 vs 4, local chat-db-app)

| Chaos Type         | Deterministic       | LLM Checker          |
|--------------------|---------------------|-----------------------|
| pool_exhaustion    | 2/2 det, 0/2 res   | 2/2 det, **2/2 res** |
| streaming_txn      | 2/2 det, 1/2 res   | 2/2 det, 0/2 res     |
| missing_index      | 2/2 det, 1/2 res   | 2/2 det, 0/2 res     |
| counter_race       | 2/2 det, 0/2 res   | 2/2 det, **2/2 res** |
| notification_fanout| 1/2 det, 1/2 res   | **2/2 det**, 1/2 res |
| write_amplification| **0/2 det**, 0/2 res| **2/2 det, 2/2 res** |
| fulltext_search    | 2/2 det, 2/2 res   | 2/2 det, 1/2 res     |
| **Overall**        | **79% det, 36% res**| **100% det, 57% res**|

### Key Findings

**LLM checker wins:**
- 100% detection rate (vs 79%) — caught write_amplification and notification_fanout
  which the deterministic checker missed entirely
- Fires within seconds (no grace period delay) — detects the 0→4→9 pool ramp
  immediately instead of waiting 30-60s
- Richer diagnostic signals — names like `idle_in_transaction_blocking_autovacuum`
  give the agent better context than generic `pool_exhaustion`

**LLM checker weaknesses:**
- Inconsistent violation naming across observations (`high_latency_spike` vs
  `high_p99_latency` vs `high_latency_p99_spike`), which breaks ticket deduplication
- streaming_txn and missing_index resolution regressed (1→0), possibly because
  noisy/varying violation names confused the agent
- ~1-3s API latency per check cycle (acceptable at 5-30s intervals)

## Next Step: Self-Consistent Naming

The naming inconsistency is the main issue. Best approach: **feed back the LLM's
own previous violations** into the next prompt.

Include the violations from the last check cycle in the user message:
```
Previous cycle violations: ["pool_exhaustion", "high_latency", "table_bloat"]
```

The LLM will naturally reuse the same names when the same conditions persist,
converging on stable names after the first cycle. This:
- Costs nothing (no extra API call, just a few tokens)
- Preserves ability to name novel issues
- Fits naturally with the rolling window already in the prompt
- Handles resolution cleanly (LLM stops reporting a name → it clears)

Implementation: add `self._last_violations` to `LLMInvariantChecker`, include it
in the user message before the observation window.

## Architecture

```
packages/operator-core/src/operator_core/monitor/llm_checker.py  — the checker
packages/operator-core/src/operator_core/cli/monitor.py          — --checker flag
eval/src/eval/runner/operator.py                                  — threads config
eval/src/eval/runner/campaign.py                                  — CheckerConfig
eval/src/eval/cli.py                                              — wires it up
eval/campaigns/debug/chatdb-checker-llm.yaml                      — LLM campaign
eval/campaigns/debug/chatdb-checker-baseline.yaml                 — deterministic
```

CLI usage:
```bash
# Deterministic (default)
uv run operator monitor run --subject chat-db-app

# LLM checker
uv run operator monitor run --subject chat-db-app --checker llm --checker-model claude-haiku-4-5-20251001

# Eval A/B test
cd eval
uv run eval run campaign campaigns/debug/chatdb-checker-baseline.yaml
uv run eval run campaign campaigns/debug/chatdb-checker-llm.yaml
```
