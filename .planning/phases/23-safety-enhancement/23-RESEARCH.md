# Phase 23: Safety Enhancement - Research

**Researched:** 2026-01-27
**Domain:** Python asyncio security patterns, TOCTOU prevention, secret redaction, process cancellation
**Confidence:** MEDIUM-HIGH

## Summary

This research covers enhancements to the existing operator-core safety system to handle advanced attack vectors: TOCTOU races, agent identity confusion, secret leakage in audit logs, and incomplete kill switch functionality.

The standard approach for TOCTOU prevention combines asyncio.Lock with double-check patterns and optimistic locking using version fields. Secret redaction uses regex-based detection libraries like detect-secrets with customizable patterns. Kill switch enhancement requires subprocess management for Docker containers since asyncio.Task.cancel() cannot force-terminate blocking operations. Session risk tracking implements cumulative scoring across action chains using behavioral analytics patterns.

**Primary recommendation:** Use asyncio.Lock with optimistic locking (version field pattern) for TOCTOU-resistant approval workflows, integrate detect-secrets library for audit log redaction, implement subprocess-based Docker container termination for kill switch, and add session-level risk accumulator with configurable thresholds.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio | stdlib (3.11+) | Async concurrency primitives | Built-in Lock, Task cancellation, event loop control |
| detect-secrets | 1.5.0+ | Secret detection and redaction | Industry standard from Yelp, 28 detection plugins, enterprise-proven |
| pydantic | 2.x | Data validation and serialization | Already in use for ActionProposal, handles datetime validation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiosqlite | 0.19+ | Async SQLite operations | Already in use, needed for atomic state checks |
| subprocess | stdlib | Process management | Docker container force-termination |
| datetime | stdlib | Timestamp comparison | Token expiration, temporal validation |
| re | stdlib | Regex pattern matching | Custom secret patterns if needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| detect-secrets | Custom regex | detect-secrets has 28 plugins, extensive testing, and enterprise validation vs fragile DIY patterns |
| asyncio.Lock | Database transactions | Lock is simpler for in-memory state; transactions needed for cross-process coordination |
| subprocess | asyncio with shields | subprocess gives true OS-level termination; asyncio can't force-kill blocking operations |

**Installation:**
```bash
pip install detect-secrets>=1.5.0
# asyncio, subprocess, datetime, re are stdlib
```

## Architecture Patterns

### Recommended Project Structure
```
operator-core/src/operator_core/actions/
├── safety.py           # SafetyController (existing)
├── audit.py            # ActionAuditor (existing - enhance with redaction)
├── executor.py         # ActionExecutor (existing - add TOCTOU checks)
├── types.py            # ActionProposal (existing - add approval_token, approved_at)
├── session.py          # NEW: SessionRiskTracker
└── secrets.py          # NEW: SecretRedactor wrapper around detect-secrets
```

### Pattern 1: TOCTOU-Resistant Approval with Optimistic Locking
**What:** Double-check pattern with asyncio.Lock + version field to detect state changes between approval and execution
**When to use:** Before executing any approved action that modifies infrastructure

**Example:**
```python
# Source: Official Python docs + optimistic locking research
import asyncio
from datetime import datetime, timedelta

class ApprovalWorkflow:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def execute_with_verification(
        self,
        proposal_id: int,
        approval_token: str,
        db: ActionDB
    ) -> ActionRecord:
        """
        TOCTOU-resistant execution with state re-verification.

        Implements double-check locking pattern:
        1. Check approval status (fast path)
        2. Acquire lock
        3. Re-check approval status and system state (TOCTOU defense)
        4. Verify token not expired
        5. Execute if all checks pass
        """
        # Fast path: check if approved (no lock needed)
        proposal = await db.get_proposal(proposal_id)
        if not proposal.is_approved:
            raise ApprovalRequiredError(proposal_id, proposal.action_name)

        # Acquire lock for state verification and execution
        async with self._lock:
            # CRITICAL: Re-fetch after acquiring lock
            proposal = await db.get_proposal(proposal_id)

            # TOCTOU Defense: Verify nothing changed
            if not proposal.is_approved:
                raise StateChangedError(
                    f"Proposal {proposal_id} approval was revoked"
                )

            # Check token expiration (60 second window)
            if proposal.approved_at:
                age = (datetime.now() - proposal.approved_at).total_seconds()
                if age > 60:
                    await db.expire_approval(proposal_id)
                    raise ApprovalExpiredError(
                        f"Approval token expired ({age:.1f}s > 60s)"
                    )

            # Verify approval token matches (prevents replay attacks)
            if proposal.approval_token != approval_token:
                raise InvalidTokenError("Approval token mismatch")

            # Optional: Check system state hasn't changed
            # (e.g., target container still exists, network accessible)
            system_state_hash = await self._get_system_state_hash()
            if proposal.expected_state_hash != system_state_hash:
                raise StateChangedError(
                    "System state changed since approval"
                )

            # All checks passed - execute action
            return await self._execute_action(proposal)
```

### Pattern 2: Optimistic Locking with Version Field
**What:** Add version column to proposals table, increment on every update, detect concurrent modifications
**When to use:** Multi-process environments or when database is shared across executors

**Example:**
```python
# Source: Optimistic locking research + DynamoDB patterns
class ActionProposal(BaseModel):
    # ... existing fields ...
    version: int = Field(default=1, description="Optimistic lock version")
    approval_token: str | None = Field(
        default=None,
        description="One-time token for approval verification"
    )
    expected_state_hash: str | None = Field(
        default=None,
        description="Hash of system state at approval time"
    )

# In ActionDB:
async def update_proposal_status(
    self,
    proposal_id: int,
    status: ActionStatus,
    expected_version: int
) -> bool:
    """
    Update proposal status with optimistic lock check.

    Returns True if update succeeded, False if version mismatch
    (indicating concurrent modification).
    """
    async with aiosqlite.connect(self.db_path) as conn:
        cursor = await conn.execute(
            """
            UPDATE action_proposals
            SET status = ?, version = version + 1
            WHERE id = ? AND version = ?
            """,
            (status.value, proposal_id, expected_version)
        )
        await conn.commit()
        return cursor.rowcount > 0

# Usage:
proposal = await db.get_proposal(proposal_id)
success = await db.update_proposal_status(
    proposal_id,
    ActionStatus.EXECUTING,
    expected_version=proposal.version
)
if not success:
    raise ConcurrentModificationError(
        f"Proposal {proposal_id} was modified by another process"
    )
```

### Pattern 3: Secret Redaction in Audit Logging
**What:** Detect and redact secrets before writing to audit logs using detect-secrets library
**When to use:** All audit log writes, especially event_data containing parameters

**Example:**
```python
# Source: detect-secrets documentation + OWASP patterns
from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings
import re

class SecretRedactor:
    """
    Wrapper around detect-secrets for audit log sanitization.
    """

    # Common patterns for environment variable secrets
    ENV_VAR_PATTERNS = [
        re.compile(r'(API_KEY|TOKEN|PASSWORD|SECRET)=[^,\s}]+', re.IGNORECASE),
        re.compile(r'(apiKey|token|password|secret)["\']\s*:\s*["\'][^"\']+', re.IGNORECASE),
        re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE),
    ]

    def __init__(self):
        self.secrets_collection = SecretsCollection()

    def redact_dict(self, data: dict) -> dict:
        """
        Recursively redact secrets from dictionary.

        Returns new dict with secrets replaced by '[REDACTED]'.
        """
        redacted = {}
        for key, value in data.items():
            if isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, str):
                redacted[key] = self._redact_string(value)
            else:
                redacted[key] = value
        return redacted

    def _redact_string(self, text: str) -> str:
        """Redact secrets from string using patterns."""
        # First, use detect-secrets
        with default_settings():
            self.secrets_collection.scan_line(text)
            if self.secrets_collection:
                # Has secrets - redact entire line for safety
                return '[REDACTED]'

        # Then apply custom patterns for env vars
        redacted = text
        for pattern in self.ENV_VAR_PATTERNS:
            redacted = pattern.sub(
                lambda m: f"{m.group(1)}=[REDACTED]" if '=' in m.group(0)
                else '[REDACTED]',
                redacted
            )

        return redacted

# Usage in ActionAuditor:
class ActionAuditor:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._redactor = SecretRedactor()

    async def log_event(self, event: AuditEvent) -> None:
        # Redact event_data before logging
        if event.event_data:
            event.event_data = self._redactor.redact_dict(event.event_data)

        # Write to database
        await self._write_event(event)
```

### Pattern 4: Kill Switch with Docker Container Termination
**What:** Force-terminate in-flight Docker operations using subprocess, not just asyncio.Task.cancel()
**When to use:** Kill switch activation when Docker containers must be stopped immediately

**Example:**
```python
# Source: Python asyncio docs + subprocess Docker patterns
import subprocess
import asyncio
from typing import List

class KillSwitch:
    """
    Enhanced kill switch with Docker container force-termination.
    """

    async def force_terminate_all(self) -> dict[str, int]:
        """
        Emergency termination of all operations.

        Returns dict with counts of:
        - pending_proposals: Cancelled from database
        - asyncio_tasks: Cancelled asyncio tasks
        - docker_containers: Force-killed Docker containers
        """
        results = {
            "pending_proposals": 0,
            "asyncio_tasks": 0,
            "docker_containers": 0,
        }

        # 1. Cancel pending proposals in database
        from operator_core.db.actions import ActionDB
        async with ActionDB(self.db_path) as db:
            results["pending_proposals"] = await db.cancel_all_pending()

        # 2. Cancel in-flight asyncio tasks
        results["asyncio_tasks"] = await self._cancel_asyncio_tasks()

        # 3. Force-kill Docker containers (cannot use asyncio for this)
        results["docker_containers"] = await self._force_kill_docker_containers()

        return results

    async def _cancel_asyncio_tasks(self) -> int:
        """Cancel all operator-created asyncio tasks."""
        tasks = [
            t for t in asyncio.all_tasks()
            if not t.done() and t.get_name().startswith('operator-')
        ]

        for task in tasks:
            task.cancel()

        # Give tasks chance to clean up
        await asyncio.gather(*tasks, return_exceptions=True)

        return len(tasks)

    async def _force_kill_docker_containers(self) -> int:
        """
        Force-kill all operator-managed Docker containers.

        CRITICAL: asyncio.Task.cancel() cannot interrupt blocking
        subprocess calls or force Docker to stop. We must use
        subprocess.run() with 'docker kill' command.
        """
        # Find operator-managed containers
        result = subprocess.run(
            [
                'docker', 'ps', '-q',
                '--filter', 'label=operator.managed=true',
                '--filter', 'status=running'
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return 0

        container_ids = result.stdout.strip().split('\n')
        container_ids = [cid for cid in container_ids if cid]

        if not container_ids:
            return 0

        # Force kill all containers (SIGKILL, exit code 137)
        kill_result = subprocess.run(
            ['docker', 'kill'] + container_ids,
            capture_output=True,
            text=True,
            timeout=30
        )

        if kill_result.returncode != 0:
            # Log error but don't raise - best effort termination
            print(f"Docker kill failed: {kill_result.stderr}")

        return len(container_ids)
```

### Pattern 5: Session-Level Risk Tracking
**What:** Accumulate risk scores across action chains to detect suspicious patterns
**When to use:** Before approving any action, to inform approval decision

**Example:**
```python
# Source: Risk-based alerting research + CTEM patterns
from datetime import datetime, timedelta
from typing import Dict, List
from enum import Enum

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SessionRiskTracker:
    """
    Track cumulative risk across action chains within a session.

    Implements behavioral analytics pattern from 2026 CTEM research:
    - Baseline risk score per action type
    - Frequency scoring (rapid succession = higher risk)
    - Pattern detection (privilege escalation chains)
    - Time-windowed accumulation
    """

    # Base risk scores for action types
    ACTION_RISK_SCORES = {
        "transfer_leader": 3,
        "add_peer": 5,
        "remove_peer": 7,
        "restart_container": 4,
        "stop_container": 6,
        "exec_command": 8,
    }

    # Risk thresholds
    RISK_THRESHOLDS = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 10,
        RiskLevel.HIGH: 20,
        RiskLevel.CRITICAL: 35,
    }

    def __init__(self, session_id: str, window_minutes: int = 10):
        self.session_id = session_id
        self.window = timedelta(minutes=window_minutes)
        self.action_history: List[dict] = []

    def add_action(
        self,
        action_name: str,
        parameters: dict,
        timestamp: datetime | None = None
    ) -> None:
        """Record action in session history."""
        if timestamp is None:
            timestamp = datetime.now()

        self.action_history.append({
            "action_name": action_name,
            "parameters": parameters,
            "timestamp": timestamp,
        })

    def calculate_risk_score(self) -> tuple[int, RiskLevel]:
        """
        Calculate cumulative risk score for current session.

        Returns (score, level) tuple.
        """
        now = datetime.now()
        cutoff = now - self.window

        # Filter to time window
        recent_actions = [
            a for a in self.action_history
            if a["timestamp"] >= cutoff
        ]

        if not recent_actions:
            return (0, RiskLevel.LOW)

        # Base score: sum of action risks
        base_score = sum(
            self.ACTION_RISK_SCORES.get(a["action_name"], 2)
            for a in recent_actions
        )

        # Frequency multiplier (more than 3 actions = suspicious)
        if len(recent_actions) > 3:
            frequency_multiplier = 1.5
        else:
            frequency_multiplier = 1.0

        # Pattern detection: escalation chain
        escalation_bonus = self._detect_escalation_chain(recent_actions)

        total_score = int(base_score * frequency_multiplier) + escalation_bonus

        # Determine risk level
        level = RiskLevel.LOW
        for threshold_level, threshold_score in sorted(
            self.RISK_THRESHOLDS.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            if total_score >= threshold_score:
                level = threshold_level
                break

        return (total_score, level)

    def _detect_escalation_chain(self, actions: List[dict]) -> int:
        """
        Detect privilege escalation patterns.

        Pattern: exec_command following container restart = +10 risk
        Pattern: multiple remove_peer actions = +5 risk per additional
        """
        bonus = 0
        action_names = [a["action_name"] for a in actions]

        # Check for exec after restart
        for i in range(len(action_names) - 1):
            if (action_names[i] in ("restart_container", "stop_container")
                and action_names[i+1] == "exec_command"):
                bonus += 10

        # Check for repeated destructive actions
        remove_count = action_names.count("remove_peer")
        if remove_count > 1:
            bonus += 5 * (remove_count - 1)

        return bonus

    def requires_elevated_approval(self) -> bool:
        """
        Determine if current risk requires additional approval.

        Returns True if risk level is HIGH or CRITICAL.
        """
        _, level = self.calculate_risk_score()
        return level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
```

### Anti-Patterns to Avoid
- **Manual datetime comparison without timezone awareness:** Use timezone-aware datetime.now(timezone.utc) to avoid "can't compare offset-naive and offset-aware" errors
- **Suppressing CancelledError without calling uncancel():** Breaks structured concurrency in TaskGroup and timeout() contexts
- **Logging parameters directly without redaction:** Secrets leak into logs and are hard to remediate
- **Assuming task.cancel() guarantees termination:** Tasks can suppress cancellation; use subprocess for Docker kill

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Secret detection in strings | Custom regex list | detect-secrets library | 28 plugins, entropy detection, keyword detection, extensively tested by Yelp and community |
| Token expiration validation | Manual timestamp math | PyJWT with exp validation | Handles timezone issues, leap seconds, clock drift with leeway parameter |
| Approval token generation | random.choice() or uuid4 | secrets.token_urlsafe(32) | CSPRNG designed for security tokens, not predictable UUIDs |
| Risk scoring formulas | Ad-hoc point system | Industry risk models (CVSS 4.0, FAIR) | Standardized, auditable, well-understood by security teams |
| State hashing | JSON serialize + hashlib | Pydantic model_dump_json() + hashlib.sha256 | Deterministic serialization order, handles datetime/enum correctly |

**Key insight:** Security primitives have subtle edge cases (timezone bugs, entropy issues, serialization order) that are easy to get wrong. Libraries have been battle-tested on these edge cases.

## Common Pitfalls

### Pitfall 1: TOCTOU Race Without Re-verification
**What goes wrong:** Approve action, system state changes, stale approval executes wrong action
**Why it happens:** Only checking state once at approval time, not at execution time
**How to avoid:** Always re-fetch proposal and verify state inside the execution lock (double-check pattern)
**Warning signs:** Audit logs showing "approved for X but executed against Y", user confusion about what was approved

### Pitfall 2: Approval Token Doesn't Actually Expire
**What goes wrong:** approved_at timestamp recorded but never checked, tokens valid indefinitely
**Why it happens:** No code path actually validates token age before execution
**How to avoid:** Always check (datetime.now() - proposal.approved_at).total_seconds() > 60 before execution
**Warning signs:** Old approvals being reused, no "approval expired" errors in logs

### Pitfall 3: Agent Identity Overwrites Requester Identity
**What goes wrong:** Audit logs show "agent" performed action, losing track of which user requested it
**Why it happens:** Only storing proposed_by field, which gets overwritten with "agent" when agent creates proposal
**How to avoid:** Add separate requester_id and agent_id fields, preserve both through action lifecycle
**Warning signs:** Compliance auditors asking "which human approved this?" and you can't answer

### Pitfall 4: Secrets Logged Before Redaction
**What goes wrong:** Parameters containing API keys written to logs, then redaction applied (too late)
**Why it happens:** Logging in multiple places, some before redaction filter
**How to avoid:** Centralize all logging through ActionAuditor.log_event(), apply redaction there
**Warning signs:** grep'ing logs finds "API_KEY=sk_live_..." strings, security scanner alerts

### Pitfall 5: Kill Switch Cancels Tasks But Not Subprocesses
**What goes wrong:** task.cancel() called, asyncio task stops, but Docker container keeps running
**Why it happens:** asyncio can't interrupt blocking subprocess.run() or signal Docker daemon
**How to avoid:** Track Docker containers separately, use subprocess.run(['docker', 'kill']) in kill switch
**Warning signs:** Kill switch activated but 'docker ps' shows containers still running

### Pitfall 6: Session Risk Score Resets on Each Action
**What goes wrong:** Each action evaluated independently, multi-step attack not detected
**Why it happens:** Not maintaining session state across actions, creating new tracker each time
**How to avoid:** Store SessionRiskTracker in executor, keyed by session_id, persist across actions
**Warning signs:** Attack pattern visible in audit log sequence but wasn't flagged during execution

### Pitfall 7: Optimistic Lock Version Not Actually Checked
**What goes wrong:** Version field exists in schema but UPDATE query doesn't use it in WHERE clause
**Why it happens:** Added version field but forgot to update query logic
**How to avoid:** Always include "WHERE version = ?" in updates and check rowcount > 0
**Warning signs:** Concurrent modifications succeeding when they should fail, data corruption

### Pitfall 8: Timezone-Naive vs Timezone-Aware Datetime Comparison
**What goes wrong:** TypeError: can't compare offset-naive and offset-aware datetimes at runtime
**Why it happens:** proposal.approved_at from database is naive, datetime.now() returns aware on some systems
**How to avoid:** Consistently use datetime.now(timezone.utc) everywhere, or strip timezone from both
**Warning signs:** Code works in dev but fails in production with different TZ settings

## Code Examples

Verified patterns from official sources:

### Token Expiration Check with Timezone Safety
```python
# Source: PyJWT documentation + timezone research
from datetime import datetime, timezone, timedelta

def is_approval_expired(
    approved_at: datetime,
    expiration_seconds: int = 60
) -> bool:
    """
    Check if approval token has expired.

    Handles both timezone-naive and timezone-aware datetimes safely.
    """
    # Ensure both datetimes are timezone-aware
    now = datetime.now(timezone.utc)

    if approved_at.tzinfo is None:
        # Assume UTC if naive
        approved_at = approved_at.replace(tzinfo=timezone.utc)

    age = (now - approved_at).total_seconds()
    return age > expiration_seconds
```

### Approval Token Generation
```python
# Source: Python secrets module documentation
import secrets

def generate_approval_token() -> str:
    """
    Generate cryptographically secure approval token.

    Uses CSPRNG (secrets module) not UUID4 which is predictable.
    Returns URL-safe base64 string (32 bytes = 256 bits entropy).
    """
    return secrets.token_urlsafe(32)
```

### Dual Identity Tracking
```python
# Source: Agentic AI security research + OAuth delegation patterns
class ActionProposal(BaseModel):
    # ... existing fields ...

    # Requester identity (human or system that initiated request)
    requester_id: str = Field(
        ...,
        description="Identity of requester (user email, system name)"
    )
    requester_type: str = Field(
        default="user",
        description="Type of requester: 'user', 'system', 'agent'"
    )

    # Agent identity (which agent executed on behalf of requester)
    agent_id: str | None = Field(
        default=None,
        description="Identity of agent executing action (if delegated)"
    )

    # Original proposed_by retained for backwards compatibility
    proposed_by: str = Field(
        default="agent",
        description="Who proposed: 'agent' or 'user'"
    )

# In audit logging:
class ActionAuditor:
    async def log_execution_started(
        self,
        proposal_id: int,
        requester_id: str,
        agent_id: str | None
    ) -> None:
        """
        Log execution with dual identity.

        SAFE-03, SAFE-04, SAFE-05: Track both requester and agent.
        """
        await self.log_event(AuditEvent(
            proposal_id=proposal_id,
            event_type="executing",
            event_data={
                "requester_id": requester_id,
                "requester_type": "user",  # from context
                "agent_id": agent_id,
            },
            actor="system",
            timestamp=datetime.now(timezone.utc),
        ))
```

### Complete TOCTOU-Resistant Workflow
```python
# Source: Combining asyncio.Lock + optimistic locking patterns
async def execute_with_toctou_defense(
    self,
    proposal_id: int,
    approval_token: str,
    requester_id: str,
    db: ActionDB,
) -> ActionRecord:
    """
    Execute proposal with comprehensive TOCTOU defense.

    Implements SAFE-01 (state re-verification), SAFE-02 (token expiry),
    SAFE-03 (requester tracking), SAFE-04 (dual authorization).
    """
    # Fast path check (no lock)
    proposal = await db.get_proposal(proposal_id)
    if not proposal.is_approved:
        raise ApprovalRequiredError(proposal_id, proposal.action_name)

    # Acquire execution lock
    async with self._execution_lock:
        # CRITICAL: Re-fetch after lock acquisition (TOCTOU defense)
        proposal = await db.get_proposal(proposal_id)

        # 1. Verify still approved (state could have changed)
        if not proposal.is_approved:
            await self._auditor.log_event(AuditEvent(
                proposal_id=proposal_id,
                event_type="toctou_blocked",
                event_data={"reason": "approval_revoked"},
                actor="system",
            ))
            raise StateChangedError("Approval was revoked")

        # 2. Verify token not expired (SAFE-02)
        if is_approval_expired(proposal.approved_at, expiration_seconds=60):
            await db.expire_approval(proposal_id)
            await self._auditor.log_event(AuditEvent(
                proposal_id=proposal_id,
                event_type="toctou_blocked",
                event_data={"reason": "token_expired"},
                actor="system",
            ))
            raise ApprovalExpiredError("Token expired (>60s)")

        # 3. Verify token matches (prevents replay)
        if proposal.approval_token != approval_token:
            await self._auditor.log_event(AuditEvent(
                proposal_id=proposal_id,
                event_type="toctou_blocked",
                event_data={"reason": "token_mismatch"},
                actor="system",
            ))
            raise InvalidTokenError("Token mismatch")

        # 4. Verify requester matches (SAFE-04)
        if proposal.requester_id != requester_id:
            await self._auditor.log_event(AuditEvent(
                proposal_id=proposal_id,
                event_type="toctou_blocked",
                event_data={"reason": "requester_mismatch"},
                actor="system",
            ))
            raise AuthorizationError("Requester ID mismatch")

        # 5. Update status with optimistic lock check
        success = await db.update_proposal_status(
            proposal_id,
            ActionStatus.EXECUTING,
            expected_version=proposal.version,
        )
        if not success:
            await self._auditor.log_event(AuditEvent(
                proposal_id=proposal_id,
                event_type="toctou_blocked",
                event_data={"reason": "concurrent_modification"},
                actor="system",
            ))
            raise ConcurrentModificationError("Version mismatch")

        # All checks passed - execute
        await self._auditor.log_execution_started(
            proposal_id,
            requester_id=proposal.requester_id,
            agent_id=proposal.agent_id,
        )

        return await self._execute_action(proposal)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single approval check at start | Double-check pattern with lock | 2024-2025 | Prevents TOCTOU races in async environments |
| Manual regex for secrets | detect-secrets + entropy | 2023-2025 | Catches 50%+ more secrets (custom formats) |
| Long-lived tokens | 60-90 second expiry | 2025-2026 | Reduces replay attack window |
| Single identity in logs | Dual identity (requester+agent) | 2025-2026 | Required for agentic AI security |
| Static risk thresholds | Dynamic cumulative scoring | 2025-2026 | Detects multi-step attack chains |
| task.cancel() for kill switch | subprocess + docker kill | Always needed | asyncio can't force-terminate blocking ops |
| Pessimistic locking (row locks) | Optimistic locking (version field) | Web era (2010s) | Better for async, fails late not early |

**Deprecated/outdated:**
- **Global locks for approval:** Single lock per proposal is sufficient, global lock causes contention
- **UUID4 for tokens:** Predictable (time-based component), use secrets.token_urlsafe() instead
- **Storing secrets for comparison:** Hash tokens server-side, compare hashes, don't store plaintext
- **Manual timestamp math:** Use PyJWT or similar libraries that handle edge cases

## Open Questions

Things that couldn't be fully resolved:

1. **What's the right session window for risk tracking?**
   - What we know: Industry uses 5-15 minute windows for behavioral analytics
   - What's unclear: Operator sessions may be longer (hours of active troubleshooting)
   - Recommendation: Start with 10 minutes, make it configurable via OPERATOR_RISK_WINDOW_MINUTES

2. **Should kill switch also kill TiKV processes?**
   - What we know: Docker containers can be force-killed with subprocess
   - What's unclear: TiKV processes may not be in Docker (playground vs cluster mode)
   - Recommendation: Phase 23 focuses on Docker kill, defer TiKV process kill to later phase if needed

3. **How to handle requester_id when agent proposes action autonomously?**
   - What we know: User-initiated actions have clear requester_id
   - What's unclear: If agent diagnoses issue and proposes action without user prompt, who is requester?
   - Recommendation: Use "agent:autonomous" as requester_id, add proposed_autonomously: bool flag

4. **Should risk thresholds block execution or just require elevated approval?**
   - What we know: HIGH/CRITICAL risk should trigger additional controls
   - What's unclear: Hard block vs elevated approval vs audit log warning
   - Recommendation: Start with elevated approval requirement, don't hard block (allows legitimate urgent actions)

5. **How to test TOCTOU race conditions reliably?**
   - What we know: Need to inject delay between check and execution
   - What's unclear: How to make tests deterministic without excessive mocking
   - Recommendation: Use asyncio.Event to coordinate race condition timing in tests

## Sources

### Primary (HIGH confidence)
- [Python Official Docs: asyncio-task.html](https://docs.python.org/3/library/asyncio-task.html) - Task cancellation, CancelledError handling
- [Python Official Docs: asyncio-sync.html](https://docs.python.org/3/library/asyncio-sync.html) - asyncio.Lock usage patterns
- [detect-secrets GitHub](https://github.com/Yelp/detect-secrets) - Library features, plugin list, programmatic usage
- [detect-secrets PyPI](https://pypi.org/project/detect-secrets/) - Installation, version info

### Secondary (MEDIUM confidence)
- [Avoiding Race Conditions in Python 2025 - Medium](https://medium.com/pythoneers/avoiding-race-conditions-in-python-in-2025-best-practices-for-async-and-threads-4e006579a622) - Asyncio race condition patterns
- [Asyncio Race Conditions - Super Fast Python](https://superfastpython.com/asyncio-race-conditions/) - Double-check pattern examples
- [Optimistic Locking Guide - Byte Byte Go](https://blog.bytebytego.com/p/optimistic-locking) - Version field patterns
- [Optimistic Locking: Concurrency Control - Medium](https://medium.com/@sumit-s/optimistic-locking-concurrency-control-with-a-version-column-2e3db2a8120d) - Database implementation
- [Secret Redaction with Grafana Alloy - Grafana Labs](https://grafana.com/blog/2025/03/20/how-to-redact-secrets-from-logs-with-grafana-alloy-and-loki/) - Redaction patterns
- [Building Reliable Secrets Detection - GitGuardian](https://blog.gitguardian.com/secrets-in-source-code-episode-3-3-building-reliable-secrets-detection/) - Detection methods
- [Secrets Patterns DB - Mazin Ahmed](https://mazinahmed.net/blog/secrets-patterns-db/) - Regex pattern database
- [Python subprocess Docker kill script - GitHub Gist](https://gist.github.com/urjitbhatia/dd346a209a36bf0bff88925378146deb) - Docker termination
- [Docker container kill docs](https://docs.docker.com/reference/cli/docker/container/kill/) - SIGKILL behavior
- [PyJWT Usage Examples](https://pyjwt.readthedocs.io/en/latest/usage.html) - Token expiration validation
- [Dynamic Risk Scoring - Deepwatch](https://www.deepwatch.com/glossary/dynamic-risk-scoring-drs/) - Risk scoring patterns
- [Risk-Based Alerting - Deepwatch](https://www.deepwatch.com/glossary/risk-based-alerting-rba/) - Cumulative risk detection
- [AI Agents Authorization Bypass - Hacker News](https://thehackernews.com/2026/01/ai-agents-are-becoming-privilege.html) - Dual identity challenges
- [New Identity Playbook for AI Agents - Strata](https://www.strata.io/blog/agentic-identity/new-identity-playbook-ai-agents-not-nhi-8b/) - Agent identity patterns
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) - Session security best practices

### Tertiary (LOW confidence)
- WebSearch results on approval workflow patterns - General industry trends, not Python-specific
- WebSearch results on TOCTOU vulnerabilities - Security concepts, not implementation details
- WebSearch results on cumulative risk scoring - Enterprise security products, not open-source patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - asyncio/detect-secrets are well-documented and battle-tested
- Architecture: MEDIUM-HIGH - Patterns combine multiple verified sources but need testing in brownfield codebase
- Pitfalls: HIGH - Based on official docs warnings and reported issues from 2025-2026

**Research date:** 2026-01-27
**Valid until:** 2026-03-27 (60 days - security practices evolve quickly, libraries stable)
