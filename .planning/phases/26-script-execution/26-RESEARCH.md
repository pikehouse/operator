# Phase 26: Script Execution & Validation - Research

**Researched:** 2026-01-28
**Domain:** Python/Bash script execution in Docker sandboxes with multi-layer validation
**Confidence:** HIGH

## Summary

This phase implements an agent-callable script execution system that validates and runs Python/Bash scripts in sandboxed Docker containers. The system uses a two-phase architecture: (1) multi-layer validation (syntax, secrets, dangerous patterns) followed by (2) sandboxed execution with strict resource limits.

The implementation leverages the existing `python-on-whales` library already used in the codebase for Docker operations, extending the `DockerActionExecutor` pattern established in Phase 24. Script validation uses Python's `ast` module for Python syntax checking and `bash -n` for Bash syntax checking, combined with regex-based pattern scanning for secrets and dangerous commands.

**Primary recommendation:** Create a `ScriptExecutor` class in a new `scripts/` module that handles validation and execution, with `execute_script` registered as a tool via `get_general_tools()` following the existing pattern from `actions/tools.py`.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-on-whales | (existing) | Docker container operations | Already in codebase, provides `docker.run()` with all required parameters |
| ast (stdlib) | Python 3.11+ | Python syntax validation | Standard library, `ast.parse()` validates without executing |
| re (stdlib) | Python 3.11+ | Pattern matching for secrets/dangerous code | Standard library, sufficient for simple pattern matching |
| asyncio (stdlib) | Python 3.11+ | Async subprocess management | Already used throughout codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| subprocess | Python 3.11+ | bash -n syntax validation | Only for bash script validation (async subprocess) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ast.parse() | bandit | Bandit is overkill for syntax check; ast.parse is simpler and faster |
| regex patterns | detect-secrets | detect-secrets adds dependency; simple patterns meet requirements |
| bash -n | shellcheck | ShellCheck more thorough but adds external dependency; bash -n meets requirements |

**Installation:**
```bash
# No new dependencies - all tools already available or in stdlib
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/src/operator_core/
├── scripts/
│   ├── __init__.py          # Module exports
│   ├── executor.py          # ScriptExecutor class
│   ├── validation.py        # ScriptValidator with all validation layers
│   └── patterns.py          # Regex patterns for secrets/dangerous code
├── actions/
│   └── tools.py             # Add execute_script to get_general_tools()
```

### Pattern 1: Two-Phase Script Execution
**What:** Validate first, execute only if validation passes
**When to use:** Always - validation must gate execution
**Example:**
```python
# Source: Project requirements VALD-06
async def execute_script(
    script_content: str,
    script_type: str,  # "python" or "bash"
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute validated script in sandbox."""
    # Phase 1: Validate
    validation_result = validate_script(script_content, script_type)
    if not validation_result.valid:
        return {
            "success": False,
            "error": validation_result.error,
            "validation_failed": True,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
        }

    # Phase 2: Execute in sandbox
    return await run_in_sandbox(script_content, script_type, timeout)
```

### Pattern 2: Multi-Layer Validation
**What:** Chain validators, fail on first error with descriptive message
**When to use:** For script validation before execution
**Example:**
```python
# Source: Requirements VALD-01 through VALD-06
@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None
    layer: str | None = None  # Which validation layer failed

def validate_script(content: str, script_type: str) -> ValidationResult:
    """Run all validation layers in sequence."""
    # Layer 1: Size check (VALD-05)
    if len(content) > 10000:
        return ValidationResult(
            valid=False,
            error=f"Script exceeds 10000 character limit ({len(content)} chars)",
            layer="size",
        )

    # Layer 2: Syntax check (VALD-01, VALD-02)
    syntax_result = validate_syntax(content, script_type)
    if not syntax_result.valid:
        return syntax_result

    # Layer 3: Secrets scan (VALD-03)
    secrets_result = scan_for_secrets(content)
    if not secrets_result.valid:
        return secrets_result

    # Layer 4: Dangerous patterns (VALD-04)
    danger_result = scan_for_dangerous_patterns(content, script_type)
    if not danger_result.valid:
        return danger_result

    return ValidationResult(valid=True)
```

### Pattern 3: Sandboxed Execution with python-on-whales
**What:** Use docker.run() with strict security constraints
**When to use:** For all script execution
**Example:**
```python
# Source: python-on-whales docs, project requirements SCRP-02 through SCRP-07
from python_on_whales import docker

async def run_in_sandbox(
    script_content: str,
    script_type: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute script in isolated Docker container."""
    loop = asyncio.get_running_loop()

    def _blocking_run():
        image = "python:3.11-slim" if script_type == "python" else "bash:5.2-alpine"
        command = ["python", "-c", script_content] if script_type == "python" else ["bash", "-c", script_content]

        try:
            output = docker.run(
                image,
                command,
                # Security constraints (SCRP-03, SCRP-04, SCRP-05)
                networks=["none"],        # Network isolation
                memory="512m",            # RAM limit
                cpus=1.0,                 # CPU limit
                pids_limit=100,           # PID limit
                user="nobody",            # Non-root user
                read_only=True,           # Read-only root filesystem
                remove=True,              # Ephemeral container (SCRP-06)
                # Timeout handling
                stop_timeout=timeout,     # Container stop timeout
            )
            return {"success": True, "stdout": output, "stderr": "", "exit_code": 0}
        except Exception as e:
            # Capture error details
            return {"success": False, "stdout": "", "stderr": str(e), "exit_code": 1}

    return await loop.run_in_executor(None, _blocking_run)
```

### Pattern 4: Async Timeout with Cleanup
**What:** Wrap blocking Docker operations with asyncio timeout
**When to use:** For enforcing script timeout (SCRP-07)
**Example:**
```python
# Source: Python asyncio docs
async def execute_with_timeout(
    script_content: str,
    script_type: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute with timeout and forced cleanup."""
    try:
        return await asyncio.wait_for(
            run_in_sandbox(script_content, script_type, timeout),
            timeout=timeout + 5,  # Extra buffer for Docker cleanup
        )
    except asyncio.TimeoutError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Script execution timed out after {timeout}s",
            "exit_code": -1,
            "timeout": True,
        }
```

### Anti-Patterns to Avoid
- **Executing before validation:** Always validate first, never execute unchecked scripts
- **Using shell=True in subprocess:** Enables injection attacks; use array arguments
- **Blacklisting dangerous patterns:** Use whitelisting where possible; blacklist is incomplete
- **Trusting script_type parameter:** Always validate the actual content matches claimed type
- **Skipping size limits:** Large scripts can cause memory/CPU issues even in sandbox

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Python syntax check | Custom parser | `ast.parse()` | Full Python grammar, catches all syntax errors |
| Bash syntax check | Regex patterns | `bash -n` | Bash itself knows its grammar best |
| Docker container run | Direct Docker API | `python-on-whales` | Already in codebase, handles all options |
| Async subprocess | Threading | `asyncio.create_subprocess_exec` | Built-in, handles timeout properly |
| Secret patterns | Custom regex from scratch | Established patterns | Well-tested, covers common cases |

**Key insight:** Script validation is a security boundary - use battle-tested standard library functions (ast.parse, bash -n) rather than custom parsing that may have gaps.

## Common Pitfalls

### Pitfall 1: ast.parse() Resource Exhaustion
**What goes wrong:** Deeply nested or very long scripts can crash Python's AST compiler
**Why it happens:** AST parsing uses recursive descent with limited stack depth
**How to avoid:** Enforce content size limit (10000 chars per VALD-05) BEFORE ast.parse()
**Warning signs:** Scripts with many nested brackets, deeply recursive structures

### Pitfall 2: bash -n False Negatives
**What goes wrong:** bash -n validates syntax but misses runtime errors and external command issues
**Why it happens:** bash -n only parses, doesn't resolve commands or variables
**How to avoid:** Understand bash -n is syntax-only; combine with pattern scanning
**Warning signs:** Scripts that use `[` (it's an external command, not bash syntax)

### Pitfall 3: Network Isolation Bypass via Mounted Volumes
**What goes wrong:** Script accesses network via mounted socket or file
**Why it happens:** Volume mounts can expose host resources
**How to avoid:** Never mount volumes; use `read_only=True` and no volume parameters
**Warning signs:** Any request to mount directories or files

### Pitfall 4: Output Capture Memory Exhaustion
**What goes wrong:** Script produces gigabytes of output, exhausts host memory
**Why it happens:** Docker captures all stdout/stderr before returning
**How to avoid:** Memory limit on container (512MB) implicitly limits output
**Warning signs:** Scripts with infinite loops printing data

### Pitfall 5: Timeout Not Actually Enforced
**What goes wrong:** Container keeps running after timeout
**Why it happens:** Docker stop_timeout only affects SIGTERM grace period, not total runtime
**How to avoid:** Use asyncio.wait_for() at Python level to forcibly kill container
**Warning signs:** Long-running containers surviving past timeout

### Pitfall 6: Pattern Detection False Positives
**What goes wrong:** Legitimate scripts blocked for containing "password" in comments
**Why it happens:** Simple regex matches without context
**How to avoid:** Match patterns like `password=` or `API_KEY=` with assignment operators
**Warning signs:** Users complaining about valid scripts being rejected

## Code Examples

Verified patterns from official sources:

### Python Syntax Validation (VALD-01)
```python
# Source: Python ast documentation
import ast

def validate_python_syntax(script_content: str) -> ValidationResult:
    """Validate Python script syntax using ast.parse()."""
    try:
        ast.parse(script_content)
        return ValidationResult(valid=True)
    except SyntaxError as e:
        return ValidationResult(
            valid=False,
            error=f"Python syntax error at line {e.lineno}: {e.msg}",
            layer="syntax",
        )
```

### Bash Syntax Validation (VALD-02)
```python
# Source: Bash manual, asyncio subprocess docs
import asyncio

async def validate_bash_syntax(script_content: str) -> ValidationResult:
    """Validate Bash script syntax using bash -n."""
    proc = await asyncio.create_subprocess_exec(
        "bash", "-n",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(script_content.encode("utf-8"))

    if proc.returncode == 0:
        return ValidationResult(valid=True)
    else:
        return ValidationResult(
            valid=False,
            error=f"Bash syntax error: {stderr.decode('utf-8').strip()}",
            layer="syntax",
        )
```

### Secret Pattern Detection (VALD-03)
```python
# Source: secrets-patterns-db, detect-secrets patterns
import re

# Patterns for common secret assignments
SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key)\s*[=:]\s*['\"][^'\"]+['\"]", "API key assignment"),
    (r"(?i)(password)\s*[=:]\s*['\"][^'\"]+['\"]", "password assignment"),
    (r"(?i)(token)\s*[=:]\s*['\"][^'\"]+['\"]", "token assignment"),
    (r"(?i)(secret)\s*[=:]\s*['\"][^'\"]+['\"]", "secret assignment"),
    (r"(?i)(aws_access_key_id)\s*[=:]\s*['\"][A-Z0-9]{20}['\"]", "AWS access key"),
    (r"(?i)(aws_secret_access_key)\s*[=:]\s*", "AWS secret key"),
    (r"-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
]

def scan_for_secrets(script_content: str) -> ValidationResult:
    """Scan script for potential secrets."""
    for pattern, description in SECRET_PATTERNS:
        if re.search(pattern, script_content):
            return ValidationResult(
                valid=False,
                error=f"Potential secret detected: {description}",
                layer="secrets",
            )
    return ValidationResult(valid=True)
```

### Dangerous Pattern Detection (VALD-04)
```python
# Source: Python security best practices, bandit patterns
import re

# Python dangerous patterns
PYTHON_DANGEROUS_PATTERNS = [
    (r"\beval\s*\(", "eval() function"),
    (r"\bexec\s*\(", "exec() function"),
    (r"\b__import__\s*\(", "__import__() function"),
    (r"\bos\.system\s*\(", "os.system() call"),
    (r"\bsubprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True", "subprocess with shell=True"),
    (r"\bcompile\s*\(", "compile() function"),
    (r"\bgetattr\s*\(.*['\"]__", "getattr with dunder access"),
]

# Bash dangerous patterns
BASH_DANGEROUS_PATTERNS = [
    (r"\beval\s+", "eval command"),
    (r"\$\(\s*\$", "nested command substitution"),
    (r"\bcurl\s+.*\|\s*(bash|sh)", "curl piped to shell"),
    (r"\bwget\s+.*\|\s*(bash|sh)", "wget piped to shell"),
]

def scan_for_dangerous_patterns(
    script_content: str,
    script_type: str,
) -> ValidationResult:
    """Scan for dangerous code patterns."""
    patterns = PYTHON_DANGEROUS_PATTERNS if script_type == "python" else BASH_DANGEROUS_PATTERNS

    for pattern, description in patterns:
        if re.search(pattern, script_content):
            return ValidationResult(
                valid=False,
                error=f"Dangerous pattern detected: {description}",
                layer="dangerous",
            )
    return ValidationResult(valid=True)
```

### Docker Sandbox Execution
```python
# Source: python-on-whales docs, Docker security best practices
from python_on_whales import docker
import asyncio

async def execute_in_sandbox(
    script_content: str,
    script_type: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute validated script in sandboxed Docker container."""
    loop = asyncio.get_running_loop()

    def _blocking_execute():
        # Select image based on script type (SCRP-02)
        if script_type == "python":
            image = "python:3.11-slim"
            command = ["python", "-c", script_content]
        else:
            image = "bash:5.2-alpine"
            command = ["bash", "-c", script_content]

        try:
            # Run with all security constraints
            output = docker.run(
                image,
                command,
                # Network isolation (SCRP-03)
                networks=["none"],
                # Resource limits (SCRP-04)
                memory="512m",
                cpus=1.0,
                pids_limit=100,
                # Non-root user (SCRP-05)
                user="nobody",
                # Read-only filesystem
                read_only=True,
                # Ephemeral container (SCRP-06)
                remove=True,
                # Capture output
                detach=False,
            )
            return {
                "success": True,
                "stdout": output if output else "",
                "stderr": "",
                "exit_code": 0,
            }
        except Exception as e:
            error_str = str(e)
            # python-on-whales raises exception on non-zero exit
            exit_code = 1
            return {
                "success": False,
                "stdout": "",
                "stderr": error_str,
                "exit_code": exit_code,
            }

    # Wrap with timeout (SCRP-07)
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _blocking_execute),
            timeout=timeout + 5,  # Buffer for container cleanup
        )
        return result
    except asyncio.TimeoutError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Script execution timed out after {timeout}s",
            "exit_code": -1,
            "timeout": True,
        }
```

### Tool Registration Pattern
```python
# Source: Existing actions/tools.py pattern
from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType

def get_script_tools() -> list[ActionDefinition]:
    """Get script execution tool definitions."""
    return [
        ActionDefinition(
            name="execute_script",
            description="Execute a Python or Bash script in a sandboxed container. Scripts are validated for syntax, secrets, and dangerous patterns before execution.",
            parameters={
                "script_content": ParamDef(
                    type="str",
                    description="The script content to execute (max 10000 characters)",
                    required=True,
                ),
                "script_type": ParamDef(
                    type="str",
                    description="Script language: 'python' or 'bash'",
                    required=True,
                ),
                "timeout": ParamDef(
                    type="int",
                    description="Execution timeout in seconds (default: 60, max: 300)",
                    required=False,
                    default=60,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",  # Arbitrary code execution
            requires_approval=True,  # Always require approval
        ),
    ]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| docker-py SDK | python-on-whales | 2022+ | Better CLI parity, async-friendly |
| eval() with sandboxing | Never use eval | Always | eval is fundamentally unsafe |
| Blacklist validation | Whitelist + blacklist | Current | Defense in depth |
| Shared containers | Ephemeral containers | Current | Better isolation |

**Deprecated/outdated:**
- docker-py for new projects: python-on-whales preferred for CLI compatibility
- RestrictedPython: Complex, still has escapes; isolation is better
- eval with globals restriction: Can always be bypassed; don't use eval

## Open Questions

Things that couldn't be fully resolved:

1. **Separate stdout/stderr capture**
   - What we know: python-on-whales `docker.run()` returns combined output as string
   - What's unclear: Whether stderr can be captured separately
   - Recommendation: May need to redirect stderr in the script itself, or accept combined output

2. **Container exit code capture**
   - What we know: python-on-whales raises exception on non-zero exit
   - What's unclear: Exact exit code extraction from exception
   - Recommendation: Parse exception message or catch specific exception types

3. **Timeout enforcement granularity**
   - What we know: stop_timeout affects SIGTERM grace period
   - What's unclear: Whether container is forcibly killed or just signaled
   - Recommendation: Combine stop_timeout with asyncio.wait_for() for double-layer timeout

## Sources

### Primary (HIGH confidence)
- python-on-whales docs: https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/container/
- Python ast module: https://docs.python.org/3/library/ast.html
- Python asyncio subprocess: https://docs.python.org/3/library/asyncio-subprocess.html
- Docker security best practices: https://docs.docker.com/build/building/best-practices/

### Secondary (MEDIUM confidence)
- secrets-patterns-db: https://github.com/mazen160/secrets-patterns-db
- Bash validation with bash -n: https://www.baeldung.com/linux/validate-bash-script
- Docker sandbox security: https://cloudnativenow.com/topics/cloudnativedevelopment/docker/docker-security-in-2025-best-practices-to-protect-your-containers-from-cyberthreats/

### Tertiary (LOW confidence)
- WebSearch results for pattern detection (needs validation)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses existing codebase libraries (python-on-whales) and Python stdlib
- Architecture: HIGH - Follows existing DockerActionExecutor and tools.py patterns
- Validation patterns: HIGH - ast.parse() and bash -n are well-documented
- Secret/dangerous patterns: MEDIUM - Based on common patterns, may need tuning
- Timeout handling: MEDIUM - Multiple approaches possible, asyncio.wait_for recommended

**Research date:** 2026-01-28
**Valid until:** 2026-02-28 (30 days - stable domain)
