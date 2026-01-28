---
phase: 26-script-execution
plan: 03
subsystem: action-framework
tags: [agent-tools, script-execution, tool-registration, discovery]
requires: [26-02-script-executor]
provides: [execute_script-tool, agent-script-discovery]
affects: [27-risk-classification, 28-agent-integration]
tech-stack:
  added: []
  patterns: [lazy-initialization, lambda-wrappers]
key-files:
  created:
    - packages/operator-core/src/operator_core/scripts/tools.py
    - packages/operator-core/tests/test_script_tools.py
  modified:
    - packages/operator-core/src/operator_core/scripts/__init__.py
    - packages/operator-core/src/operator_core/actions/tools.py
    - packages/operator-core/tests/test_host_actions.py
decisions:
  - id: lazy-script-executor
    choice: Lazy initialization of ScriptExecutor in _get_script_executor()
    rationale: Prevents circular import between tools.py and scripts module, follows Docker/Host pattern
  - id: execute-script-high-risk
    choice: Risk level "high" with requires_approval=True
    rationale: Script execution is arbitrary code execution despite sandbox, requires approval
  - id: comprehensive-description
    choice: Tool description explains validation layers and sandbox constraints
    rationale: Agent needs to understand what validation happens and execution limits
metrics:
  duration: 3m20s
  files-modified: 5
  tests-added: 9
  tests-passing: 104
completed: 2026-01-28
---

# Phase 26 Plan 03: Script Tool Registration Summary

**One-liner:** execute_script tool registered as high-risk agent-discoverable tool with validation/sandbox documentation, lazy executor initialization, and comprehensive integration tests

## What Was Built

Registered `execute_script` as an agent-discoverable tool integrated into the action framework:

1. **Created `scripts/tools.py`** with `get_script_tools()` returning ActionDefinition
   - Tool name: `execute_script`
   - Parameters: `script_content` (required), `script_type` (required), `timeout` (optional, default 60)
   - Risk level: `high`, requires approval: `True`
   - Description explains 5-layer validation (syntax, secrets, patterns, size) and sandbox isolation
   - Description explains resource limits (network=none, 512MB, 1 CPU, read-only FS, 300s max)

2. **Integrated into action framework** via `actions/tools.py`
   - Imported `get_script_tools` in `get_general_tools()`
   - Added `_script_executor` lazy initialization following Docker/Host pattern
   - Added `execute_script` to `TOOL_EXECUTORS` mapping to `_get_script_executor().execute()`
   - Lambda wrapper passes parameters through to `ScriptExecutor.execute()`

3. **Created comprehensive integration tests** in `test_script_tools.py`
   - Tests verify tool discoverable via `get_general_tools()`
   - Tests verify parameters, risk level, approval requirement
   - Tests verify `execute_tool()` routes to `ScriptExecutor.execute()`
   - Mock testing for executor integration
   - Tests verify description mentions sandbox and validation

## Requirements Satisfied

- **SCRP-01**: execute_script tool available via get_general_tools() ✓
  - Agent can discover execute_script with parameters documented
  - execute_tool('execute_script', ...) executes script via ScriptExecutor
  - execute_script requires approval (risk_level: high)

## Technical Decisions

### Lazy Initialization Pattern

Followed Docker/Host pattern for ScriptExecutor initialization:

```python
_script_executor = None

def _get_script_executor():
    from operator_core.scripts import ScriptExecutor
    global _script_executor
    if _script_executor is None:
        _script_executor = ScriptExecutor()
    return _script_executor

TOOL_EXECUTORS = {
    "execute_script": lambda **kw: _get_script_executor().execute(**kw),
}
```

**Benefits:**
- Avoids circular import issues (tools.py imports scripts, scripts might import tools types)
- Single shared executor instance for all execute_script calls
- Consistent pattern with Docker and Host tools
- Lambda wrapper provides clean parameter pass-through

### High Risk Classification

Classified execute_script as `risk_level="high"` with `requires_approval=True`:

**Rationale:**
- Script execution is arbitrary code execution despite sandbox
- Risk level "high" matches Docker exec and Host kill_process
- Requires explicit approval before execution
- Agent can discover and propose, but not auto-execute

**Consistent with existing patterns:**
- Docker exec: high risk (arbitrary command execution)
- Host kill_process: high risk (process termination)
- Docker stop/restart: high risk (availability impact)

### Comprehensive Tool Description

Tool description explains both validation and execution constraints:

**Validation layers documented:**
1. Syntax checking (Python: ast.parse, Bash: bash -n)
2. Secret scanning (API keys, passwords, tokens)
3. Dangerous pattern detection (rm -rf, eval, etc.)
4. Size limit enforcement (10000 characters)

**Sandbox constraints documented:**
- Network isolation (--network none)
- Resource limits (512MB memory, 1 CPU, 100 PIDs)
- Non-root execution (user=nobody)
- Read-only filesystem
- Timeout enforcement (max 300s)

**Agent guidance included:**
- Use cases (analyze logs, generate configs, transform data)
- Anti-patterns (network ops, file modifications, long-running)

**Rationale:**
- Agent needs to understand what scripts will pass validation
- Agent needs to understand execution environment constraints
- Clear guidance prevents proposing invalid scripts
- Description serves as inline documentation for agent reasoning

## Files Modified

### Created Files

**packages/operator-core/src/operator_core/scripts/tools.py**
- `get_script_tools()` returning ActionDefinition for execute_script
- Comprehensive description with validation layers and sandbox details
- Parameters with detailed descriptions and defaults
- Risk level and approval configuration

**packages/operator-core/tests/test_script_tools.py**
- 9 integration tests for execute_script tool registration
- Tests for discoverability, parameters, risk level
- Tests for executor routing with mocked ScriptExecutor
- Tests for validation error handling

### Modified Files

**packages/operator-core/src/operator_core/scripts/__init__.py**
- Added `get_script_tools` import
- Added to `__all__` exports
- Updated module docstring

**packages/operator-core/src/operator_core/actions/tools.py**
- Added `get_script_tools` import to `get_general_tools()`
- Added `_script_executor` lazy initialization
- Added `execute_script` to `TOOL_EXECUTORS` mapping
- Updated docstring to mention Script actions

**packages/operator-core/tests/test_host_actions.py**
- Updated total tool count test: 14 → 15 tools
- Updated comment: "2 base + 8 Docker + 4 Host + 1 Script = 15"

## Testing Results

All tests pass (104 total):

```bash
pytest packages/operator-core/tests/test_docker_actions.py \
      packages/operator-core/tests/test_host_actions.py \
      packages/operator-core/tests/test_script_tools.py -q

104 passed in 0.33s
```

### New Tests Added (9)

1. **test_execute_script_discoverable**: Verifies tool in get_general_tools()
2. **test_execute_script_parameters**: Verifies required/optional parameters
3. **test_execute_script_risk_and_approval**: Verifies high risk + approval required
4. **test_execute_script_action_type**: Verifies ActionType.TOOL
5. **test_execute_script_description**: Verifies description mentions sandbox/validation
6. **test_execute_script_in_tool_executors**: Verifies mapping in TOOL_EXECUTORS
7. **test_execute_tool_calls_script_executor**: Verifies routing to ScriptExecutor.execute()
8. **test_execute_tool_uses_default_timeout**: Verifies parameter pass-through
9. **test_execute_tool_validation_error**: Verifies validation error handling

### Existing Tests Verified

- Docker action tests: All 37 passing (verified Docker tools still work)
- Host action tests: All 58 passing (verified Host tools still work)
- Integration verified: Docker, Host, and Script tools coexist correctly

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

### Upstream Dependencies

- **26-02-script-executor**: ScriptExecutor with validation and sandbox execution
  - Used via lazy initialization in `_get_script_executor()`
  - Lambda wrapper passes parameters to `ScriptExecutor.execute()`

### Downstream Impact

- **27-risk-classification**: execute_script classified as HIGH risk
  - Will be subject to risk tracking and session scoring
  - Requires approval before execution

- **28-agent-integration**: Agent can discover and propose execute_script
  - Tool appears in agent's available actions
  - Description guides agent on valid use cases
  - Agent cannot auto-execute (requires approval)

### Framework Integration

- **actions/tools.py**: Central registry for all agent-discoverable tools
  - execute_script joins wait, log_message, 8 Docker tools, 4 Host tools
  - Total: 15 tools available to agents
  - Consistent discovery pattern via `get_general_tools()`

- **TOOL_EXECUTORS mapping**: Routing execute_tool() calls to implementations
  - Lambda wrapper provides consistent interface
  - Lazy initialization prevents import cycles
  - Same pattern as Docker and Host tools

## Next Phase Readiness

**Phase 27 (Risk Classification):**
- execute_script registered with `risk_level="high"`
- Ready for risk scoring and session tracking
- Approval requirement already enforced

**Phase 28 (Agent Integration):**
- Tool fully discoverable via `get_general_tools()`
- Parameters documented with descriptions
- Description guides agent on valid use cases
- Agent can propose but not auto-execute

**Phase 29 (Demo Scenarios):**
- execute_script ready for demo workflows
- Can demonstrate script validation catching secrets/dangerous patterns
- Can demonstrate sandbox isolation (network=none, read-only FS)
- Can demonstrate timeout enforcement

## Performance Notes

- **Lazy initialization**: ScriptExecutor created on first use, not at import
- **Single instance**: Shared executor across all execute_script calls
- **No blocking operations**: Lambda wrapper is synchronous, but execute() is async
- **Test suite**: 104 tests complete in 0.33s (3ms per test average)

## Lessons Learned

### Pattern Consistency Wins

Following Docker/Host patterns for lazy initialization and lambda wrappers:
- Prevented circular import issues without debugging
- Tests followed same mock patterns as Docker/Host tests
- Integration "just worked" because pattern was proven

### Comprehensive Descriptions Matter

Tool description serves multiple purposes:
- Agent reasoning (what scripts will pass validation)
- Inline documentation (no separate docs needed)
- Use case guidance (prevents invalid script proposals)
- Constraint clarity (network isolation, read-only FS)

Time spent on description pays off in agent quality and debugging reduction.

### Test-Driven Integration

Writing integration tests first revealed:
- Forgot to update total tool count in existing test
- Mock patterns needed unittest.mock (not pytest-mock)
- Parameter pass-through worked correctly with lambda wrappers

Integration tests catch cross-component issues early.

---

**Status:** ✅ Complete - All requirements satisfied, all tests passing, ready for Phase 27 (Risk Classification)
