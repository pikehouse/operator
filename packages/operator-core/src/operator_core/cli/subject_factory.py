"""
Factory for creating subject and checker instances.

Uses lazy imports to avoid loading unused subject packages.
Subjects are discovered via hardcoded switch per CONTEXT.md decision.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from operator_protocols import InvariantCheckerProtocol, SubjectProtocol

# Hardcoded list of available subjects
AVAILABLE_SUBJECTS = ["tikv", "ratelimiter"]


async def create_subject(
    subject_name: str,
    **kwargs: Any,
) -> tuple["SubjectProtocol", "InvariantCheckerProtocol"]:
    """
    Factory function to create subject and checker instances.

    Args:
        subject_name: Subject identifier (e.g., "tikv", "ratelimiter")
        **kwargs: Subject-specific configuration (endpoints, etc.)

    Returns:
        Tuple of (subject, checker) instances

    Raises:
        ValueError: If subject_name is not recognized

    Example:
        # TiKV subject
        subject, checker = await create_subject(
            "tikv",
            pd_endpoint="http://pd:2379",
            prometheus_url="http://prometheus:9090",
        )

        # Rate limiter subject
        subject, checker = await create_subject(
            "ratelimiter",
            ratelimiter_url="http://ratelimiter:8000",
            redis_url="redis://localhost:6379",
            prometheus_url="http://prometheus:9090",
        )
    """
    if subject_name == "tikv":
        # Lazy import to avoid loading tikv package unless needed
        from tikv_observer.factory import create_tikv_subject_and_checker

        return create_tikv_subject_and_checker(**kwargs)
    elif subject_name == "ratelimiter":
        # Lazy import to avoid loading ratelimiter package unless needed
        from ratelimiter_observer.factory import create_ratelimiter_subject_and_checker

        return create_ratelimiter_subject_and_checker(**kwargs)
    else:
        raise ValueError(
            f"Unknown subject '{subject_name}'. "
            f"Available subjects: {', '.join(AVAILABLE_SUBJECTS)}"
        )


def get_available_subjects() -> list[str]:
    """Return list of available subject names."""
    return AVAILABLE_SUBJECTS.copy()
