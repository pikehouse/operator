# Requirements: Operator v2.3

**Defined:** 2026-01-27
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems — and now infrastructure-level remediation with script execution

## v2.3 Requirements

Requirements for Infrastructure Actions & Script Execution milestone.

### Safety Enhancement (Phase 23) ✓

- [x] **SAFE-01**: Approval workflow re-verifies state immediately before execution (TOCTOU resistance)
- [x] **SAFE-02**: Approval tokens expire after 60 seconds
- [x] **SAFE-03**: Requester identity maintained through action chain (not just agent identity)
- [x] **SAFE-04**: Dual authorization model: requester permission AND agent capability
- [x] **SAFE-05**: Audit logs include both requester ID and agent ID
- [x] **SAFE-06**: Audit logs redact secrets before logging (API_KEY=, password=, token= patterns)
- [x] **SAFE-07**: Session-level cumulative risk tracking across action chains
- [x] **SAFE-08**: Kill switch can force-terminate in-flight operations (not just block new ones)

### Docker Actions

- [ ] **DOCK-01**: docker_start_container action starts a stopped container
- [ ] **DOCK-02**: docker_stop_container action stops a running container (graceful)
- [ ] **DOCK-03**: docker_restart_container action restarts a container
- [ ] **DOCK-04**: docker_logs action retrieves container logs with tail limit (max 10000 lines)
- [ ] **DOCK-05**: docker_inspect_container action returns container status and config (read-only)
- [ ] **DOCK-06**: docker_network_connect action connects container to network
- [ ] **DOCK-07**: docker_network_disconnect action disconnects container from network
- [ ] **DOCK-08**: docker_exec action executes command in container with output capture
- [ ] **DOCK-09**: All Docker actions use async executor wrapping (run_in_executor)
- [ ] **DOCK-10**: Docker actions register as ActionType.TOOL in get_general_tools()

### Host Actions

- [ ] **HOST-01**: host_service_start action starts a systemd service
- [ ] **HOST-02**: host_service_stop action stops a systemd service
- [ ] **HOST-03**: host_service_restart action restarts a systemd service
- [ ] **HOST-04**: host_kill_process action sends signal to process (SIGTERM or SIGKILL)
- [ ] **HOST-05**: Process kill uses graceful pattern: SIGTERM → wait 5s → SIGKILL if still running
- [ ] **HOST-06**: Host actions validate inputs (service name whitelist, PID > 1 check)
- [ ] **HOST-07**: Host actions use asyncio.create_subprocess_exec (never shell=True)

### Script Execution

- [ ] **SCRP-01**: execute_script action accepts Python or bash script content
- [ ] **SCRP-02**: Scripts run in isolated Docker container (python:3.11-slim or bash:5.2-alpine)
- [ ] **SCRP-03**: Sandbox enforces network isolation (--network none)
- [ ] **SCRP-04**: Sandbox enforces resource limits (512MB RAM, 1 CPU, 100 PIDs)
- [ ] **SCRP-05**: Sandbox runs as non-root user (user=nobody)
- [ ] **SCRP-06**: Sandbox container is ephemeral (remove=True)
- [ ] **SCRP-07**: Execution enforces timeout (60s default, configurable)
- [ ] **SCRP-08**: Script output (stdout/stderr) captured and returned to agent
- [ ] **SCRP-09**: Script exit code captured and returned

### Script Validation

- [ ] **VALD-01**: Python scripts validated with ast.parse() before execution
- [ ] **VALD-02**: Bash scripts validated with bash -n before execution
- [ ] **VALD-03**: Scripts scanned for secret patterns (API_KEY=, password=, token=)
- [ ] **VALD-04**: Scripts scanned for dangerous patterns (eval, exec, __import__, os.system)
- [ ] **VALD-05**: Script content limited to 10000 characters
- [ ] **VALD-06**: Validation failures block execution with descriptive error

### Risk Classification

- [ ] **RISK-01**: Actions classified by risk level (LOW, MEDIUM, HIGH, CRITICAL)
- [ ] **RISK-02**: docker_inspect, docker_logs classified as LOW risk
- [ ] **RISK-03**: docker_start, docker_restart, host_service_* classified as MEDIUM risk
- [ ] **RISK-04**: docker_stop, docker_network_*, host_kill_process classified as HIGH risk
- [ ] **RISK-05**: execute_script classified as CRITICAL risk
- [ ] **RISK-06**: Approval mode configurable per risk level (AUTO, REQUIRE, DENY)

### Agent Integration

- [ ] **AGNT-01**: Agent can propose execute_script with script_content parameter
- [ ] **AGNT-02**: Script execution result returned to agent for analysis
- [ ] **AGNT-03**: Agent can iterate on failed scripts based on output
- [ ] **AGNT-04**: Agent prompt includes guidance on when to use scripts vs direct actions

### Demo Scenarios

- [ ] **DEMO-01**: Container recovery demo: TiKV node crash → detect → docker_restart_container → verify
- [ ] **DEMO-02**: Config repair demo: misconfiguration → execute_script (inspection + fix) → verify

## Future Requirements

### v2.4 Cloud Actions

- Cloud API integration (AWS/GCP/Azure)
- IAM credential management
- Multi-region operation support

### v2.5 Advanced Features

- Host file read/write operations
- Action chaining with data passing
- Auto-rollback on failure
- Gradual rollout patterns

## Out of Scope

| Feature | Reason |
|---------|--------|
| Direct host script execution | Security risk — all scripts must run in sandboxed containers |
| Unlimited shell access | Attack vector — violates zero-trust principles |
| Credential storage in actions | Compliance violation — easy to leak via logs |
| Cloud API actions | Deferred to v2.4 — prove model locally first |
| Host file operations | Deferred to v2.5 — higher risk, focus on process/service control |
| Shared sandbox environments | Security boundary violation — each execution must be isolated |
| Micro-VM sandboxing (gVisor/Firecracker) | Deferred — Docker containers sufficient for demo, evaluate for production |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SAFE-01 | Phase 23 | Complete |
| SAFE-02 | Phase 23 | Complete |
| SAFE-03 | Phase 23 | Complete |
| SAFE-04 | Phase 23 | Complete |
| SAFE-05 | Phase 23 | Complete |
| SAFE-06 | Phase 23 | Complete |
| SAFE-07 | Phase 23 | Complete |
| SAFE-08 | Phase 23 | Complete |
| DOCK-01 | Phase 24 | Pending |
| DOCK-02 | Phase 24 | Pending |
| DOCK-03 | Phase 24 | Pending |
| DOCK-04 | Phase 24 | Pending |
| DOCK-05 | Phase 24 | Pending |
| DOCK-06 | Phase 24 | Pending |
| DOCK-07 | Phase 24 | Pending |
| DOCK-08 | Phase 24 | Pending |
| DOCK-09 | Phase 24 | Pending |
| DOCK-10 | Phase 24 | Pending |
| HOST-01 | Phase 25 | Pending |
| HOST-02 | Phase 25 | Pending |
| HOST-03 | Phase 25 | Pending |
| HOST-04 | Phase 25 | Pending |
| HOST-05 | Phase 25 | Pending |
| HOST-06 | Phase 25 | Pending |
| HOST-07 | Phase 25 | Pending |
| SCRP-01 | Phase 26 | Pending |
| SCRP-02 | Phase 26 | Pending |
| SCRP-03 | Phase 26 | Pending |
| SCRP-04 | Phase 26 | Pending |
| SCRP-05 | Phase 26 | Pending |
| SCRP-06 | Phase 26 | Pending |
| SCRP-07 | Phase 26 | Pending |
| SCRP-08 | Phase 26 | Pending |
| SCRP-09 | Phase 26 | Pending |
| VALD-01 | Phase 26 | Pending |
| VALD-02 | Phase 26 | Pending |
| VALD-03 | Phase 26 | Pending |
| VALD-04 | Phase 26 | Pending |
| VALD-05 | Phase 26 | Pending |
| VALD-06 | Phase 26 | Pending |
| RISK-01 | Phase 27 | Pending |
| RISK-02 | Phase 27 | Pending |
| RISK-03 | Phase 27 | Pending |
| RISK-04 | Phase 27 | Pending |
| RISK-05 | Phase 27 | Pending |
| RISK-06 | Phase 27 | Pending |
| AGNT-01 | Phase 28 | Pending |
| AGNT-02 | Phase 28 | Pending |
| AGNT-03 | Phase 28 | Pending |
| AGNT-04 | Phase 28 | Pending |
| DEMO-01 | Phase 29 | Pending |
| DEMO-02 | Phase 29 | Pending |

**Coverage:**
- v2.3 requirements: 52 total
- Mapped to phases: 52
- Unmapped: 0 ✓

---
*Requirements defined: 2026-01-27*
*Last updated: 2026-01-28 — Phase 23 complete (SAFE-01 through SAFE-08)*
