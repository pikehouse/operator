"""Script execution tools for agent workflows.

Provides execute_script tool for running validated Python and Bash scripts
in sandboxed Docker containers with multi-layer validation:
- Syntax checking (Python: ast.parse, Bash: bash -n)
- Secret scanning (API keys, passwords, tokens)
- Dangerous pattern detection (rm -rf, eval, etc.)

Scripts execute in isolated containers with:
- Network isolation (--network none)
- Resource limits (512MB memory, 1 CPU)
- Non-root execution (user=nobody)
- Read-only filesystem
- Timeout enforcement (max 300s)
"""

from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType


def get_script_tools() -> list[ActionDefinition]:
    """
    Get script execution tool definitions.

    Returns list of ActionDefinition for script execution operations.
    Per SCRP-01: execute_script is discoverable via get_general_tools().
    """
    return [
        ActionDefinition(
            name="execute_script",
            description=(
                "Execute Python or Bash script in sandboxed Docker container. "
                "Scripts undergo multi-layer validation:\n"
                "1. Syntax checking (Python: ast.parse, Bash: bash -n)\n"
                "2. Secret scanning (detects hardcoded API keys, passwords)\n"
                "3. Dangerous pattern detection (rm -rf, eval, curl | sh, etc.)\n"
                "4. Size limit enforcement (10000 characters)\n"
                "\n"
                "Execution happens in isolated container with:\n"
                "- Network isolation (--network none)\n"
                "- Resource limits (512MB memory, 1 CPU, 100 PIDs)\n"
                "- Non-root execution (user=nobody)\n"
                "- Read-only filesystem\n"
                "- Timeout enforcement (max 300s)\n"
                "\n"
                "Use this tool to:\n"
                "- Analyze logs or data with custom scripts\n"
                "- Generate configuration files\n"
                "- Transform data formats\n"
                "- Calculate metrics or statistics\n"
                "\n"
                "Do NOT use for:\n"
                "- Network operations (container has no network access)\n"
                "- File system modifications (container is read-only)\n"
                "- Long-running processes (5 minute timeout)"
            ),
            parameters={
                "script_content": ParamDef(
                    type="str",
                    description=(
                        "Script content to execute. "
                        "Must pass validation checks (syntax, secrets, dangerous patterns). "
                        "Maximum 10000 characters."
                    ),
                    required=True,
                ),
                "script_type": ParamDef(
                    type="str",
                    description="Script language: 'python' or 'bash'",
                    required=True,
                ),
                "timeout": ParamDef(
                    type="int",
                    description=(
                        "Execution timeout in seconds (default: 60, max: 300). "
                        "Script will be killed if it exceeds this duration."
                    ),
                    required=False,
                    default=60,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
            requires_approval=True,
        ),
    ]
