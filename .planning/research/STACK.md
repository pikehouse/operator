# Technology Stack: Infrastructure Actions & Script Execution

**Project:** Operator v2.3
**Feature Scope:** Docker control, host operations, sandboxed script execution
**Researched:** 2026-01-27
**Overall Confidence:** HIGH

## Executive Summary

The existing stack already includes most necessary components. The project uses `python-on-whales>=0.70.0` which supports all required Docker operations (container lifecycle, exec, logs, networking). For async compatibility with the existing asyncio architecture, we'll wrap synchronous operations with `asyncio.run_in_executor()` rather than introducing a parallel async Docker library. Minimal additions: `aiofiles` for async file I/O, Python stdlib's `os` and `signal` modules for process operations (no additional dependencies needed).

**Key Decision:** Stay with python-on-whales + executor pattern rather than switching to aiodocker. Rationale: Already integrated, covers all operations, switching would require rewriting existing Docker Compose management code with marginal benefit.

---

## Existing Stack (No Changes Needed)

### Docker Operations
| Technology | Current Version | Purpose | Coverage |
|------------|-----------------|---------|----------|
| **python-on-whales** | 0.70.0+ (current: 0.80.0) | Docker CLI wrapper | Container lifecycle, exec, logs, networking |
| **Docker Compose** | via python-on-whales | Orchestration | Already managing TiKV/ratelimiter containers |

**Why no change:**
- [python-on-whales 0.80.0](https://pypi.org/project/python-on-whales/) (released 2026-01-10) supports all required operations
- Thread-safe by design (no intermediate state stored)
- [Comprehensive API coverage](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) including `docker.container.start()`, `docker.container.stop()`, `docker.container.restart()`, `docker.container.kill()`, `docker.container.exec()`, `docker.container.logs()`, `docker.network.connect()`, `docker.network.disconnect()`
- Already integrated with existing deployment infrastructure
- Synchronous operations work fine with asyncio via `run_in_executor()`

**Alternative considered:** [aiodocker 0.25.0](https://pypi.org/project/aiodocker/) provides native async/await Docker API. **Rejected** because:
1. Would require rewriting existing Docker Compose management
2. Performance benefit minimal for operator use case (not high-frequency Docker operations)
3. Adds dependency on aiohttp (not currently used elsewhere in stack)
4. python-on-whales is sufficient when wrapped with executor pattern

### Process Operations
| Technology | Version | Purpose | Why Sufficient |
|------------|---------|---------|----------------|
| **Python stdlib: os** | stdlib (Python 3.11+) | Process signaling | `os.kill(pid, signal)` for SIGTERM/SIGKILL |
| **Python stdlib: signal** | stdlib (Python 3.11+) | Signal constants | SIGTERM, SIGKILL, SIGINT constants |

**Why no psutil:**
- [psutil 7.2.1](https://pypi.org/project/psutil/) is feature-rich but overkill for simple signaling
- stdlib `os.kill()` handles required operations (send signals to processes)
- [asyncio loop.add_signal_handler()](https://docs.python.org/3/library/asyncio-eventloop.html) for receiving signals
- psutil is synchronous-only, would still require executor wrapping
- Avoid dependency bloat for operations stdlib already provides

---

## Required Additions

### Async File Operations
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **aiofiles** | 25.1.0+ | Async file I/O | Non-blocking file read/write for host operations |

**Installation:**
```bash
uv add "aiofiles>=25.1.0"
```

**Rationale:**
- [aiofiles 25.1.0](https://pypi.org/project/aiofiles/) (released 2025-10-09) supports Python 3.9-3.14
- Integrates seamlessly with existing asyncio architecture
- Host file operations (read/write) need async to avoid blocking event loop
- Simple API: `async with aiofiles.open(path, mode) as f: content = await f.read()`
- Delegates I/O to thread pool automatically (same pattern as run_in_executor but cleaner API)

**Alternatives considered:**
- **aiopath**: Pathlib-like async interface. Rejected because adds abstraction overhead; aiofiles' explicit open/read/write is clearer for action implementations
- **anyio**: Cross-framework async (trio/asyncio). Rejected because project is asyncio-only; unnecessary abstraction
- **Plain stdlib + run_in_executor**: Would work but aiofiles provides cleaner, more maintainable code

### Sandbox Container Images

For script execution, we need minimal base images with Python/bash interpreters.

**Base Images (no Python dependencies, pulled at runtime):**
- `python:3.11-slim` (for Python script execution)
- `bash:5.2-alpine` (for bash script execution)

**Why these:**
- **python:3.11-slim**: Matches project's Python 3.11+ requirement, includes pip for potential library installation
- **bash:5.2-alpine**: Minimal shell environment (~2MB vs ~50MB for Ubuntu)
- Official images, regularly updated, security-patched
- No custom Dockerfile needed (reduces maintenance)

**Security configuration (applied via python-on-whales):**
```python
docker.run(
    image="python:3.11-slim",
    command=["python", "/sandbox/script.py"],
    volumes=["/host/path:/sandbox:ro"],  # Read-only mount
    network_mode="none",                  # No network access
    user="nobody",                        # Non-root execution
    remove=True,                          # Auto-cleanup
    cpus=1.0,                            # CPU limit
    memory="512m",                       # Memory limit
)
```

**Security layers applied:**
1. **Default seccomp profile**: [Docker's default](https://docs.docker.com/engine/security/seccomp/) blocks ~51 dangerous syscalls (e.g., `unshare`, `mount`, `reboot`)
2. **No network**: `network_mode="none"` prevents external communication
3. **Non-root user**: Run as `nobody` (UID 65534) to prevent privilege escalation
4. **Resource limits**: CPU and memory caps prevent resource exhaustion
5. **Read-only volumes**: Scripts can't modify host filesystem
6. **Ephemeral containers**: `remove=True` ensures no persistent state

**Reference:** [Setting Up a Secure Python Sandbox for LLM Agents](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents) and [epicbox security model](https://github.com/StepicOrg/epicbox) (AppArmor + Docker isolation).

---

## Integration Patterns

### Async Wrapping for python-on-whales

python-on-whales is synchronous (calls Docker CLI via subprocess). Wrap with executor for async compatibility:

```python
import asyncio
from python_on_whales import docker

async def docker_container_start(container_id: str) -> None:
    """Start container asynchronously."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,  # Default ThreadPoolExecutor
        docker.container.start,
        container_id
    )
```

**Why this works:**
- [python-on-whales is thread-safe](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) (no shared state)
- Docker daemon handles concurrent requests internally
- Executor offloads blocking subprocess calls to thread pool
- Standard pattern used throughout Python async ecosystem for blocking I/O

**Pattern for all Docker operations:**
- Container lifecycle: `docker.container.{start,stop,restart,kill}` → wrap with executor
- Exec: `docker.container.exec()` → wrap with executor
- Logs: `docker.container.logs()` → wrap with executor (returns generator, consume in thread)
- Networking: `docker.network.{connect,disconnect}` → wrap with executor

### File Operations with aiofiles

```python
import aiofiles

async def read_host_file(path: str) -> str:
    """Read file from host asynchronously."""
    async with aiofiles.open(path, mode='r') as f:
        return await f.read()

async def write_host_file(path: str, content: str) -> None:
    """Write file to host asynchronously."""
    async with aiofiles.open(path, mode='w') as f:
        await f.write(content)
```

**Error handling:**
- Wrap in try/except for `FileNotFoundError`, `PermissionError`
- Validate paths to prevent directory traversal (e.g., reject `../` patterns)

### Process Signaling (stdlib only)

```python
import os
import signal
import asyncio

async def send_signal_to_process(pid: int, sig: signal.Signals) -> None:
    """Send signal to process asynchronously."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        os.kill,
        pid,
        sig
    )

# Usage
await send_signal_to_process(12345, signal.SIGTERM)  # Graceful shutdown
await send_signal_to_process(12345, signal.SIGKILL)  # Force kill
```

**Why executor wrapping:**
- `os.kill()` is fast (syscall) but best practice to avoid blocking event loop
- Consistent pattern with other blocking operations

### Script Execution Pattern

```python
import aiofiles
import asyncio
from python_on_whales import docker

async def execute_python_script(script_content: str) -> dict:
    """Execute Python script in sandbox, return output."""
    # Write script to temp file
    script_path = "/tmp/operator_script.py"
    async with aiofiles.open(script_path, mode='w') as f:
        await f.write(script_content)

    # Execute in sandbox container
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: docker.run(
            image="python:3.11-slim",
            command=["python", "/sandbox/script.py"],
            volumes=[(script_path, "/sandbox/script.py")],
            network_mode="none",
            user="nobody",
            remove=True,
            cpus=1.0,
            memory="512m",
        )
    )

    return {
        "stdout": result,  # docker.run returns stdout
        "exit_code": 0,    # Non-zero exit raises exception
    }
```

**Capture considerations:**
- `docker.run()` returns stdout as string (stderr merged by default)
- Exceptions raised on non-zero exit codes (catch and return error)
- Timeout via `docker.run(..., timeout=30)` to prevent infinite loops
- Clean up temp files after execution

---

## Version Summary

| Component | Version | Source | Confidence |
|-----------|---------|--------|------------|
| python-on-whales | 0.80.0 | [PyPI verified](https://pypi.org/project/python-on-whales/) | HIGH |
| aiofiles | 25.1.0 | [PyPI verified](https://pypi.org/project/aiofiles/) | HIGH |
| os/signal | stdlib | Python 3.11+ docs | HIGH |
| python:3.11-slim | latest | Docker Hub official | HIGH |
| bash:5.2-alpine | latest | Docker Hub official | HIGH |

---

## Installation Steps

```bash
# Add new dependency to operator-core
cd packages/operator-core
uv add "aiofiles>=25.1.0"

# Verify Docker images available (pulled automatically on first use)
docker pull python:3.11-slim
docker pull bash:5.2-alpine
```

**No other changes needed.** Existing dependencies cover all Docker operations.

---

## Security Considerations

### Docker Sandbox Hardening

| Layer | Configuration | Risk Mitigated |
|-------|--------------|----------------|
| Seccomp | Default profile | Blocks 51 dangerous syscalls (container escape) |
| Network | `network_mode="none"` | Prevents data exfiltration, C2 communication |
| User | `user="nobody"` | Limits damage from privilege escalation exploits |
| Resources | `cpus=1.0, memory="512m"` | Prevents DoS via resource exhaustion |
| Filesystem | Read-only volumes | Prevents host filesystem tampering |
| Ephemeral | `remove=True` | No persistent backdoors in containers |

**Known Limitations:**
- Docker isolation is not a security boundary ([kernel vulnerabilities affect all containers](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents))
- For production use with untrusted AI-generated code, consider: (1) separate infrastructure for script execution, (2) gVisor for enhanced kernel isolation, (3) AppArmor profiles for additional syscall filtering

**Acceptable for operator use case because:**
- Scripts generated by Claude (not arbitrary user input)
- Running on operator's own infrastructure (not multi-tenant)
- Actions already require authentication
- Defense-in-depth via multiple layers (seccomp + network isolation + non-root + resource limits)

### Host File Operation Constraints

**Implement in action layer:**
- **Path validation:** Reject `../` patterns, absolute paths only
- **Allowlist:** Restrict to specific directories (e.g., `/var/log/operator/`, `/etc/operator/`)
- **Size limits:** Reject reads >10MB, writes >1MB
- **Permission checks:** Verify file permissions before operations

**Rationale:** Actions run with operator's privileges. Limit blast radius of buggy/malicious actions.

### Process Signaling Constraints

**Implement in action layer:**
- **PID validation:** Verify PID exists and belongs to managed service
- **Signal allowlist:** Only SIGTERM (15) and SIGKILL (9)
- **Ownership check:** Ensure process owned by operator user
- **Rate limiting:** Prevent signal spam

---

## Alternatives Considered

### aiodocker vs python-on-whales

**aiodocker advantages:**
- Native async/await (no executor wrapping)
- Direct HTTP API access (no subprocess overhead)

**aiodocker disadvantages:**
- Requires rewriting existing Docker Compose code
- Adds aiohttp dependency (unused elsewhere in stack)
- Marginal performance benefit (Docker operations not high-frequency)
- Different API paradigm (HTTP vs CLI) increases cognitive load

**Decision:** Stay with python-on-whales. Executor pattern is idiomatic Python async for blocking I/O.

### psutil vs stdlib (os/signal)

**psutil advantages:**
- Rich process introspection (CPU%, memory%, open files)
- Cross-platform abstractions

**psutil disadvantages:**
- Synchronous-only (still needs executor wrapping)
- Large dependency for simple signaling operations
- Operator only needs `kill()` (stdlib sufficient)

**Decision:** Use stdlib. Add psutil later if process monitoring needed.

### Custom Docker Sandbox Library vs Direct python-on-whales

**Custom library (e.g., [epicbox](https://github.com/StepicOrg/epicbox)):**
- Higher-level API for sandboxing
- Built-in security profiles

**Direct python-on-whales:**
- Lower-level control over container configuration
- No additional dependency
- Security configuration explicit in action code (easier to audit)

**Decision:** Direct python-on-whales. Operator has specific needs (output capture, resource limits) better served by explicit configuration.

---

## Open Questions / Future Considerations

1. **Script library installation:** If Python scripts need external libraries (e.g., `requests`), consider:
   - Pre-built images with common libraries (increases image size)
   - Dynamic `pip install` in sandbox (increases execution time)
   - Allowlist of approved libraries (reduces risk)

   **Recommendation:** Start with no external libraries. Add if needed based on actual use cases.

2. **Script execution timeout:** What's appropriate timeout?
   - Short (30s): Prevents runaway scripts, may terminate slow operations
   - Long (5m): Accommodates slow operations, delays failure detection

   **Recommendation:** Start with 60s, make configurable per action.

3. **Output size limits:** Scripts could generate massive output (DoS).
   - Recommendation: Cap at 1MB, truncate with warning.

4. **Multi-language support:** Currently Python/bash. Future: Go, Rust?
   - Recommendation: Start with Python/bash. Add languages based on demand.

---

## Sources

### High Confidence (Official Documentation)
- [python-on-whales PyPI](https://pypi.org/project/python-on-whales/) - Version and release info
- [python-on-whales Documentation](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) - API reference
- [aiofiles PyPI](https://pypi.org/project/aiofiles/) - Version and Python compatibility
- [aiodocker PyPI](https://pypi.org/project/aiodocker/) - Alternative Docker library
- [psutil PyPI](https://pypi.org/project/psutil/) - Process utilities
- [Python asyncio Documentation](https://docs.python.org/3/library/asyncio-eventloop.html) - Event loop and signals
- [Docker Seccomp Security](https://docs.docker.com/engine/security/seccomp/) - Security profiles

### Medium Confidence (Community/Tutorials)
- [Setting Up a Secure Python Sandbox for LLM Agents](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents) - Security patterns
- [epicbox GitHub](https://github.com/StepicOrg/epicbox) - Sandbox reference implementation
- [Docker Python-on-whales Blog](https://www.docker.com/blog/guest-post-calling-the-docker-cli-from-python-with-python-on-whales/) - Usage patterns
- [Twilio aiofiles Tutorial](https://www.twilio.com/en-us/blog/developers/tutorials/building-blocks/working-with-files-asynchronously-in-python-using-aiofiles-and-asyncio) - Async file I/O patterns

### Search Results (Supporting)
- [Python on whales asyncio](https://github.com/gabrieldemarmiesse/python-on-whales) - Threading safety
- [aiodocker GitHub](https://github.com/aio-libs/aiodocker) - Async Docker API
- [Docker seccomp best practices](https://martinheinz.dev/blog/41) - Hardening guide
- [Asyncio signal handling](https://superfastpython.com/asyncio-control-c-sigint/) - Signal patterns
