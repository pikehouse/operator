"""Host-level action executor for systemd service management.

Provides HostActionExecutor for controlling systemd services (start/stop/restart)
with security validation via ServiceWhitelist.
"""

from operator_core.host.validation import ServiceWhitelist

# HostActionExecutor will be imported after actions.py is created in Task 2
# This avoids import errors during Task 1 execution

__all__ = ["ServiceWhitelist"]
