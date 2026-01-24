# Phase 2: TiKV Subject - Research

**Researched:** 2026-01-24
**Domain:** TiKV PD API, Prometheus metrics, TiKV log parsing, Python async HTTP clients
**Confidence:** HIGH

## Summary

This phase implements the TiKV Subject, the first complete subject implementation against the interface defined in Phase 1. The research focused on four key domains: PD API endpoints for cluster state observation, Prometheus metrics for performance monitoring, TiKV log format for event extraction, and Python async patterns for building the clients.

TiKV provides a comprehensive HTTP API through Placement Driver (PD) at `/pd/api/v1/*` endpoints for cluster state, stores, and regions. Prometheus metrics are well-documented with specific metric names for latency (`tikv_grpc_msg_duration_seconds`), QPS (`tikv_storage_command_total`), disk (`tikv_store_size_bytes`), and Raft health (`tikv_raftstore_region_count`). TiKV uses a structured log format that enables regex-based parsing for leadership changes and other events.

**Primary recommendation:** Use httpx AsyncClient for both PD API and Prometheus HTTP API queries. Parse TiKV logs using the TiDB unified log format specification. Access container logs via python-on-whales (already in Phase 1 stack).

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | latest | Async HTTP client for PD API and Prometheus | Already in Phase 1 stack, async support, connection pooling |
| python-on-whales | latest | Docker container log access | Already in Phase 1 stack, streaming log support |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | v2 | Response validation | PD API and Prometheus response parsing |
| re (stdlib) | - | Log parsing | TiKV log line parsing |
| datetime (stdlib) | - | Timestamp handling | Log timestamp parsing, metric time ranges |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx for Prometheus | prometheus-api-client | Additional dependency, httpx is simpler for basic queries |
| python-on-whales for logs | docker-py | docker-py has streaming issues, python-on-whales already in stack |
| Regex for log parsing | Custom parser | Regex is sufficient for structured TiDB log format |

**Installation:**
```bash
# Already installed in Phase 1, no new dependencies needed
# TiKV subject package will depend on operator-core
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-tikv/
├── pyproject.toml
└── src/
    └── operator_tikv/
        ├── __init__.py
        ├── subject.py          # TiKVSubject implementation
        ├── pd_client.py        # PD API client
        ├── prom_client.py      # Prometheus metrics client
        ├── log_parser.py       # TiKV log parser
        ├── invariants.py       # TiKV invariant checks
        └── types.py            # TiKV-specific response types
```

### Pattern 1: Async Client with Injected httpx
**What:** TiKV clients receive pre-configured httpx.AsyncClient instances
**When to use:** All external API communication (PD, Prometheus)
**Example:**
```python
# Source: Phase 1 CONTEXT.md decision - core injects clients
import httpx
from dataclasses import dataclass

@dataclass
class PDClient:
    """PD API client with injected httpx client."""

    http: httpx.AsyncClient

    async def get_stores(self) -> list[dict]:
        """GET /pd/api/v1/stores"""
        response = await self.http.get("/pd/api/v1/stores")
        response.raise_for_status()  # Fail loudly per CONTEXT.md
        return response.json()["stores"]

    async def get_store(self, store_id: str) -> dict:
        """GET /pd/api/v1/store/{id}"""
        response = await self.http.get(f"/pd/api/v1/store/{store_id}")
        response.raise_for_status()
        return response.json()

    async def get_regions(self) -> list[dict]:
        """GET /pd/api/v1/regions"""
        response = await self.http.get("/pd/api/v1/regions")
        response.raise_for_status()
        return response.json()["regions"]
```

### Pattern 2: Prometheus Instant Queries via HTTP
**What:** Query Prometheus HTTP API directly with httpx, no additional library needed
**When to use:** Metric collection for invariant checks
**Example:**
```python
# Source: https://prometheus.io/docs/prometheus/latest/querying/api/
import httpx
from dataclasses import dataclass
from typing import Any

@dataclass
class PrometheusClient:
    """Prometheus API client with injected httpx client."""

    http: httpx.AsyncClient

    async def instant_query(self, query: str) -> list[dict[str, Any]]:
        """Execute instant query at current time."""
        response = await self.http.get(
            "/api/v1/query",
            params={"query": query}
        )
        response.raise_for_status()
        data = response.json()
        if data["status"] != "success":
            raise ValueError(f"Prometheus query failed: {data}")
        return data["data"]["result"]

    async def get_metric_value(self, query: str) -> float | None:
        """Get single numeric value from instant query."""
        results = await self.instant_query(query)
        if not results:
            return None
        # Result format: [{"metric": {...}, "value": [timestamp, "value"]}]
        return float(results[0]["value"][1])
```

### Pattern 3: TiKV Log Parsing with Regex
**What:** Parse TiDB unified log format using regex patterns
**When to use:** Extracting leadership change events from logs
**Example:**
```python
# Source: https://github.com/tikv/rfcs/blob/master/text/0018-unified-log-format.md
import re
from dataclasses import dataclass
from datetime import datetime

# TiDB unified log format: [timestamp] [LEVEL] [source] [message] [field=value]...
LOG_PATTERN = re.compile(
    r'\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{2}:\d{2})\] '  # timestamp
    r'\[(\w+)\] '  # level
    r'\[([^\]]+)\] '  # source
    r'\[([^\]]*)\]'  # message
    r'(.*)?$'  # optional fields
)

FIELD_PATTERN = re.compile(r'\[(\w+)=([^\]]+)\]')

@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    source: str
    message: str
    fields: dict[str, str]

def parse_log_line(line: str) -> LogEntry | None:
    """Parse a TiKV log line into structured data."""
    match = LOG_PATTERN.match(line)
    if not match:
        return None

    timestamp_str, level, source, message, fields_str = match.groups()

    # Parse timestamp: 2018/12/15 14:20:11.015 +08:00
    timestamp = datetime.strptime(
        timestamp_str[:23], "%Y/%m/%d %H:%M:%S.%f"
    )

    # Parse fields
    fields = {}
    if fields_str:
        for field_match in FIELD_PATTERN.finditer(fields_str):
            fields[field_match.group(1)] = field_match.group(2)

    return LogEntry(
        timestamp=timestamp,
        level=level,
        source=source,
        message=message,
        fields=fields
    )
```

### Pattern 4: Invariant with Grace Period
**What:** Invariant checks that allow transient violations before alerting
**When to use:** Latency threshold checks (per CONTEXT.md - grace period configurable)
**Example:**
```python
# Source: CONTEXT.md decision - grace period configurable per invariant
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Awaitable

@dataclass
class InvariantViolation:
    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    store_id: str | None = None

@dataclass
class Invariant:
    name: str
    check: Callable[[], Awaitable[str | None]]  # Returns violation message or None
    grace_period: timedelta = field(default_factory=lambda: timedelta(seconds=0))

    # Track active violations for grace period logic
    _active_violations: dict[str, datetime] = field(default_factory=dict)

    async def evaluate(self) -> InvariantViolation | None:
        """Check invariant, respecting grace period."""
        violation_msg = await self.check()
        now = datetime.now()

        if violation_msg is None:
            # Clear any tracked violation
            self._active_violations.pop(self.name, None)
            return None

        # Track when violation first seen
        if self.name not in self._active_violations:
            self._active_violations[self.name] = now

        first_seen = self._active_violations[self.name]

        # Check if grace period has elapsed
        if now - first_seen < self.grace_period:
            return None  # Still within grace period

        return InvariantViolation(
            invariant_name=self.name,
            message=violation_msg,
            first_seen=first_seen,
            last_seen=now
        )
```

### Pattern 5: Container Log Streaming with python-on-whales
**What:** Access Docker container logs for TiKV instances
**When to use:** Collecting log context for AI diagnosis
**Example:**
```python
# Source: https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/container/
from python_on_whales import DockerClient
from datetime import datetime, timedelta

def get_recent_logs(
    docker: DockerClient,
    container_name: str,
    minutes: int = 30
) -> list[str]:
    """Get last N minutes of logs from a container."""
    since = datetime.now() - timedelta(minutes=minutes)

    # Returns string when stream=False (default)
    logs = docker.container.logs(
        container_name,
        since=since,
        timestamps=True
    )

    return logs.split('\n') if logs else []
```

### Anti-Patterns to Avoid
- **Creating httpx clients per request:** Violates connection pooling; use injected long-lived client
- **Blocking on log streaming:** Use `stream=False` for diagnosis context, not real-time streaming
- **Swallowing API errors:** Per CONTEXT.md, fail loudly on unexpected data
- **Polling without backoff:** Use reasonable intervals, don't hammer PD/Prometheus
- **Complex log parsing:** TiDB format is well-defined; regex is sufficient

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prometheus queries | Custom HTTP + PromQL parsing | httpx + standard response format | Prometheus API is simple, no library needed |
| HTTP connection pooling | Manual socket management | httpx.AsyncClient | Handles keepalive, TLS, timeouts |
| Log line parsing | Custom tokenizer | Regex with TiDB log format spec | Format is well-documented with clear structure |
| Timestamp parsing | Manual string slicing | datetime.strptime | Standard library handles all edge cases |
| Retry logic | Custom retry loops | httpx.AsyncHTTPTransport(retries=N) | Built-in to httpx |

**Key insight:** TiKV/PD use standard HTTP APIs with JSON responses. No specialized client libraries are needed - httpx handles everything. The main complexity is understanding the specific API endpoints and metric names.

## Common Pitfalls

### Pitfall 1: PD API Returns Nested Structures
**What goes wrong:** Code assumes flat response, fails to access nested data
**Why it happens:** PD API wraps results (e.g., `{"stores": [...]}` not just `[...]`)
**How to avoid:** Always check PD API response structure; extract the nested array
**Warning signs:** KeyError on response parsing

### Pitfall 2: Prometheus Metric Values are Strings
**What goes wrong:** Code treats metric values as floats directly
**Why it happens:** Prometheus returns `["timestamp", "string_value"]` format
**How to avoid:** Always `float(result["value"][1])` to convert string to number
**Warning signs:** TypeError on arithmetic operations

### Pitfall 3: Store IDs are Strings in Some APIs, Integers in Others
**What goes wrong:** Type mismatches when joining data from different APIs
**Why it happens:** PD returns numeric IDs, Prometheus labels are strings
**How to avoid:** Normalize to string (StoreId type alias) everywhere
**Warning signs:** Failed lookups, key mismatches

### Pitfall 4: Prometheus Queries with Special Characters
**What goes wrong:** PromQL query fails due to unescaped characters
**Why it happens:** Label selectors need proper quoting
**How to avoid:** Use label matchers: `metric{label="value"}` with proper escaping
**Warning signs:** 400 Bad Request from Prometheus

### Pitfall 5: Log Timestamp Timezone Handling
**What goes wrong:** Log timestamps compared incorrectly across time zones
**Why it happens:** TiKV logs include timezone offset that may differ from local
**How to avoid:** Parse timezone from log format, use UTC internally for comparisons
**Warning signs:** Logs appearing out of order, missed time windows

### Pitfall 6: Grace Period State Not Persisted
**What goes wrong:** Operator restart clears violation tracking, re-triggers alerts
**Why it happens:** In-memory tracking of first_seen times lost on restart
**How to avoid:** Accept this limitation for Phase 2; can persist state later if needed
**Warning signs:** Duplicate tickets after restarts

## Code Examples

Verified patterns from official sources:

### PD API: Get All Stores
```python
# Source: https://tikv.org/docs/6.5/deploy/monitor/api/
# GET /pd/api/v1/stores returns:
# {
#   "count": 3,
#   "stores": [
#     {
#       "store": {
#         "id": 1,
#         "address": "tikv-0:20160",
#         "state_name": "Up",
#         "version": "8.1.0"
#       },
#       "status": {
#         "capacity": "100GiB",
#         "available": "80GiB",
#         "leader_count": 100,
#         "region_count": 300
#       }
#     }
#   ]
# }

async def get_stores(http: httpx.AsyncClient) -> list[Store]:
    response = await http.get("/pd/api/v1/stores")
    response.raise_for_status()
    data = response.json()

    stores = []
    for item in data.get("stores", []):
        store_info = item["store"]
        stores.append(Store(
            id=str(store_info["id"]),
            address=store_info["address"],
            state=store_info["state_name"]
        ))
    return stores
```

### PD API: Get Region by ID
```python
# Source: https://github.com/tikv/pd/blob/master/server/api/router.go
# GET /pd/api/v1/region/id/{id}

async def get_region(http: httpx.AsyncClient, region_id: int) -> Region:
    response = await http.get(f"/pd/api/v1/region/id/{region_id}")
    response.raise_for_status()
    data = response.json()

    leader_store_id = str(data["leader"]["store_id"])
    peer_store_ids = [str(p["store_id"]) for p in data.get("peers", [])]

    return Region(
        id=region_id,
        leader_store_id=leader_store_id,
        peer_store_ids=peer_store_ids
    )
```

### Prometheus: Query P99 Latency
```python
# Source: https://tikv.org/docs/4.0/tasks/monitor/key-metrics/
# Metric: tikv_grpc_msg_duration_seconds

async def get_p99_latency_ms(prom: httpx.AsyncClient, store_address: str) -> float:
    """Get P99 gRPC latency for a store in milliseconds."""
    # Note: instance label uses the status address (port 20180), not gRPC port
    query = f'histogram_quantile(0.99, rate(tikv_grpc_msg_duration_seconds_bucket{{instance=~"{store_address}.*"}}[1m]))'

    response = await prom.get("/api/v1/query", params={"query": query})
    response.raise_for_status()
    data = response.json()

    if data["status"] != "success" or not data["data"]["result"]:
        return 0.0

    # Value is in seconds, convert to ms
    seconds = float(data["data"]["result"][0]["value"][1])
    return seconds * 1000
```

### Prometheus: Query Disk Usage
```python
# Source: https://tikv.org/docs/4.0/tasks/monitor/key-metrics/
# Metric: tikv_store_size_bytes

async def get_disk_usage_percent(prom: httpx.AsyncClient, store_address: str) -> float:
    """Get disk usage percentage for a store."""
    # Available space
    available_query = f'tikv_store_size_bytes{{instance=~"{store_address}.*", type="available"}}'
    # Total capacity
    capacity_query = f'tikv_store_size_bytes{{instance=~"{store_address}.*", type="capacity"}}'

    available_resp = await prom.get("/api/v1/query", params={"query": available_query})
    capacity_resp = await prom.get("/api/v1/query", params={"query": capacity_query})

    available_resp.raise_for_status()
    capacity_resp.raise_for_status()

    available_data = available_resp.json()
    capacity_data = capacity_resp.json()

    if (available_data["status"] != "success" or
        capacity_data["status"] != "success" or
        not available_data["data"]["result"] or
        not capacity_data["data"]["result"]):
        raise ValueError("Could not fetch disk metrics")

    available = float(available_data["data"]["result"][0]["value"][1])
    capacity = float(capacity_data["data"]["result"][0]["value"][1])

    if capacity == 0:
        return 0.0

    used = capacity - available
    return (used / capacity) * 100
```

### Log Parsing: Extract Leadership Changes
```python
# Source: https://github.com/tikv/rfcs/blob/master/text/0018-unified-log-format.md
# Leadership change logs contain region_id field and relevant keywords

import re
from dataclasses import dataclass
from datetime import datetime

@dataclass
class LeadershipChange:
    timestamp: datetime
    region_id: int
    message: str

def extract_leadership_changes(log_lines: list[str]) -> list[LeadershipChange]:
    """Extract leadership change events from TiKV logs."""
    changes = []

    # Pattern for leadership-related log messages
    leadership_keywords = [
        "transfer leader",
        "leader changed",
        "became leader",
        "step down",
        "leader election"
    ]

    for line in log_lines:
        # Check if line mentions leadership
        line_lower = line.lower()
        if not any(kw in line_lower for kw in leadership_keywords):
            continue

        # Parse the log line
        entry = parse_log_line(line)
        if entry is None:
            continue

        # Extract region_id if present
        region_id_str = entry.fields.get("region_id")
        if region_id_str is None:
            continue

        try:
            region_id = int(region_id_str)
        except ValueError:
            continue

        changes.append(LeadershipChange(
            timestamp=entry.timestamp,
            region_id=region_id,
            message=entry.message
        ))

    return changes
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| prometheus-api-client library | Direct httpx to Prometheus HTTP API | - | Simpler, no extra dependency |
| docker-py for logs | python-on-whales | 2022+ | Better streaming support, cleaner API |
| Custom log parsing | Regex with TiDB unified format | 2019+ | Format is standardized across TiKV/PD/TiDB |
| Sync HTTP clients | Async httpx | 2020+ | Non-blocking I/O for concurrent queries |

**Deprecated/outdated:**
- **prometheus-api-client for simple queries**: Adds complexity; httpx + JSON is sufficient
- **docker-py logs streaming**: Has known issues with buffering delays

## Open Questions

Things that couldn't be fully resolved:

1. **Exact Prometheus instance label format**
   - What we know: TiKV exposes metrics on status address (port 20180)
   - What's unclear: Whether instance label includes port or just hostname
   - Recommendation: Use regex matching `instance=~"hostname.*"` to be flexible

2. **Leadership change log message variations**
   - What we know: TiDB log format is standardized, region_id field is present
   - What's unclear: Exact message text varies by TiKV version
   - Recommendation: Match on keywords ("leader", "transfer", "election") rather than exact strings

3. **PD API rate limits**
   - What we know: PD is designed for programmatic access
   - What's unclear: Whether aggressive polling could cause issues
   - Recommendation: Poll at reasonable intervals (5-10 seconds), respect any rate limit headers

## Sources

### Primary (HIGH confidence)
- [TiKV PD API Router](https://github.com/tikv/pd/blob/master/server/api/router.go) - Complete API route definitions
- [TiKV Monitoring API](https://tikv.org/docs/6.5/deploy/monitor/api/) - API endpoint documentation
- [TiDB Monitoring API](https://docs.pingcap.com/tidb/stable/tidb-monitoring-api/) - PD API format
- [TiKV Key Metrics](https://tikv.org/docs/4.0/tasks/monitor/key-metrics/) - Prometheus metric names and queries
- [TiKV Grafana Dashboard](https://docs.pingcap.com/tidb/stable/grafana-tikv-dashboard/) - Metric descriptions
- [TiDB Unified Log Format RFC](https://github.com/tikv/rfcs/blob/master/text/0018-unified-log-format.md) - Log format specification
- [TiKV Configuration File](https://docs.pingcap.com/tidb/stable/tikv-configuration-file/) - Log configuration options
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/) - Query endpoints
- [httpx Async Docs](https://www.python-httpx.org/async/) - AsyncClient patterns
- [python-on-whales Container Logs](https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/container/) - Log streaming API

### Secondary (MEDIUM confidence)
- [PD Control Guide](https://docs.pingcap.com/tidb/stable/pd-control/) - Scheduling configuration
- [TiKV Docker Stack](https://tikv.org/docs/4.0/tasks/try/docker-stack/) - Docker deployment patterns

### Tertiary (LOW confidence)
- Community articles on TiKV monitoring patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses libraries already established in Phase 1
- Architecture: HIGH - Patterns verified against official API documentation
- Pitfalls: MEDIUM - Based on API response formats, some community knowledge
- Metrics: HIGH - Metric names verified against official TiKV documentation

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - APIs are stable)
