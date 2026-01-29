# Requirements: Operator v3.2 Evaluation Harness

**Defined:** 2026-01-29
**Core Value:** Evaluate how well Claude operates through chaos events — compare to baseline, detect regressions, analyze trends

## v3.2 Requirements

Requirements for evaluation harness. Each maps to roadmap phases.

### Runner Layer

- [ ] **RUN-01**: Campaign runner executes trials in sequence (reset → inject → wait → record)
- [ ] **RUN-02**: Trial records raw timing data (started_at, chaos_injected_at, ticket_created_at, resolved_at, ended_at)
- [ ] **RUN-03**: Subject state captured before and after chaos (initial_state, final_state)
- [ ] **RUN-04**: Commands extracted from agent session for post-hoc analysis
- [ ] **RUN-05**: Baseline trials run without agent (self-healing test)
- [ ] **RUN-06**: eval.db stores campaigns and trials separately from operator.db

### EvalSubject Protocol

- [ ] **SUBJ-01**: EvalSubject protocol defines reset(), wait_healthy(), capture_state(), get_chaos_types()
- [ ] **SUBJ-02**: TiKVEvalSubject implements protocol with Docker Compose reset
- [ ] **SUBJ-03**: TiKV chaos: node_kill (SIGKILL container)
- [ ] **SUBJ-04**: TiKV chaos: latency injection (tc netem)
- [ ] **SUBJ-05**: TiKV chaos: disk pressure (fallocate)
- [ ] **SUBJ-06**: TiKV chaos: network partition (iptables)

### Analysis Layer

- [ ] **ANAL-01**: Scoring computes time-to-detect, time-to-resolve from raw trial data
- [ ] **ANAL-02**: Command analysis: count, unique commands, thrashing detection
- [ ] **ANAL-03**: Destructive command detection via pattern matching
- [ ] **ANAL-04**: Baseline comparison (agent vs self-healing)
- [ ] **ANAL-05**: Campaign comparison (variant A vs variant B)
- [ ] **ANAL-06**: Analysis is idempotent — can re-run on old campaigns

### Viewer Layer

- [ ] **VIEW-01**: CLI: eval list shows campaigns
- [ ] **VIEW-02**: CLI: eval show <campaign_id> displays campaign + trials
- [ ] **VIEW-03**: CLI: eval show <trial_id> displays single trial detail
- [ ] **VIEW-04**: Web: minimal FastAPI + htmx for browsing trials
- [ ] **VIEW-05**: Web: trial detail shows reasoning/commands from agent session

### Config Variants

- [ ] **CONF-01**: Config variants define model, system_prompt, tools_config
- [ ] **CONF-02**: Campaigns can specify which variant to use
- [ ] **CONF-03**: Analysis compares performance across variants

### CLI

- [ ] **CLI-01**: eval run --subject tikv --chaos node_kill runs single trial
- [ ] **CLI-02**: eval run --baseline runs without agent
- [ ] **CLI-03**: eval run campaign config.yaml runs full campaign
- [ ] **CLI-04**: eval analyze <campaign_id> computes scores
- [ ] **CLI-05**: eval compare <campaign_a> <campaign_b> compares campaigns
- [ ] **CLI-06**: eval compare-baseline <campaign_id> compares to baseline

## Future Requirements

### Rate Limiter Subject

- **RL-01**: RateLimiterEvalSubject implements protocol
- **RL-02**: Rate limiter chaos: redis_kill
- **RL-03**: Rate limiter chaos: config_corrupt
- **RL-04**: Rate limiter chaos: burst_traffic

### Advanced Chaos

- **ADV-01**: TiKV chaos: cascade (multi-fault)
- **ADV-02**: TiKV chaos: adversarial (misleading symptoms)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fancy dashboards/charts | CLI is primary interface, web is for drilling into details |
| Real-time streaming UI | Post-hoc analysis, not live monitoring |
| Integration with operator-core | Eval harness is standalone, reads operator.db read-only |
| Automated regression alerts | Manual analysis first, automation later |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RUN-01 | Phase 35 | Pending |
| RUN-02 | Phase 35 | Pending |
| RUN-03 | Phase 35 | Pending |
| RUN-04 | Phase 35 | Pending |
| RUN-05 | Phase 35 | Pending |
| RUN-06 | Phase 35 | Pending |
| SUBJ-01 | Phase 35 | Pending |
| SUBJ-02 | Phase 35 | Pending |
| SUBJ-03 | Phase 35 | Pending |
| ANAL-01 | Phase 36 | Pending |
| ANAL-02 | Phase 36 | Pending |
| ANAL-03 | Phase 36 | Pending |
| ANAL-04 | Phase 36 | Pending |
| ANAL-05 | Phase 36 | Pending |
| ANAL-06 | Phase 36 | Pending |
| VIEW-01 | Phase 37 | Pending |
| VIEW-02 | Phase 37 | Pending |
| VIEW-03 | Phase 37 | Pending |
| VIEW-04 | Phase 37 | Pending |
| VIEW-05 | Phase 37 | Pending |
| SUBJ-04 | Phase 38 | Pending |
| SUBJ-05 | Phase 38 | Pending |
| SUBJ-06 | Phase 38 | Pending |
| CLI-01 | Phase 35 | Pending |
| CLI-02 | Phase 35 | Pending |
| CLI-03 | Phase 38 | Pending |
| CLI-04 | Phase 36 | Pending |
| CLI-05 | Phase 36 | Pending |
| CLI-06 | Phase 36 | Pending |
| CONF-01 | Phase 39 | Pending |
| CONF-02 | Phase 39 | Pending |
| CONF-03 | Phase 39 | Pending |

**Coverage:**
- v3.2 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

---
*Requirements defined: 2026-01-29*
*Last updated: 2026-01-29 after initial definition*
