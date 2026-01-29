# Requirements: Operator v3.2 Evaluation Harness

**Defined:** 2026-01-29
**Core Value:** Evaluate how well Claude operates through chaos events — compare to baseline, detect regressions, analyze trends

## v3.2 Requirements

Requirements for evaluation harness. Each maps to roadmap phases.

### Runner Layer

- [x] **RUN-01**: Campaign runner executes trials in sequence (reset → inject → wait → record)
- [x] **RUN-02**: Trial records raw timing data (started_at, chaos_injected_at, ticket_created_at, resolved_at, ended_at)
- [x] **RUN-03**: Subject state captured before and after chaos (initial_state, final_state)
- [x] **RUN-04**: Commands extracted from agent session for post-hoc analysis
- [x] **RUN-05**: Baseline trials run without agent (self-healing test)
- [x] **RUN-06**: eval.db stores campaigns and trials separately from operator.db

### EvalSubject Protocol

- [x] **SUBJ-01**: EvalSubject protocol defines reset(), wait_healthy(), capture_state(), get_chaos_types()
- [x] **SUBJ-02**: TiKVEvalSubject implements protocol with Docker Compose reset
- [x] **SUBJ-03**: TiKV chaos: node_kill (SIGKILL container)
- [ ] **SUBJ-04**: TiKV chaos: latency injection (tc netem)
- [ ] **SUBJ-05**: TiKV chaos: disk pressure (fallocate)
- [ ] **SUBJ-06**: TiKV chaos: network partition (iptables)

### Analysis Layer

- [x] **ANAL-01**: Scoring computes time-to-detect, time-to-resolve from raw trial data
- [x] **ANAL-02**: Command analysis: count, unique commands, thrashing detection
- [x] **ANAL-03**: Destructive command detection via LLM classification
- [x] **ANAL-04**: Baseline comparison (agent vs self-healing)
- [x] **ANAL-05**: Campaign comparison (variant A vs variant B)
- [x] **ANAL-06**: Analysis is idempotent — can re-run on old campaigns

### Viewer Layer

- [x] **VIEW-01**: CLI: eval list shows campaigns
- [x] **VIEW-02**: CLI: eval show <campaign_id> displays campaign + trials
- [x] **VIEW-03**: CLI: eval show <trial_id> displays single trial detail
- [x] **VIEW-04**: Web: minimal FastAPI + Jinja2 for browsing trials
- [x] **VIEW-05**: Web: trial detail shows reasoning/commands from agent session

### Config Variants

- [ ] **CONF-01**: Config variants define model, system_prompt, tools_config
- [ ] **CONF-02**: Campaigns can specify which variant to use
- [ ] **CONF-03**: Analysis compares performance across variants

### CLI

- [x] **CLI-01**: eval run --subject tikv --chaos node_kill runs single trial
- [x] **CLI-02**: eval run --baseline runs without agent
- [ ] **CLI-03**: eval run campaign config.yaml runs full campaign
- [x] **CLI-04**: eval analyze <campaign_id> computes scores
- [x] **CLI-05**: eval compare <campaign_a> <campaign_b> compares campaigns
- [x] **CLI-06**: eval compare-baseline <campaign_id> compares to baseline

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
| RUN-01 | Phase 35 | Complete |
| RUN-02 | Phase 35 | Complete |
| RUN-03 | Phase 35 | Complete |
| RUN-04 | Phase 35 | Complete |
| RUN-05 | Phase 35 | Complete |
| RUN-06 | Phase 35 | Complete |
| SUBJ-01 | Phase 35 | Complete |
| SUBJ-02 | Phase 35 | Complete |
| SUBJ-03 | Phase 35 | Complete |
| ANAL-01 | Phase 36 | Complete |
| ANAL-02 | Phase 36 | Complete |
| ANAL-03 | Phase 36 | Complete |
| ANAL-04 | Phase 36 | Complete |
| ANAL-05 | Phase 36 | Complete |
| ANAL-06 | Phase 36 | Complete |
| VIEW-01 | Phase 37 | Complete |
| VIEW-02 | Phase 37 | Complete |
| VIEW-03 | Phase 37 | Complete |
| VIEW-04 | Phase 37 | Complete |
| VIEW-05 | Phase 37 | Complete |
| SUBJ-04 | Phase 38 | Pending |
| SUBJ-05 | Phase 38 | Pending |
| SUBJ-06 | Phase 38 | Pending |
| CLI-01 | Phase 35 | Complete |
| CLI-02 | Phase 35 | Complete |
| CLI-03 | Phase 38 | Pending |
| CLI-04 | Phase 36 | Complete |
| CLI-05 | Phase 36 | Complete |
| CLI-06 | Phase 36 | Complete |
| CONF-01 | Phase 39 | Pending |
| CONF-02 | Phase 39 | Pending |
| CONF-03 | Phase 39 | Pending |

**Coverage:**
- v3.2 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0

---
*Requirements defined: 2026-01-29*
*Last updated: 2026-01-29 after Phase 37 complete*
