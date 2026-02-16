"""Subject factory with registration pattern for local and cloud subjects."""

from typing import Any, Callable

from eval.types import EvalSubject


class SubjectRegistry:
    """Registry for subject constructors by type and mode.

    Enables decoupled subject creation for local vs cloud execution.
    Subjects register themselves via decorator, and the registry handles
    instantiation with proper mode fallback.

    Example:
        @SubjectRegistry.register("tikv", "local")
        def _create_local_tikv(instance_id: int, **kwargs) -> EvalSubject:
            from eval.subjects.tikv import TiKVEvalSubject
            return TiKVEvalSubject(instance_id=instance_id)

        # Create a local TiKV subject
        subject = SubjectRegistry.create("tikv", instance_id=0, mode="local")

        # Create a cloud TiKV subject (falls back to local if cloud not registered)
        subject = SubjectRegistry.create("tikv", instance_id=0, mode="cloud-gcp")
    """

    _registry: dict[tuple[str, str], Callable[..., EvalSubject]] = {}

    @classmethod
    def register(cls, subject_type: str, mode: str = "local"):
        """Decorator to register a subject constructor.

        Args:
            subject_type: Subject type identifier (e.g., "tikv")
            mode: Execution mode (e.g., "local", "cloud-gcp")

        Returns:
            Decorator function
        """
        def decorator(fn: Callable[..., EvalSubject]) -> Callable[..., EvalSubject]:
            cls._registry[(subject_type, mode)] = fn
            return fn
        return decorator

    @classmethod
    def create(
        cls,
        subject_type: str,
        instance_id: int = 0,
        mode: str = "local",
        **kwargs: Any,
    ) -> EvalSubject:
        """Create a subject instance by type and mode.

        Falls back to local mode if requested mode is not registered.

        Args:
            subject_type: Subject type identifier (e.g., "tikv")
            instance_id: Instance number for parallel execution
            mode: Execution mode (e.g., "local", "cloud-gcp")
            **kwargs: Additional constructor arguments

        Returns:
            EvalSubject instance

        Raises:
            ValueError: If subject_type not registered for any mode
        """
        key = (subject_type, mode)

        # Try exact match first
        if key in cls._registry:
            return cls._registry[key](instance_id=instance_id, **kwargs)

        # Fall back to local mode
        local_key = (subject_type, "local")
        if local_key in cls._registry:
            return cls._registry[local_key](instance_id=instance_id, **kwargs)

        # No registration found
        available = [k for k in cls._registry.keys() if k[0] == subject_type]
        if available:
            modes = [k[1] for k in available]
            raise ValueError(
                f"Subject '{subject_type}' not registered for mode '{mode}'. "
                f"Available modes: {modes}"
            )
        else:
            all_types = sorted(set(k[0] for k in cls._registry.keys()))
            raise ValueError(
                f"Unknown subject type: '{subject_type}'. "
                f"Available types: {all_types}"
            )

    @classmethod
    def list_subjects(cls) -> list[str]:
        """List all registered subject types.

        Returns:
            Sorted list of subject type identifiers
        """
        return sorted(set(k[0] for k in cls._registry.keys()))

    @classmethod
    def list_modes(cls, subject_type: str) -> list[str]:
        """List available modes for a subject type.

        Args:
            subject_type: Subject type identifier

        Returns:
            List of mode identifiers for this subject
        """
        return [k[1] for k in cls._registry.keys() if k[0] == subject_type]

    @classmethod
    def is_registered(cls, subject_type: str, mode: str = "local") -> bool:
        """Check if a subject is registered for a mode.

        Args:
            subject_type: Subject type identifier
            mode: Execution mode

        Returns:
            True if registered, False otherwise
        """
        return (subject_type, mode) in cls._registry


# Register built-in subjects
@SubjectRegistry.register("tikv", "local")
def _create_local_tikv(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a local TiKV eval subject.

    Args:
        instance_id: Instance number for parallel execution (0, 1, 2, ...)
        **kwargs: Additional arguments (compose_file, etc.)

    Returns:
        TiKVEvalSubject instance
    """
    from eval.subjects.tikv import TiKVEvalSubject
    return TiKVEvalSubject(instance_id=instance_id, **kwargs)


@SubjectRegistry.register("chat-db-app-shard", "local")
def _create_local_chat_db_app_shard(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a local chat-db-app-shard eval subject.

    Args:
        instance_id: Instance number for parallel execution (0, 1, 2, ...)
        **kwargs: Additional arguments (workspace_base, etc.)

    Returns:
        ChatDBAppShardEvalSubject instance
    """
    from eval.subjects.chat_db_app_shard import ChatDBAppShardEvalSubject
    return ChatDBAppShardEvalSubject(instance_id=instance_id, **kwargs)


@SubjectRegistry.register("chat-db-app", "local")
def _create_local_chat_db_app(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a local chat-db-app eval subject.

    Args:
        instance_id: Instance number for parallel execution (0, 1, 2, ...)
        **kwargs: Additional arguments (workspace_base, etc.)

    Returns:
        ChatDBAppEvalSubject instance
    """
    from eval.subjects.chat_db_app import ChatDBAppEvalSubject
    return ChatDBAppEvalSubject(instance_id=instance_id, **kwargs)


# Register cloud subjects (lazy import to avoid dependency on asyncpg/google-cloud)
@SubjectRegistry.register("tikv", "cloud-gcp")
def _create_gcp_tikv(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a GCP TiKV eval subject.

    Args:
        instance_id: Instance number for parallel execution
        **kwargs: Additional arguments (project, zone, machine_type)

    Returns:
        GCPTiKVSubject instance

    Raises:
        ImportError: If cloud dependencies not installed
    """
    try:
        from eval.subjects.cloud.gcp.subject import GCPTiKVSubject
        return GCPTiKVSubject(
            instance_id=instance_id,
            project=kwargs.get("project"),
            zone=kwargs.get("zone", "us-central1-a"),
            machine_type=kwargs.get("machine_type", "e2-standard-4"),
        )
    except ImportError as e:
        raise ImportError(
            "Cloud dependencies not installed. Install with: pip install 'eval[cloud]'"
        ) from e


@SubjectRegistry.register("chat-db-app", "cloud-gcp")
def _create_gcp_chatdb(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a GCP Chat DB App eval subject.

    Args:
        instance_id: Instance number for parallel execution
        **kwargs: Additional arguments (project, zone, machine_type)

    Returns:
        GCPChatDBAppSubject instance

    Raises:
        ImportError: If cloud dependencies not installed
    """
    try:
        from eval.subjects.cloud.gcp.chatdb_subject import GCPChatDBAppSubject
        return GCPChatDBAppSubject(
            instance_id=instance_id,
            project=kwargs.get("project"),
            zone=kwargs.get("zone", "us-central1-a"),
            machine_type=kwargs.get("machine_type", "e2-standard-2"),
        )
    except ImportError as e:
        raise ImportError(
            "Cloud dependencies not installed. Install with: pip install 'eval[cloud]'"
        ) from e


@SubjectRegistry.register("chat-db-app-shard", "cloud-gcp")
def _create_gcp_chatdb_shard(instance_id: int = 0, **kwargs) -> EvalSubject:
    """Create a GCP Chat DB App Shard eval subject.

    Args:
        instance_id: Instance number for parallel execution
        **kwargs: Additional arguments (project, zone, machine_type)

    Returns:
        GCPChatDBAppShardSubject instance

    Raises:
        ImportError: If cloud dependencies not installed
    """
    try:
        from eval.subjects.cloud.gcp.chatdb_shard_subject import GCPChatDBAppShardSubject
        return GCPChatDBAppShardSubject(
            instance_id=instance_id,
            project=kwargs.get("project"),
            zone=kwargs.get("zone", "us-central1-a"),
            machine_type=kwargs.get("machine_type", "e2-standard-2"),
        )
    except ImportError as e:
        raise ImportError(
            "Cloud dependencies not installed. Install with: pip install 'eval[cloud]'"
        ) from e
