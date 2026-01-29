"""Environment-based configuration for rate limiter service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Rate limiter service configuration.

    All settings can be overridden via environment variables with
    RATELIMITER_ prefix. For example:
        RATELIMITER_REDIS_URL=redis://prod-redis:6379
        RATELIMITER_NODE_ID=node-2
    """

    # Redis connection
    redis_url: str = "redis://localhost:6379"

    # Node identity
    node_id: str = "node-1"
    node_host: str = "localhost"
    node_port: int = 8000

    # Rate limiting defaults
    default_limit: int = 100
    default_window_ms: int = 60000  # 60 seconds

    # Node registration
    node_ttl_seconds: int = 30
    node_heartbeat_seconds: int = 10

    model_config = {"env_prefix": "RATELIMITER_"}


settings = Settings()
