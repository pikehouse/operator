# Project Research Summary

**Project:** Operator v2.3 - Infrastructure Actions & Script Execution
**Domain:** AI-driven distributed systems automation with Docker control and sandboxed code execution
**Researched:** 2026-01-27
**Confidence:** HIGH

## Executive Summary

Infrastructure automation for AI agents in 2026 is a high-stakes domain where security failures have catastrophic consequences. This milestone adds Docker container control (start/stop/restart/exec/logs/networking), host operations (file I/O, process signaling), and sandboxed Python/bash script execution to an existing AI-powered operator system. The research reveals three critical insights: (1) existing safety controls (kill switch, approval workflow, observe-only mode) are necessary but **insufficient** for infrastructure actions — they must be enhanced to handle time-of-check/time-of-use races, agent identity confusion, and multi-step attack chains; (2) the technology stack requires minimal additions (aiofiles for async I/O) since python-on-whales already covers Docker operations; (3) container sandboxing provides baseline security but is **not a security boundary** — micro-VMs (gVisor/Firecracker) should be considered for production deployments.

The recommended approach leverages the existing ActionType.TOOL framework with three dedicated executor components (DockerActionExecutor, HostActionExecutor, ScriptSandbox). Script execution follows a two-phase pattern: agent generates script as string parameter, system validates/sandboxes/executes/captures output. This avoids direct LLM code execution and enforces defense-in-depth through validation, isolation, resource limits, and privilege dropping. The key architectural decision is treating infrastructure actions as extensions of the existing action system rather than a parallel execution path.

Critical risks center on authorization bypass (agent identity confusion), container escape (shared kernel vulnerabilities), and prompt injection (malicious content triggering dangerous operations). Mitigation requires maintaining requester context throughout action chains, implementing TOCTOU-resistant approval workflows, enforcing strict sandbox hardening (no network, read-only FS, resource limits, non-root user), and multi-layer script validation (syntax, secrets scanning, dangerous command detection). The 2026 security landscape shows 45% of AI-generated code contains exploitable vulnerabilities, making validation non-negotiable.

## Key Findings

### Recommended Stack

The existing stack already provides most necessary capabilities. python-on-whales 0.80.0 (currently integrated) supports all required Docker operations including container lifecycle, exec, logs, and networking. Rather than introducing a parallel async Docker library (aiodocker), the research recommends wrapping synchronous python-on-whales calls with asyncio.run_in_executor() for async compatibility. This preserves existing Docker Compose management code and maintains architectural consistency. The only new dependency required is aiofiles for async file I/O operations.

**Core technologies:**
- **python-on-whales 0.80.0** (existing): Docker container lifecycle, exec, logs, networking — thread-safe, comprehensive API coverage, already integrated with deployment infrastructure
- **aiofiles 25.1.0** (new): Async file read/write for host operations — seamless asyncio integration, cleaner API than raw executor wrapping
- **Python stdlib (os/signal)**: Process signaling operations — sufficient for SIGTERM/SIGKILL without additional dependencies like psutil
- **python:3.11-slim** (base image): Sandbox container for Python script execution — matches project's Python version, includes pip, official image with security patches
- **bash:5.2-alpine** (base image): Sandbox container for bash scripts — minimal footprint (~2MB), sufficient for shell execution

**Key decision:** Stay with python-on-whales + executor pattern rather than switching to aiodocker. Switching would require rewriting existing Docker Compose code for marginal async performance benefit. The executor wrapping pattern is idiomatic Python async for blocking I/O.

**Security configuration for sandboxes:** Default Docker seccomp profile (blocks 51 dangerous syscalls), network_mode="none" (prevents data exfiltration), user="nobody" (non-root execution), resource limits (cpus=1.0, memory=512m), read-only volumes, ephemeral containers (remove=True).

### Expected Features

Infrastructure automation in 2026 centers on three pillars: safety through isolation, observability through comprehensive logging, and governance through risk-based approvals. The feature landscape distinguishes table stakes (what users expect from any infrastructure automation tool) from differentiators (what sets AI-driven systems apart).

**Must have (table stakes):**
- Docker container control: start/stop/restart (basic lifecycle), logs access with limits (debugging), network connect/disconnect (isolation scenarios), exec with audit (troubleshooting) — every Docker automation tool has these
- Host operations: read/write files with path restrictions (config inspection/repair), process signals SIGTERM/SIGKILL (graceful/forced shutdown), service status checks (pre-flight validation) — standard operational patterns
- Sandboxed script execution: Python/bash in isolated containers, resource limits (5min timeout, 512MB RAM, 1 CPU), stdout/stderr streaming (real-time feedback), exit code capture (success/failure), ephemeral execution (no persistent state) — 2026 standard for AI-generated code
- Action lifecycle: dry-run/preview mode (plan before apply), parameter validation (JSON schema), real-time progress updates (streaming state changes), comprehensive audit logging (who/what/when/why), timeout enforcement (prevent hung operations), idempotency (retry safety) — comparable to Terraform, Pulumi, Kubernetes operators
- Safety controls: risk-based approval gates (low/medium/high/critical), observe-only mode (compliance testing), action kill switch (emergency stop), pre-flight validation (fail fast), concurrent action limits (resource exhaustion prevention) — enterprise IaC standard

**Should have (competitive):**
- **AI-generated script validation pipeline** (DIFFERENTIATOR): Multi-layer validation (static analysis, secrets scanning, dangerous command detection, Pydantic schema) addressing the 45% vulnerability rate in AI-generated code — this is what separates manual automation (Ansible Tower, Rundeck) from AI-driven automation in 2026
- Real-time security guardrails: treat every tool invocation as high-risk event, pre-execution webhook to analyzer, block prompt injection patterns — Microsoft Defender pattern for runtime AI agent defense
- Syntax validation before sandboxing: catch errors early using ast.parse() for Python, bash -n for shell scripts — don't waste sandbox resources on syntax errors
- Security policy enforcement: no hardcoded secrets, no public exposure by default, IAM least privilege, PII redaction in logs — Cloudflare shift-left security model

**Defer (v2+ or post-MVP):**
- Action chaining with data passing: output from action N becomes input to action N+1 (StackStorm/Ansible Tower pattern) — adds workflow complexity, users can chain manually initially
- Auto-rollback on failure: restore previous state if action fails (container orchestration pattern) — high complexity, requires state management, can simulate with manual undo scripts
- Gradual rollout (canary pattern): apply to 1% → 10% → 100% with validation stages — very high complexity, requires metric monitoring infrastructure
- Interactive approval with diffs: show before/after state like Git diff — nice UX but text-based preview sufficient for MVP
- Automatic retry with exponential backoff: transient failure recovery (1s, 2s, 4s, 8s) — adds failure mode complexity, manual retry sufficient initially
- Action composition UI: visual workflow builder, drag-and-drop action nodes — very high complexity, defer until core execution stable

**Anti-features (explicitly avoid):**
- Unrestricted shell access to host/containers — attack vector, violates zero-trust
- Credential storage in action parameters — compliance violation, easy to leak via logs
- Synchronous long-running actions — terrible UX, use async pattern with action ID polling
- Auto-execution without preview — violates principle of least surprise, users lose trust
- Shared sandbox environments — state leakage between runs, security boundary violation
- Global kill switch only — too coarse-grained, need per-action surgical intervention
- Script execution on host (non-containerized) — zero isolation, catastrophic security risk
- Unlimited retry loops — amplifies blast radius, turns single failure into DoS

### Architecture Approach

Infrastructure actions integrate with the existing action framework through ActionType.TOOL. The core action lifecycle (propose → validate → execute → complete) remains unchanged. New infrastructure is isolated in dedicated executor components that implement tool execution handlers. This architectural decision preserves the existing approval workflow, audit logging, and status tracking while enabling infrastructure capabilities.

**Major components:**
1. **DockerActionExecutor** (packages/operator-core/src/operator_core/actions/executors/docker.py): Docker container lifecycle, network operations using python-on-whales with async executor wrapping — fire-and-forget semantics, structured results, Docker errors propagate as exceptions
2. **HostActionExecutor** (packages/operator-core/src/operator_core/actions/executors/host.py): Host file operations, process management using asyncio.create_subprocess_exec() — NEVER uses shell=True to prevent command injection, validates all inputs before execution
3. **ScriptSandbox** (packages/operator-core/src/operator_core/actions/executors/script.py): Script validation, sandboxed execution in gVisor/Docker containers, output capture with timeout — two-phase (validate → sandbox → execute → capture → cleanup), multi-layer security (syntax check, deny list, resource limits, no network, read-only FS)
4. **InfrastructureTools** (packages/operator-core/src/operator_core/actions/tools.py): Tool action definitions registered via get_general_tools(), dispatched through execute_tool() by name prefix — docker_* → DockerActionExecutor, host_* → HostActionExecutor, execute_script → ScriptSandbox

**No changes required to:** ActionExecutor.execute_proposal() (already supports TOOL type), ActionProposal (parameters JSON field supports arbitrary data including script_content), ActionRegistry, ActionStatus lifecycle, database schema.

**Integration pattern:** Agent generates script as string parameter in ActionRecommendation, flows through standard proposal/approval/execution path, ScriptSandbox writes to temp file → creates sandbox container → executes with timeout → captures output → returns through action result. This avoids direct LLM code execution and enables validation/approval between generation and execution.

**Build order:** Phase 1 (Docker Actions - simplest, no external content) → Phase 2 (Host Actions - subprocess patterns only) → Phase 3 (Script Sandbox - most complex, depends on Docker) → Phase 4 (Agent Integration - script generation guidance) → Phase 5 (Demo Scenarios). Clear dependency graph, no circular dependencies.

### Critical Pitfalls

Research identified 15 domain pitfalls; the top 5 by severity and likelihood:

1. **Agent Identity Confusion Bypasses Authorization** (CRITICAL, Phase 0): Actions authorized against agent identity rather than requesting user identity, enabling unauthorized users to execute privileged operations through agent. Prevention: maintain requester context throughout action chain, authorize against requester not agent, audit logs MUST include both requester ID and agent ID, implement dual-authorization ("Can requester ask?" AND "Can agent execute?"). Real-world: CVE-2025-12420 (ServiceNow) allowed unauthenticated attackers to impersonate any user by exploiting agent identity trust.

2. **Time-of-Check/Time-of-Use (TOCTOU) Race Conditions** (CRITICAL, Phase 0): System state changes between approval and execution, bypassing safety checks. Attack scenarios: container swap (approve stop web-server-1, attacker renames database-master → web-server-1, agent stops database), file content swap (approve write config.json, attacker symlinks to /etc/passwd). Prevention: atomic approval+execution transaction, resource locking during approval-to-execution window, re-verify conditions immediately before execution, short approval expiry (30-60s), use immutable identifiers (container IDs not names, inodes not paths). Multiple 2026 CVEs confirm exploitability.

3. **Container Escape via Kernel Vulnerabilities** (CRITICAL, Phase 3): Sandboxed scripts escape container isolation through shared kernel vulnerabilities. Recent CVEs: CVE-2024-21626 (runC), CVE-2025-31133/52565/52881 (November 2025 runC vulnerabilities), Leaky Vessels. Prevention: use micro-VMs instead of containers for highest security (gVisor, Firecracker, Docker Sandboxes), keep host kernel/Docker/runC patched, runtime monitoring (eBPF-based Falco/Tetragon), strict seccomp profiles, zero network access, read-only root filesystem, rootless containers. Research finding: namespace-based containers have weaker isolation than micro-VMs.

4. **Prompt Injection Manipulates Infrastructure Actions** (HIGH, Phase 2-3): Malicious prompts in external content (emails, documents, API responses) trick agent into dangerous operations. Attack scenarios: email with hidden "stop all production containers" instruction, PDF metadata containing "create privileged container" command, API response poisoning. Prevention: input sanitization (strip instructions from external content), separate contexts (external content vs user commands), trust level tagging, confirmation prompts for infrastructure actions, use structured tools not natural language, human-in-loop for external triggers. OWASP AI Agent Security Top 10 (2026) lists this as #1 risk.

5. **Insufficient Sandboxing in Script Execution** (HIGH, Phase 3): Agent-generated scripts run with inadequate isolation, accessing host resources/network/other containers. Common failures: network isolation not enforced (can connect to internal services), resource limits not set (DoS via fork bombs/disk fill), shared volumes mounted. Prevention requires ALL isolation layers: --network none, --read-only root FS, resource limits (--memory=512m, --cpus=1.0, --pids-limit=100), --cap-drop all, --security-opt=no-new-privileges, custom seccomp profile, time limits (5-10min auto-kill). 2026 research: "Sandboxing limits blast radius but does not eliminate risk."

**Additional critical pitfalls:** Docker socket exposure = root access (NEVER mount /var/run/docker.sock), privileged containers disable all isolation (NEVER use --privileged for agent code), multi-step attack chains bypass single-action risk assessment (need session-level cumulative risk tracking), audit logs leak secrets (implement redaction before logging).

## Implications for Roadmap

Based on dependency analysis and risk mitigation requirements, this research recommends a **5-phase build sequence** prioritizing safety infrastructure before capabilities. The critical finding is that existing safety controls must be enhanced BEFORE adding infrastructure actions, otherwise the system introduces attack vectors that bypass governance.

### Phase 0: Safety Infrastructure Enhancement
**Rationale:** All critical pitfalls related to authorization, race conditions, and audit logging must be resolved before infrastructure capabilities are enabled. Building Docker/host/script executors on top of vulnerable foundation creates exploitable system.

**Delivers:**
- TOCTOU-resistant approval workflow (atomic operations, resource locking, state re-verification, 60s approval expiry, immutable identifiers)
- Requester context tracking (maintain user identity through action chain, dual-authorization model)
- Enhanced audit logging (requester ID + agent ID, secret redaction, structured format)
- Session-level risk accumulation (track cumulative risk across action chains, pattern detection for read→write→network sequences)
- Force-termination kill switch (can interrupt in-flight operations, not just block new ones)

**Addresses pitfalls:** Agent identity confusion (Pitfall 3), TOCTOU races (Pitfall 4), audit log leakage (Pitfall 9), multi-step attack chains (Pitfall 6), incomplete kill switch (Pitfall 13)

**Why first:** Security vulnerabilities in approval/authorization/audit create systemic risk. Infrastructure capabilities amplify blast radius. Cannot safely proceed to Phase 1 without these fixes.

**Research flag:** Low — these are extensions of existing operator controls, architecture well-understood

### Phase 1: Docker Container Control
**Rationale:** Docker actions have minimal external dependencies, well-documented APIs, and existing python-on-whales integration. Serves as foundation for script execution (Phase 3) which depends on Docker containers.

**Delivers:**
- DockerActionExecutor with async executor wrapping pattern
- Container lifecycle actions: docker_start_container, docker_stop_container, docker_restart_container
- Container inspection: docker_inspect_container (read-only, low-risk validation)
- Network operations: docker_prune_networks (cleanup, low-risk)
- Docker logs access with tail limits (max 10000 lines to prevent memory issues)
- Integration with existing ActionType.TOOL dispatch

**Uses stack:** python-on-whales 0.80.0 (existing), asyncio.run_in_executor() for async wrapping

**Implements architecture:** DockerActionExecutor component, tool registration in get_general_tools()

**Addresses pitfalls:** Docker socket exposure (use API not socket mount), privileged containers (enforce --cap-drop all, --security-opt=no-new-privileges), network cascading failures (dependency checking before disconnect)

**Avoids anti-features:** No docker exec in Phase 1 (defer to later phase after additional security hardening), no unrestricted network operations

**Why second:** Simplest infrastructure capability, no external content processing (lower prompt injection risk), validates executor pattern before complex operations

**Research flag:** Low — python-on-whales API well-documented, Docker operations standard

### Phase 2: Host Operations
**Rationale:** Host operations (file I/O, process signaling) have moderate complexity and use only stdlib/aiofiles (no complex dependencies). Required for config repair scenarios but can be developed in parallel with Phase 1.

**Delivers:**
- HostActionExecutor using asyncio.create_subprocess_exec()
- Service control: host_restart_service, host_stop_service, host_start_service (systemctl integration)
- Process signaling: host_kill_process with graceful SIGTERM → SIGKILL pattern
- File operations: async read/write with aiofiles (deferred to post-MVP based on risk assessment)
- Input validation: service name whitelist pattern, signal name validation, PID verification

**Uses stack:** aiofiles 25.1.0 (NEW — add via `uv add "aiofiles>=25.1.0"`), Python stdlib asyncio.subprocess, os/signal modules

**Implements architecture:** HostActionExecutor component, subprocess security patterns (NEVER shell=True)

**Addresses pitfalls:** Path traversal (canonicalize paths, whitelist directories, use O_NOFOLLOW), unsafe process signaling (SIGTERM before SIGKILL, validate target process, never signal PID 1 or kernel threads)

**Why third:** Moderate risk profile, requires Phase 0 safety enhancements, can develop in parallel with Phase 1 if resources available

**Research flag:** Low — asyncio subprocess well-documented, standard Unix operations

### Phase 3: Sandboxed Script Execution
**Rationale:** Highest complexity and risk, depends on Docker (Phase 1), requires multi-layer security validation. This is the key differentiator for AI-driven infrastructure automation but must be built on secure foundation.

**Delivers:**
- ScriptSandbox component with two-phase execution (validate → execute)
- Multi-layer validation pipeline: syntax check (ast.parse for Python, bash -n for shell), secrets scanning (detect API_KEY=, password= patterns), dangerous command detection (deny list for import os, eval, exec, __import__), length limit (max 10000 chars)
- Sandbox container configuration: python:3.11-slim base image, network_mode="none", read-only root FS, resource limits (--memory=512m, --cpus=1.0, --pids-limit=100), user="nobody", --security-opt=no-new-privileges
- Execution with timeout enforcement (default 60s, configurable, force-kill on timeout)
- Output capture: stdout/stderr streaming, exit code, timeout flag
- Automatic cleanup: ephemeral containers (remove=True), temp file deletion

**Uses stack:** python-on-whales (from Phase 1), python:3.11-slim and bash:5.2-alpine base images (pulled on first use)

**Implements architecture:** ScriptSandbox component, execute_script tool definition, integration with agent script generation flow

**Addresses pitfalls:** Container escape (micro-VM recommendation for production, strict seccomp), insufficient sandboxing (all 6 isolation layers required), resource exhaustion DoS (hard limits on CPU/memory/disk/processes), prompt injection (multi-layer validation catches malicious patterns)

**Why fourth:** Depends on Docker executor (Phase 1), highest security scrutiny required, enables AI differentiation

**Research flag:** Medium — sandbox security patterns well-documented but implementation requires careful testing, consider phase-specific research for gVisor vs Firecracker vs Docker Sandboxes comparison

### Phase 4: Agent Script Generation Integration
**Rationale:** Connects script execution capability to agent diagnosis workflow, enabling AI to generate remediation scripts. Requires working sandbox (Phase 3) and safety controls (Phase 0).

**Delivers:**
- Extended agent prompt guidance: when to use execute_script vs docker/host actions, script capabilities and limitations, example patterns
- ActionRecommendation support for script_content parameter (no schema changes needed)
- Agent script generation for complex remediation: multi-step operations, conditional logic, state inspection before action
- End-to-end validation: agent generates → system validates → sandbox executes → result captured → iterative refinement based on output

**Implements architecture:** Agent integration points, script_content parameter flow through existing proposal system

**Addresses pitfalls:** Prompt injection (agent trained to distinguish user commands from external content), multi-step attack chains (script content analyzed holistically before execution)

**Why fifth:** Requires all previous phases, highest integration complexity, enables full AI-driven automation

**Research flag:** Low — extends existing agent diagnosis patterns

### Phase 5: Demo Scenarios & Documentation
**Rationale:** Validate end-to-end flows with realistic scenarios, update operator demos to showcase infrastructure capabilities.

**Delivers:**
- Demo scenario 1: TiKV container crash → docker_restart_container remediation
- Demo scenario 2: PD process hung → host_kill_process (SIGTERM) → docker_restart_container
- Demo scenario 3: Network partition → execute_script (query metrics + conditional restart logic)
- Updated demo chapters documenting infrastructure action flows
- Runbook examples for common operational patterns

**Why last:** Requires all capabilities functional, serves as integration test and documentation

**Research flag:** None — demonstration of implemented features

### Phase Ordering Rationale

- **Safety-first approach:** Phase 0 addresses systemic security vulnerabilities before capabilities added. Cannot safely enable infrastructure actions on vulnerable foundation.
- **Dependency-driven sequence:** Phase 1 (Docker) before Phase 3 (Script Sandbox which uses Docker containers). Phase 2 (Host) can parallelize with Phase 1.
- **Risk graduation:** Start with well-understood Docker operations (Phase 1), progress to moderate-risk host operations (Phase 2), culminate with highest-risk AI-generated code execution (Phase 3).
- **Iterative validation:** Each phase validates executor pattern and safety controls before next phase. Early phases serve as integration tests.
- **Architecture preservation:** Extends existing ActionType.TOOL framework rather than parallel execution path. Maintains consistency with v2.0-v2.2 action system.

**Critical path:** Phase 0 (Safety) → Phase 1 (Docker) → Phase 3 (Sandbox) → Phase 4 (Agent Integration). Phase 2 (Host) can parallelize with Phase 1 if resources available.

**Parallel opportunities:** Phase 1 and Phase 2 development can occur simultaneously after Phase 0 completes. Phase 5 (Demos) can begin as soon as any single capability (Docker OR Host OR Script) is functional.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 3 (Script Sandbox):** Container runtime comparison (namespace-based Docker vs gVisor vs Firecracker vs Docker Sandboxes) for production security posture. Research existing but implementation-specific guidance needed. Consider `/gsd:research-phase` for "micro-VM sandbox selection and configuration" if production deployment requires stronger isolation than baseline Docker.

**Phases with standard patterns (skip research-phase):**
- **Phase 0 (Safety Enhancement):** Extends existing approval/audit systems, architecture well-understood from v2.0-v2.2
- **Phase 1 (Docker Control):** python-on-whales API extensively documented, Docker operations standard across industry
- **Phase 2 (Host Operations):** asyncio subprocess patterns well-documented, Unix process management standard
- **Phase 4 (Agent Integration):** Extends existing agent diagnosis patterns, prompt engineering iterative not research-blocked
- **Phase 5 (Demos):** Documentation and examples, no research needed

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | python-on-whales API verified via PyPI and official docs, aiofiles extensively documented, stdlib operations standard. Decision to stay with python-on-whales vs switching to aiodocker based on architectural consistency and avoiding rewrite. |
| Features | HIGH | Feature categorization verified against multiple automation platforms (Ansible Tower, Rundeck, StackStorm, Kubernetes operators), 2026 security best practices (OWASP, Microsoft, Cloudflare), sandbox platforms comparison. Table stakes vs differentiators distinction clear. |
| Architecture | HIGH | Integration with existing ActionType.TOOL framework verified via codebase inspection, executor pattern validated against Python asyncio best practices, build order dependency analysis complete. No framework changes required confirms low integration risk. |
| Pitfalls | HIGH | 15 pitfalls verified with official sources (OWASP, Docker documentation), 2026 CVEs (container escape, TOCTOU, agent identity bypass), security research papers. Severity assessment based on real-world incidents. Phase 0 safety enhancements critical before capabilities. |

**Overall confidence:** HIGH

### Gaps to Address

**Gap 1: Production sandbox technology selection**
- **What's uncertain:** Whether baseline Docker containers with seccomp/namespaces provide sufficient isolation for production deployment, or if micro-VMs (gVisor/Firecracker/Docker Sandboxes) are required.
- **Impact:** Security posture and performance characteristics differ significantly. Docker Sandboxes (released 2025/2026) specifically targets AI agent code execution.
- **How to handle:** Start with hardened Docker containers for MVP (network=none, read-only FS, resource limits, custom seccomp). Monitor for container escape attempts. Evaluate micro-VM migration if security incidents occur or compliance requires stronger isolation. Consider `/gsd:research-phase` for Phase 3 if production deployment timeline known.

**Gap 2: Script library installation for Python sandboxes**
- **What's uncertain:** Whether Python scripts need external libraries (requests, pandas, etc.) and how to provide them securely (pre-built images vs dynamic pip install vs library allowlist).
- **Impact:** Pre-built images increase image size and maintenance. Dynamic pip install increases execution time and supply chain risk. Allowlist reduces flexibility.
- **How to handle:** Start with no external libraries (stdlib only). Add if actual use cases demonstrate need. Recommendation: allowlist approach with pre-approved, vulnerability-scanned libraries if required.

**Gap 3: Optimal execution timeout values**
- **What's uncertain:** What timeout values balance preventing runaway scripts vs accommodating legitimate slow operations. 30s may terminate valid operations, 5min delays failure detection.
- **Impact:** User experience (premature termination frustration) vs security (delayed DoS detection).
- **How to handle:** Start with 60s default, make configurable per action. Monitor actual execution times in production. Adjust based on p95 latency + safety margin. Implement progressive timeout (warn at 45s, kill at 60s).

**Gap 4: Dependency mapping for Docker network operations**
- **What's uncertain:** How to automatically discover service dependencies for blast radius analysis when disconnecting containers from networks.
- **Impact:** Manual approval required for all network operations if dependency analysis unavailable. Risk of cascading failures if dependencies unknown.
- **How to handle:** Phase 1 MVP: require manual approval for all network disconnect operations (HIGH risk level). Post-MVP: implement dependency discovery via Docker Compose service definitions, network traffic analysis, or manual dependency configuration.

**Gap 5: Kill switch force-termination implementation patterns**
- **What's uncertain:** Architectural patterns for interrupt-safe operation execution, particularly for long-running Docker operations (e.g., stopping 100 containers).
- **Impact:** Kill switch effectiveness. User trust in safety controls.
- **How to handle:** Phase 0: implement pre-execution check + in-flight operation tracking. For MVP, track operation PIDs and use SIGKILL for force-termination. Post-MVP research: checkpoint/rollback patterns, saga pattern for multi-step operations.

## Sources

### Primary (HIGH confidence - official documentation and verified 2026 sources)

**Stack research:**
- [python-on-whales PyPI](https://pypi.org/project/python-on-whales/) — Version 0.80.0 released 2026-01-10, API coverage verification
- [python-on-whales Documentation](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) — Container lifecycle, exec, logs, networking API reference
- [aiofiles PyPI](https://pypi.org/project/aiofiles/) — Version 25.1.0, Python 3.9-3.14 compatibility
- [Python asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html) — Official Python 3.14.2 docs, updated 2026-01-26
- [Docker Seccomp Security](https://docs.docker.com/engine/security/seccomp/) — Default seccomp profile blocking 51 syscalls

**Features research:**
- [Docker API Best Practices](https://docs.docker.com/reference/api/engine/) — Container control operations
- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html) — Security requirements, privileged container warnings
- [StackStorm Event-Driven Automation](https://docs.stackstorm.com/overview.html) — Action runners, workflow patterns
- [Rundeck Workflow Automation](https://docs.rundeck.com/docs/) — Runbook automation reference
- [Kubernetes Operator Reconciliation](https://book.kubebuilder.io/reference/good-practices) — Idempotency patterns

**Architecture research:**
- Existing operator codebase: operator_core/actions/executor.py, operator_core/actions/tools.py, operator_core/actions/types.py — ActionType.TOOL infrastructure verified

**Pitfalls research:**
- [Docker Security Documentation](https://docs.docker.com/engine/security/) — Official security guidance
- [OWASP AI Agent Security Top 10 (2026)](https://medium.com/@oracle_43885/owasps-ai-agent-security-top-10-agent-security-risks-2026-fc5c435e86eb) — Prompt injection #1 risk
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) — Secret redaction requirements
- [CWE-367: TOCTOU Race Condition](https://cwe.mitre.org/data/definitions/367.html) — Attack patterns and mitigations
- [Path Traversal - OWASP](https://owasp.org/www-community/attacks/Path_Traversal) — Canonicalization requirements

### Secondary (MEDIUM confidence - 2026 industry research and security papers)

**2026 security research:**
- [Microsoft: Runtime Defense for AI Agents](https://www.microsoft.com/en-us/security/blog/2026/01/23/runtime-risk-realtime-defense-securing-ai-agents/) — Real-time security guardrails, multi-step attack detection
- [AI-Generated Code Security Risks](https://apiiro.com/blog/ai-generated-code-security/) — 45% vulnerability rate statistic
- [Cloudflare Shift-Left Security](https://www.infoq.com/news/2026/01/cloudflare-security-shift-left/) — 50+ policy enforcement patterns
- [Container Security 2026](https://www.cloud4c.com/blogs/container-security-in-2026-risks-and-strategies) — Evolving threat landscape

**Sandbox platforms:**
- [Top Sandbox Platforms for AI 2026](https://www.koyeb.com/blog/top-sandbox-code-execution-platforms-for-ai-code-execution-2026) — gVisor, Firecracker, Docker Sandboxes comparison
- [Docker Sandboxes for Coding Agents](https://www.docker.com/blog/docker-sandboxes-a-new-approach-for-coding-agent-safety/) — Micro-VM approach for AI-generated code
- [Setting Up Secure Python Sandbox for LLM Agents](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents) — Security configuration patterns

**Container vulnerabilities (2025-2026 CVEs):**
- [Docker Desktop CVE-2025-9074](https://securitybuzz.com/cybersecurity-news/docker-desktop-flaw-exposes-hosts-to-privilege-escalation/) — CVSS 9.3 authentication bypass
- [Leaky Vessels Vulnerabilities](https://www.paloaltonetworks.com/blog/cloud-security/leaky-vessels-vulnerabilities-container-escape/) — Container runtime escapes
- [CVE-2026-20809: Windows Kernel TOCTOU](https://windowsforum.com/threads/cve-2026-20809-windows-kernel-toctou-local-privilege-elevation-patch-playbook.396703/) — TOCTOU privilege escalation
- [ServiceNow CVE-2025-12420](https://appomni.com/ao-labs/bodysnatcher-agentic-ai-security-vulnerability-in-servicenow/) — Agent identity bypass enabling unauthenticated impersonation

**Process and file security:**
- [OpenStack Subprocess Security](https://security.openstack.org/guidelines/dg_use-subprocess-securely.html) — shell=True prevention
- [Symlink Attacks](https://medium.com/@instatunnel/symlink-attacks-when-file-operations-betray-your-trust-986d5c761388) — Path traversal via symlinks
- [SIGKILL vs SIGTERM Guide](https://www.suse.com/c/observability-sigkill-vs-sigterm-a-developers-guide-to-process-termination/) — Graceful shutdown patterns

### Tertiary (Supporting context)

**Infrastructure automation trends:**
- [Infrastructure Management Trends 2026](https://www.trigyn.com/insights/infrastructure-management-trends-2026-powering-resilient-intelligent-and-always) — Risk-based approval workflows, AIOps integration
- [Pulumi Kubernetes Operator 2.3](https://www.pulumi.com/blog/pulumi-kubernetes-operator-2-3/) — Preview mode patterns
- [Governance as Code](https://spacelift.io/blog/governance-as-code) — Policy enforcement architectures

---
*Research completed: 2026-01-27*
*Ready for roadmap: yes*
