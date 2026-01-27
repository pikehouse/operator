"""Pydantic models matching ratelimiter-service API responses."""

from datetime import datetime

from pydantic import BaseModel


class NodeInfo(BaseModel):
    """Information about a rate limiter node."""

    id: str
    address: str
    state: str
    registered_at: datetime | None = None


class NodesResponse(BaseModel):
    """Response from /api/nodes."""

    nodes: list[NodeInfo]


class CounterInfo(BaseModel):
    """Information about a rate limit counter."""

    key: str
    count: int
    limit: int
    remaining: int


class CountersResponse(BaseModel):
    """Response from /api/counters."""

    counters: list[CounterInfo]


class LimitsResponse(BaseModel):
    """Response from /api/limits."""

    default_limit: int
    default_window_ms: int


class BlockedKeyInfo(BaseModel):
    """Information about a blocked key."""

    key: str
    current_count: int
    limit: int


class BlocksResponse(BaseModel):
    """Response from /api/blocks."""

    blocked: list[BlockedKeyInfo]


class UpdateLimitRequest(BaseModel):
    """Request to update rate limit for a key."""

    limit: int
    window_ms: int | None = None


class UpdateLimitResponse(BaseModel):
    """Response from PUT /api/limits/{key}."""

    key: str
    limit: int
    window_ms: int
    updated: bool
