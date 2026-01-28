"""Service validation for host actions.

Provides service name whitelist to prevent unauthorized operations on critical system services.
Per HOST-06: Service name whitelist prevents operations on unauthorized services.
"""

from typing import Set


class ServiceWhitelist:
    """Service authorization whitelist.

    Only whitelisted services can be controlled via host actions.
    Forbidden services (systemd, ssh, dbus, etc.) are blocked even if manually whitelisted.
    """

    # Default whitelist for demo/development
    DEFAULT_WHITELIST: Set[str] = {
        # TiKV/PD services (if running as systemd units)
        "tikv",
        "pd",
        # Common infrastructure services
        "nginx",
        "redis-server",
        "postgresql",
        "mysql",
        "docker",
        # Rate limiter service (custom)
        "ratelimiter",
    }

    # Critical services that should NEVER be controlled
    # These take precedence over whitelist - even if manually added, is_allowed() returns False
    FORBIDDEN_SERVICES: Set[str] = {
        "systemd",
        "dbus",
        "ssh",
        "sshd",
        "networking",
        "network-manager",
        "systemd-resolved",
        "systemd-networkd",
        "init",
    }

    def __init__(self, whitelist: Set[str] | None = None):
        """Initialize whitelist.

        Args:
            whitelist: Custom whitelist, or None for default
        """
        self.whitelist = whitelist if whitelist is not None else self.DEFAULT_WHITELIST.copy()

    def is_allowed(self, service_name: str) -> bool:
        """Check if service is allowed.

        Args:
            service_name: Service name to check

        Returns:
            True if service in whitelist and not forbidden, False otherwise

        Note:
            Forbidden services take precedence - even if service is in whitelist,
            is_allowed() returns False if service is in FORBIDDEN_SERVICES.
        """
        # Explicit deny takes precedence
        if service_name in self.FORBIDDEN_SERVICES:
            return False

        # Must be explicitly whitelisted
        return service_name in self.whitelist

    def add_service(self, service_name: str) -> None:
        """Add service to whitelist (runtime configuration).

        Args:
            service_name: Service name to add

        Raises:
            ValueError: If attempting to add a forbidden service
        """
        if service_name in self.FORBIDDEN_SERVICES:
            raise ValueError(f"Cannot whitelist forbidden service: {service_name}")
        self.whitelist.add(service_name)

    def validate_service_name(self, service_name: str) -> None:
        """Validate service name for security.

        Checks for path traversal attempts and other security issues.

        Args:
            service_name: Service name to validate

        Raises:
            ValueError: If service name contains path separators or other invalid characters
        """
        # Check for path separators (prevent path traversal)
        if "/" in service_name:
            raise ValueError(f"Invalid service name: contains path separator '/'")
        if ".." in service_name:
            raise ValueError(f"Invalid service name: contains path traversal '..'")
