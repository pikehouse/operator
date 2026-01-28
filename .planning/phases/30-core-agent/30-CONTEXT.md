# Phase 30: Core Agent - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Agent container with one tool (shell) and audit logging. Container is equipped with CLI tools and Python packages an SRE would use. No dedicated web tools — Claude uses curl directly.

</domain>

<decisions>
## Implementation Decisions

### Tool Design
- **One tool only:** `shell(command, reasoning)` — no web_search or web_fetch
- Reasoning parameter is **required** — forces Claude to explain every action
- Return **structured dict** to Claude: `{stdout, stderr, exit_code, timed_out}`
- Default timeout: **120 seconds** (allows longer operations like docker pulls)
- Claude can use curl directly for web fetches

### Audit Format
- **JSON files** in mounted volume, one file per session
- Session = one triggered incident (start on unhealthy state, end on resolution/failure)
- **Full conversation** logged — all Claude messages + tool calls, complete reasoning chain
- File naming: **timestamp-based** (`2026-01-28T10-00-00-abc123.json`)

### Container Tooling
- Base image: **python:3.12-slim**
- CLI tools: curl, wget, jq, vim, git, netcat, dig, ping, htop
- Additional networking: tcpdump, traceroute, nmap
- Text processing: sed, awk, grep (standard in slim image)
- Python: executable via shell, can write and run scripts
- Python packages: anthropic, httpx, redis, pyyaml, pandas, numpy, prometheus-client

### Claude's Discretion
- Exact error message formatting in tool responses
- How to handle command timeouts (what message to return)
- Session ID generation method (uuid, timestamp, etc.)

</decisions>

<specifics>
## Specific Ideas

- "Let Claude cook" — don't restrict what commands it can run
- Container isolation is the safety boundary, not tool restrictions
- If Claude breaks things, docker-compose down/up resets

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Web search capability explicitly deferred (Claude uses curl).

</deferred>

---

*Phase: 30-core-agent*
*Context gathered: 2026-01-28*
