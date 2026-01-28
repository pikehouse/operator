# Phase 30: Core Agent - Research

**Researched:** 2026-01-28
**Domain:** AI agent container with shell tool and audit logging
**Confidence:** HIGH

## Summary

This phase implements the foundational container for v3.0 "Operator Laboratory" - a paradigm shift from the v2.x action framework approach to giving Claude full shell access with container isolation as the safety boundary. The agent container runs Python 3.12 with CLI tooling an SRE would use, provides a single `shell(command, reasoning)` tool, and logs complete conversation sessions to JSON files.

The implementation diverges from v2.x by abandoning predefined action abstractions in favor of autonomy. Claude can execute arbitrary commands (curl, docker, jq, netcat, etc.) with mandatory reasoning strings, and safety comes from container isolation rather than action restrictions. Audit logs capture full conversation history including all tool calls and reasoning chains to enable post-incident review.

The standard stack leverages `AsyncAnthropic` SDK (already in codebase), `asyncio.create_subprocess_exec` for shell tool execution with timeout, and JSON file-based audit logs (one file per session). Container tooling follows the existing Dockerfile patterns from the ratelimiter-service package.

**Primary recommendation:** Create a lightweight Python agent script that runs in a `python:3.12-slim` container with mounted Docker socket, uses `AsyncAnthropic` client for Claude API calls, implements `shell()` tool with structured dict returns, and writes session audit logs to a mounted volume.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | (existing) | Claude SDK with AsyncAnthropic client | Already in codebase, official SDK with tool calling support |
| asyncio (stdlib) | Python 3.12 | Async subprocess execution | Standard library, used throughout operator-core |
| python:3.12-slim | Docker base | Agent container base image | Matches CONTEXT.md requirement, slim variant reduces attack surface |
| Docker CLI | (in container) | Docker operations from within agent | Required for docker-compose access, standard CLI |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | (existing) | HTTP backend for AsyncAnthropic | Already in codebase, optional but recommended for async |
| json (stdlib) | Python 3.12 | Audit log serialization | Standard library, sufficient for structured logging |

### Container Tooling
| Tool | Purpose | Installation |
|------|---------|--------------|
| curl, wget | HTTP operations | apt-get install curl wget |
| jq | JSON processing | apt-get install jq |
| vim | Text editing | apt-get install vim |
| git | Version control | apt-get install git |
| netcat-openbsd, dnsutils, iputils-ping | Networking (nc, dig, ping) | apt-get install netcat-openbsd dnsutils iputils-ping |
| htop | Process monitoring | apt-get install htop |
| tcpdump, traceroute, nmap | Advanced networking | apt-get install tcpdump traceroute nmap |

### Python Packages (in container)
| Package | Purpose |
|---------|---------|
| anthropic | Claude SDK |
| httpx | Async HTTP |
| redis | Redis client (for subject observation) |
| pyyaml | YAML parsing |
| pandas, numpy | Data analysis |
| prometheus-client | Prometheus metrics |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python:3.12-slim | python:3.12-alpine | Alpine smaller but glibc incompatibilities, slim is safer |
| JSON files | SQLite audit DB | SQLite adds dependency, JSON files simpler and greppable |
| AsyncAnthropic | Sync Anthropic | Async required for non-blocking tool execution |

**Installation (Dockerfile):**
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget jq vim git \
    netcat-openbsd dnsutils iputils-ping htop \
    tcpdump traceroute nmap \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    anthropic httpx redis pyyaml \
    pandas numpy prometheus-client

WORKDIR /app
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/src/operator_core/
├── agent_lab/                # New v3.0 agent module
│   ├── __init__.py
│   ├── agent.py             # Core agent loop (Phase 31)
│   ├── tools.py             # shell() tool implementation
│   ├── audit.py             # Session audit logging
│   └── prompt.py            # SRE agent system prompt (Phase 31)
docker/
├── agent/
│   ├── Dockerfile           # Agent container
│   └── entrypoint.py        # Container startup script
docker-compose.yml           # Updated with agent service (Phase 32)
```

### Pattern 1: Shell Tool with Structured Returns
**What:** Execute arbitrary commands with timeout, return structured dict to Claude
**When to use:** For all agent shell operations
**Example:**
```python
# Source: CONTEXT.md decisions, asyncio subprocess docs
import asyncio
from typing import Any

async def shell(command: str, reasoning: str) -> dict[str, Any]:
    """
    Execute shell command with timeout and structured output.

    Args:
        command: Shell command to execute (arbitrary string)
        reasoning: Required explanation of why this command is needed

    Returns:
        Dict with stdout, stderr, exit_code, timed_out fields
    """
    # Reasoning is logged but not validated (mandatory parameter)

    # Create subprocess with timeout (default 120s per CONTEXT.md)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=120.0
        )

        return {
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "exit_code": proc.returncode,
            "timed_out": False,
        }

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "stdout": "",
            "stderr": "Command timed out after 120 seconds",
            "exit_code": -1,
            "timed_out": True,
        }
```

### Pattern 2: Session-Based Audit Logging
**What:** One JSON file per session with full conversation history
**When to use:** For all agent sessions (unhealthy detection → resolution/failure)
**Example:**
```python
# Source: Audit research findings, existing audit.py patterns
import json
from datetime import datetime
from pathlib import Path
from typing import Any

class SessionAuditor:
    """
    Session-based audit logger for agent conversations.

    Logs complete reasoning chains including all Claude messages
    and tool calls to timestamped JSON files.
    """

    def __init__(self, audit_dir: Path):
        self.audit_dir = audit_dir
        self.session_id = self._generate_session_id()
        self.messages = []

    def _generate_session_id(self) -> str:
        """Generate timestamp-based session ID."""
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        import uuid
        short_id = str(uuid.uuid4())[:8]
        return f"{timestamp}-{short_id}"

    def log_message(self, role: str, content: Any):
        """Log a message in the conversation."""
        self.messages.append({
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
        })

    def log_tool_call(self, tool_name: str, parameters: dict, result: dict):
        """Log a tool invocation with reasoning."""
        self.messages.append({
            "timestamp": datetime.now().isoformat(),
            "type": "tool_call",
            "tool": tool_name,
            "parameters": parameters,
            "result": result,
        })

    def save_session(self):
        """Write session audit log to JSON file."""
        filepath = self.audit_dir / f"{self.session_id}.json"

        session_data = {
            "session_id": self.session_id,
            "started_at": self.messages[0]["timestamp"] if self.messages else None,
            "ended_at": datetime.now().isoformat(),
            "message_count": len(self.messages),
            "messages": self.messages,
        }

        filepath.write_text(json.dumps(session_data, indent=2))
```

### Pattern 3: AsyncAnthropic Tool Calling Loop
**What:** Use AsyncAnthropic with tool definitions and result streaming
**When to use:** For Claude conversation loop (Phase 31)
**Example:**
```python
# Source: Anthropic SDK docs, existing agent/runner.py patterns
from anthropic import AsyncAnthropic
from anthropic.types import ToolUseBlock

async def run_agent_loop(client: AsyncAnthropic, system_prompt: str, initial_message: str):
    """
    Core agent loop with tool execution.

    Sends initial message to Claude, handles tool calls by executing
    shell commands, and returns results for continued reasoning.
    """
    messages = [{"role": "user", "content": initial_message}]

    tools = [
        {
            "name": "shell",
            "description": "Execute a shell command with timeout",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explanation of why this command is needed"
                    }
                },
                "required": ["command", "reasoning"]
            }
        }
    ]

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

        # Check for tool use
        tool_uses = [block for block in response.content if isinstance(block, ToolUseBlock)]

        if not tool_uses:
            # No more tools, conversation complete
            break

        # Execute tools and collect results
        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "shell":
                result = await shell(**tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result)
                })

        # Add assistant message and tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
```

### Anti-Patterns to Avoid
- **Restricting commands:** Don't validate or whitelist shell commands - defeats the "let Claude cook" philosophy
- **Synchronous Anthropic client:** Blocks event loop during API calls, must use AsyncAnthropic
- **Shell injection protection:** Don't use shlex.quote() - Claude generates the full command, trust container isolation
- **Complex approval workflows:** v3.0 has no approval system, container isolation is the safety boundary

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async subprocess timeout | Manual signal handling | asyncio.wait_for(proc.communicate(), timeout) | Handles cleanup, race conditions, signal delivery |
| JSON serialization | Custom encoders | json.dumps() with default indent | Standard library handles common types, simple is better |
| Session ID generation | Custom timestamp format | datetime.strftime() + uuid4()[:8] | Collision-resistant, sortable, standard |
| Docker socket mounting | Custom socket paths | Standard -v /var/run/docker.sock:/var/run/docker.sock | Docker convention, works everywhere |

**Key insight:** This phase is intentionally simple. The complexity is in Claude's reasoning, not the container infrastructure. Resist the urge to add validation layers or safety abstractions.

## Common Pitfalls

### Pitfall 1: Using Sync Anthropic Client
**What goes wrong:** Blocking API calls freeze the entire agent loop, timeouts don't work correctly
**Why it happens:** Easy to forget `async`/`await` when copying examples from sync documentation
**How to avoid:** Always import `AsyncAnthropic`, not `Anthropic`, and use `await` on all client methods
**Warning signs:** Agent hangs during Claude API calls, tool execution stops during thinking

### Pitfall 2: Shell Command Escaping
**What goes wrong:** Over-escaping or quoting breaks commands Claude generates (e.g., `curl` with JSON payloads)
**Why it happens:** Security instinct from web apps doesn't apply - Claude controls the full command
**How to avoid:** Pass command directly to `create_subprocess_shell()`, let Claude handle quoting/escaping
**Warning signs:** Commands with quotes or special chars fail mysteriously, JSON payloads break

### Pitfall 3: Forgetting Timeout Cleanup
**What goes wrong:** Timed-out processes become zombies, consuming resources until container restart
**Why it happens:** `asyncio.wait_for()` raises exception but doesn't kill the process
**How to avoid:** Always call `proc.kill()` in timeout handler, then `await proc.wait()` to reap
**Warning signs:** Container memory grows over time, `ps aux` shows zombie processes

### Pitfall 4: Audit Log File Naming Collisions
**What goes wrong:** Concurrent sessions or rapid restarts overwrite audit logs
**Why it happens:** Timestamp-only naming has ~1 second resolution
**How to avoid:** Include random component (uuid4()[:8]) in filename after timestamp
**Warning signs:** Missing audit logs, file modification times don't match session count

### Pitfall 5: Docker Socket Permission Denied
**What goes wrong:** Agent container can't execute docker commands despite mounted socket
**Why it happens:** Container user isn't in docker group or socket has restrictive permissions
**How to avoid:** Run container as root (safe within isolated container) or add user to host docker group
**Warning signs:** "permission denied" errors on docker commands, socket exists but isn't accessible

### Pitfall 6: Tool Result Size Explosion
**What goes wrong:** Large command outputs (logs, file dumps) exceed Claude's context window
**Why it happens:** No automatic truncation on stdout/stderr in structured return
**How to avoid:** Phase 30 is foundation - truncation logic belongs in Phase 31 agent loop
**Warning signs:** API errors about context length, very long tool results in audit logs

## Code Examples

Verified patterns from official sources:

### Async Subprocess with Timeout and Exit Code
```python
# Source: https://docs.python.org/3/library/asyncio-subprocess.html
import asyncio

async def shell_exec(command: str, timeout: float = 120.0) -> dict:
    """Execute shell command with timeout."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout
        )

        return {
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "exit_code": proc.returncode,  # Available after communicate()
            "timed_out": False,
        }

    except asyncio.TimeoutError:
        # Must kill and wait to prevent zombies
        proc.kill()
        await proc.wait()

        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "exit_code": -1,
            "timed_out": True,
        }
```

### AsyncAnthropic Client Setup
```python
# Source: https://github.com/anthropics/anthropic-sdk-python
import os
from anthropic import AsyncAnthropic

# Client initialization (reuse across conversation)
client = AsyncAnthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
)

# Basic message with await
async def call_claude():
    message = await client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello, Claude"}],
    )
    return message.content
```

### Docker Socket Mount Pattern
```yaml
# Source: Docker Compose best practices, existing docker-compose.yml
services:
  agent:
    build: ./docker/agent
    volumes:
      # Mount Docker socket for docker CLI access
      - /var/run/docker.sock:/var/run/docker.sock
      # Mount audit log directory
      - ./audit_logs:/app/audit_logs
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

### Timestamp-Based File Naming
```python
# Source: Common practice, collision resistance
from datetime import datetime
import uuid

def generate_session_filename() -> str:
    """Generate unique session audit log filename."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    random_id = str(uuid.uuid4())[:8]
    return f"{timestamp}-{random_id}.json"

# Example output: "2026-01-28T10-30-45-abc12345.json"
```

## State of the Art

| Old Approach (v2.x) | Current Approach (v3.0) | When Changed | Impact |
|---------------------|-------------------------|--------------|--------|
| Action abstractions (ActionExecutor, ActionProposal) | Direct shell access with reasoning | v3.0 pivot (2026-01-28) | Simpler code, more autonomy, faster iteration |
| Approval workflows (validate, approve, execute) | No approvals, audit-only | v3.0 pivot (2026-01-28) | Development speed over runtime safety gates |
| Predefined tool set (docker_restart, host_kill) | Single shell() tool | v3.0 pivot (2026-01-28) | Claude chooses commands, not limited to predefined actions |
| Per-action audit events | Session-based conversation logs | Phase 30 | Better reasoning chain visibility, simpler querying |
| Risk classification (LOW/MEDIUM/HIGH) | Container isolation only | v3.0 pivot (2026-01-28) | Trust boundary is container, not risk levels |

**Deprecated/outdated:**
- ActionExecutor pattern (Phase 24-26): Phase 30+ doesn't use action abstractions
- Approval workflow (Phase 14, 23): v3.0 has no approval system
- Risk levels (planned Phase 27): Superseded, all operations equally "risky" but contained
- Tool registration via get_general_tools(): v3.0 uses direct tool definitions in agent loop

## Open Questions

Things that couldn't be fully resolved:

1. **Container restart strategy after agent crashes**
   - What we know: Docker Compose can auto-restart with `restart: unless-stopped`
   - What's unclear: Should agent be stateless (restart cleans state) or resume sessions?
   - Recommendation: Phase 30 is stateless, Phase 31 decides restart behavior

2. **Audit log retention and rotation**
   - What we know: JSON files accumulate in mounted volume indefinitely
   - What's unclear: Rotation policy, max file count, compression strategy
   - Recommendation: Phase 30 writes files, Phase 32 adds optional cleanup script

3. **Tool result truncation strategy**
   - What we know: Large outputs (docker logs, file dumps) can exceed context window
   - What's unclear: Truncate in tool return or in agent loop? How much to keep?
   - Recommendation: Phase 30 returns full output, Phase 31 implements smart truncation

4. **Multi-session concurrency**
   - What we know: Current design assumes one session at a time (single unhealthy trigger)
   - What's unclear: If multiple alerts fire, should agent handle concurrently or queue?
   - Recommendation: Phase 30/31 single-threaded, v3.1+ could explore concurrent sessions

5. **Docker-in-Docker vs Docker socket mount**
   - What we know: Socket mount is simpler but shares daemon with host
   - What's unclear: Is DinD isolation worth complexity for this use case?
   - Recommendation: Phase 30 uses socket mount (simpler), DinD can be future enhancement

## Sources

### Primary (HIGH confidence)
- [Python asyncio-subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html) - Official Python 3.14 docs (verified Jan 28, 2026)
- [Anthropic SDK Python repository](https://github.com/anthropics/anthropic-sdk-python) - Official SDK with AsyncAnthropic examples
- Existing codebase patterns:
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/host/actions.py` - asyncio.create_subprocess_exec pattern
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/agent/runner.py` - AsyncAnthropic client usage
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/actions/audit.py` - Audit logging patterns
  - `/Users/jrtipton/x/operator/packages/ratelimiter-service/Dockerfile` - Slim Dockerfile pattern

### Secondary (MEDIUM confidence)
- [Docker Docs: Configure Claude Code](https://docs.docker.com/ai/sandboxes/claude-code/) - Docker best practices for Claude containers
- [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices) - Anthropic official guidance
- [Audit Logging for AI article](https://medium.com/@pranavprakash4777/audit-logging-for-ai-what-should-you-track-and-where-3de96bbf171b) - AI audit logging patterns
- [Trustworthy AI Agents: Verifiable Audit Logs](https://www.sakurasky.com/blog/missing-primitives-for-trustworthy-ai-part-5/) - Hash-chained audit patterns

### Tertiary (LOW confidence - patterns only)
- Various Alpine + curl + jq Docker images - Confirmed tooling availability but not used (python:3.12-slim chosen instead)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools already in codebase or verified in official docs
- Architecture: HIGH - Patterns extracted from existing operator-core modules
- Pitfalls: MEDIUM - Derived from common async/subprocess issues, not all verified in this codebase

**Research date:** 2026-01-28
**Valid until:** 60 days (stable domain - Python stdlib and Anthropic SDK have slow-moving APIs)

**Key decisions locked by CONTEXT.md:**
- One tool only (shell) - no web_search or web_fetch
- Python 3.12 base image
- 120 second default timeout
- Reasoning parameter required
- Structured dict returns
- Session-based JSON audit logs
- Timestamp-based file naming

**Claude's discretion:**
- Exact error message formatting in tool responses
- How to handle command timeouts (current: return timed_out flag)
- Session ID generation method (current: timestamp + uuid)
