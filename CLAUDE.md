# Operator - Claude Context

An autonomous infrastructure operator that monitors distributed systems, detects issues via invariant checking, and uses AI agents to diagnose and resolve problems.

## Architecture: Protocol-Driven Separation

The system is designed for **strict separation of concerns**. You can:
- Add subjects without changing the operator
- Understand the operator without knowing subject details
- Run eval independently of the operator

### Dependency Direction (Critical)

```
operator-protocols  (ZERO dependencies - foundation)
       ↑
       │ imported by
       ├── operator-core (orchestration)
       ├── tikv-observer (subject implementation)
       ├── ratelimiter-observer (subject implementation)
       └── [new subjects import only this]

Subjects NEVER import operator-core.
operator-core imports subjects ONLY via lazy factory.
eval imports NOTHING from operator packages.
```

### Core Protocols

**SubjectProtocol** (`operator_protocols/subject.py`) - Read-only observation:
```python
class SubjectProtocol(Protocol):
    async def observe(self) -> dict[str, Any]: ...
```

**InvariantCheckerProtocol** (`operator_protocols/invariant.py`) - Health checking:
```python
class InvariantCheckerProtocol(Protocol):
    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]: ...
```

The MonitorLoop uses these protocols without knowing concrete types. It treats all subjects identically.

## Package Structure

```
packages/
├── operator-protocols/     # Interface definitions (ZERO deps)
│   └── SubjectProtocol, InvariantCheckerProtocol, generic types
├── operator-core/          # Runtime orchestration
│   ├── monitor/            # MonitorLoop daemon
│   ├── agent_lab/          # Autonomous agent with shell access
│   ├── db/                 # SQLite for tickets/audit
│   └── cli/                # Typer commands + subject_factory.py

subjects/
├── tikv/
│   ├── observer/           # TiKVSubject, TiKVInvariantChecker
│   ├── service/            # Docker compose for TiKV cluster
│   └── docker-compose.yaml
├── ratelimiter/
│   └── observer/           # RateLimiterSubject, checker

eval/                       # Chaos engineering framework (independent)
├── src/eval/
│   ├── runner/             # Campaign/trial execution
│   ├── analysis/           # Scoring, comparison
│   ├── subjects/tikv/      # TiKVEvalSubject (chaos injection)
│   └── viewer/             # Web UI
└── CLAUDE.md               # Eval-specific documentation

demo/                       # Interactive TUI demonstrations
```

## Adding a New Subject

**You only touch ONE file in operator-core:** `cli/subject_factory.py`

### Step 1: Create subject package
```
subjects/myservice/observer/
├── src/myservice_observer/
│   ├── subject.py      # Implements SubjectProtocol
│   ├── invariants.py   # Implements InvariantCheckerProtocol
│   └── factory.py      # Exports create_myservice_subject_and_checker()
└── pyproject.toml      # Depends on operator-protocols ONLY
```

### Step 2: Implement protocols
```python
# subject.py
from operator_protocols import SubjectProtocol

class MyServiceSubject:
    async def observe(self) -> dict[str, Any]:
        return {"services": [...], "metrics": {...}}

# invariants.py
from operator_protocols import InvariantCheckerProtocol, InvariantViolation

class MyServiceInvariantChecker:
    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        violations = []
        # Your health checks here
        return violations

# factory.py
def create_myservice_subject_and_checker(**kwargs):
    return MyServiceSubject(...), MyServiceInvariantChecker()
```

### Step 3: Register in factory (one line)
```python
# packages/operator-core/src/operator_core/cli/subject_factory.py
AVAILABLE_SUBJECTS = ["tikv", "ratelimiter", "myservice"]  # Add here

# Add elif branch in create_subject()
elif subject_name == "myservice":
    from myservice_observer.factory import create_myservice_subject_and_checker
    return create_myservice_subject_and_checker(**kwargs)
```

**Done.** Works automatically with monitor, agent, CLI, viewer.

## Key Files by Task

| Task | File |
|------|------|
| Understand monitoring flow | `operator-core/monitor/loop.py` |
| Add new subject | `subjects/newname/observer/` + `cli/subject_factory.py` |
| Modify agent behavior | `operator-core/agent_lab/` |
| Add invariant check | `subjects/*/observer/invariants.py` |
| Change ticket handling | `operator-core/db/tickets.py` |
| Add CLI command | `operator-core/cli/*.py` |

## Eval System (Separate)

Eval has its own `EvalSubject` protocol for **chaos injection** (not monitoring):
```python
class EvalSubject(Protocol):
    async def reset(self) -> None
    async def inject_chaos(self, chaos_type: str, **params) -> dict
    async def cleanup_chaos(self, metadata: dict) -> None
    async def wait_healthy(self, timeout_sec: float) -> bool
    async def capture_state(self) -> dict
```

This is intentionally separate from SubjectProtocol. Monitoring is read-only; eval manipulates state.

See `eval/CLAUDE.md` for eval-specific documentation.

## CLI Commands

```bash
# Monitor a subject
uv run operator monitor run --subject tikv --pd http://localhost:2379

# Start autonomous agent
uv run operator agent start --db operator.db

# View tickets
uv run operator tickets list

# Run eval campaign
cd eval && uv run eval run campaign campaigns/smoke-tests/tikv-smoke.yaml
```

## Development Workflow

### Test as You Go

When making changes, add or update tests alongside the code - not as a separate step later. If a change needs a test, write it as part of the same work.

- **New function or class?** Add a test file or test cases immediately
- **Bug fix?** Add a regression test that would have caught it
- **Changing behavior?** Update existing tests to match

Run tests for the package you're modifying:
```bash
# operator-core tests
uv run pytest packages/operator-core/tests/

# tikv-observer tests
uv run pytest subjects/tikv/observer/tests/

# eval tests
cd eval && uv run pytest tests/
```

### Incremental Verification

After each logical change you make, run a quick smoke test or verification before moving to the next change. Don't batch multiple untested changes together. If a test fails, fix it before proceeding.

### Commit Hygiene

- Commit working code with passing tests
- Tests and implementation go in the same commit when they're for the same change

## Documentation

User-facing instructions live in READMEs, not CLAUDE.md files. Keep them in sync:

| What | Where |
|------|-------|
| Demo instructions | `README.md` (root) |
| Eval campaign instructions | `eval/README.md` |

When changing user-facing behavior (CLI commands, campaign configs, prerequisites, new subjects), update the corresponding README. The campaign tables in `eval/README.md` list every YAML file in `eval/campaigns/` — add new campaigns there too.

## Design Principles

1. **operator-protocols has ZERO dependencies** - Can be imported anywhere
2. **Subjects depend on operator-protocols only** - Never import operator-core
3. **Factory pattern isolates subject loading** - Lazy imports prevent coupling
4. **MonitorLoop is subject-agnostic** - Uses protocols, not concrete types
5. **Observation dict schema is per-subject** - Protocol defines method, not schema
6. **Eval is deliberately separate** - Different protocols, can evolve independently

## Understanding Without Subject Details

To understand operator-core, you only need to know:
- `subject.observe()` returns a dict describing current system state
- `checker.check(observation)` returns a list of invariant violations
- MonitorLoop calls these every N seconds
- Violations become tickets; cleared violations auto-resolve tickets
- Agent reads tickets and observations to reason about problems

You don't need to know anything about TiKV, PD APIs, Prometheus, or rate limiters.

## Tech Stack

This project is primarily Python. The main stack is: Python, Docker Compose, GCP (Cloud SQL PostgreSQL, Cloud Run), FastAPI. Shell scripts are used for automation but core logic is Python.

## Infrastructure / Environment

Always check Docker first for running services (not tiup, not other tools). The project runs TiKV and other infrastructure in Docker Compose.

## Code Style / Architecture Principles

Prefer simplicity over abstraction. Don't over-engineer with fancy typing, predefined option sets, or complex patterns. Keep things subject-agnostic with strict layer separation. When I say simplify, I mean radically simplify.

## Debugging / Troubleshooting

Before making assumptions about errors or limitations (e.g., billing quotas, resource limits), verify with actual evidence. Don't invent explanations — say 'I'm not sure' if you don't know.

## Testing / Demos

When running demos or smoke tests, always verify the correct container names/filters before executing kill/restart commands. Container name patterns can match unintended services (e.g., PD nodes matching TiKV filters).
