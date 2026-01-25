# Project Milestones: Operator

## v1.0 MVP (Shipped: 2026-01-25)

**Delivered:** AI-powered distributed systems operator that monitors TiKV clusters, diagnoses issues with Claude, and demonstrates diagnostic reasoning through an end-to-end chaos demo.

**Phases completed:** 1-6 (22 plans total)

**Key accomplishments:**
- Service-agnostic operator core with Subject adapter pattern and deployment abstraction
- TiKV subject implementation with PD API client, Prometheus metrics, and invariant checking
- Fully containerized test environment (6-node TiKV/PD cluster, Prometheus, Grafana, load generator)
- SQLite-backed ticket system with automated monitor loop and violation deduplication
- AI diagnosis with Claude producing SRE-quality reasoning (root cause, alternatives considered, recommendations)
- End-to-end chaos demo with fault injection, live detection, and diagnostic reasoning display

**Stats:**
- 6,223 lines of Python across 2 packages
- 6 phases, 22 plans
- 99 commits
- 1 day from start to ship

**Git range:** `90b6641` (docs: initialize project) → `ec4aa1b` (docs(06): complete chaos-demo phase)

**What's next:** v1.1 enhancements (additional chaos scenarios, action execution, multi-subject support)

---
