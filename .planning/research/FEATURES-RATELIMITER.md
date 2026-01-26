# Features Research: Rate Limiter Subject

**Domain:** Distributed rate limiter monitoring and anomaly detection
**Researched:** 2026-01-26
**Confidence:** HIGH (patterns well-documented, aligns with existing TiKV patterns)

## Executive Summary

A distributed rate limiter with Redis backend presents several observable invariants and anomaly types distinct from traditional infrastructure monitoring. Unlike TiKV where we focus on node health and replication, rate limiters have a rich surface for **behavioral anomalies** - states where the system is technically "up" but behaving incorrectly.

This makes rate limiters an excellent second subject: the AI must diagnose issues in a system it hasn't seen before, using reasoning about distributed systems behavior rather than pre-programmed rules.

## Rate Limiter Invariants

What "healthy" looks like for a distributed rate limiter.

### Core Health Invariants

| Invariant | Description | Observable Via |
|-----------|-------------|----------------|
| **Nodes reachable** | All rate limiter nodes respond to health checks | HTTP health endpoints |
| **Redis connected** | All nodes have active Redis connection | Node health API / connection status |
| **Limits enforced** | Requests exceeding limits are rejected | Allow/deny ratio matches expected |
| **State consistent** | Counter values agree across nodes (within tolerance) | Redis key inspection |

### Behavioral Invariants

| Invariant | Description | Why It Matters |
|-----------|-------------|----------------|
| **No over-admission** | Total allowed requests <= configured limit | Core purpose of rate limiter |
| **No under-admission** | Legitimate requests within limit are allowed | Availability/UX impact |
| **Bounded latency** | Rate check latency < threshold (e.g., 5ms p99) | Rate limiter shouldn't slow requests |
| **Consistent decisions** | Same key gets consistent allow/deny across nodes | User experience consistency |

## Anomaly Types

Specific anomalies to detect and diagnose, organized by what makes them interesting for AI diagnosis.

### Table Stakes Anomalies

Must-have monitoring - without these, the system isn't being monitored at all.

| Anomaly | Observable Signal | Severity | Grace Period |
|---------|------------------|----------|--------------|
| **Node unreachable** | Health check fails | Critical | 0s (immediate) |
| **Redis disconnected** | Connection state = disconnected | Critical | 0s (immediate) |
| **High rate check latency** | P99 latency > 5ms | Warning | 30s |
| **Redis latency spike** | Redis operation P99 > 10ms | Warning | 30s |

**Rationale:** These are infrastructure problems similar to TiKV's "store down" invariant. Must detect, but not particularly interesting for AI diagnosis - root cause is obvious.

### Differentiators: Behavioral Anomalies

These showcase AI's diagnostic reasoning - the system is "up" but something is wrong.

| Anomaly | Observable Signal | Why Interesting for AI |
|---------|------------------|------------------------|
| **Counter drift** | Same key has different counter values across nodes | Requires reasoning about eventual consistency, Redis replication lag, or split-brain |
| **Ghost allowing** | Allow rate exceeds configured limit | Could be clock skew, race condition, or algorithm bug |
| **Over-throttling** | Deny rate too high for actual request volume | Could be stuck counter, wrong window calculation, or stale state |
| **Burst boundary abuse** | 2x normal traffic in 2-second window at minute boundary | Classic fixed-window vulnerability - AI must recognize the pattern |
| **Hot key imbalance** | One key getting 10x checks vs. others | Potential attack pattern or misconfigured client |
| **Stale counter** | Counter hasn't decremented despite time passing | TTL/EXPIRE failure, key stuck in Redis |

#### Counter Drift (PRIMARY DIFFERENTIATOR)

**What it looks like:**
- Node A sees counter = 45 for key "user:123"
- Node B sees counter = 52 for key "user:123"
- Difference > expected (given Redis replication lag)

**Why AI diagnosis is valuable:**
The AI must reason about:
1. Is this expected replication lag? (check Redis replication_offset)
2. Is this a Redis cluster partition? (check cluster health)
3. Is this clock skew affecting sliding windows? (check node timestamps)
4. Is this a race condition in the algorithm? (check concurrent request rate)

**Observable metrics:**
- Counter values per key per node
- Redis replication lag
- Node clock offsets
- Concurrent request rate

#### Ghost Allowing (Over-Admission)

**What it looks like:**
- Limit is 100 req/min for key "api:gold-tier"
- Actual allowed requests = 150 in last minute

**Why AI diagnosis is valuable:**
Multiple possible causes:
1. Fixed window boundary burst (100 at :59, 100 at :00)
2. Clock skew between nodes causing window disagreement
3. Redis INCR race condition (rare but possible)
4. Incorrect limit configuration deployment

**Observable metrics:**
- Allowed count per minute (actual)
- Configured limit
- Request timestamps at window boundaries
- Node decision distribution

#### Burst Boundary Abuse

**What it looks like:**
- Normal traffic: 50 req/min steady
- Anomaly period: 100 req in 2 seconds (50 at :58-:00, 50 at :00-:02)
- All requests allowed despite 100/min limit

**Why AI diagnosis is valuable:**
Classic distributed systems interview question. AI must:
1. Recognize the timing pattern (requests clustered at boundary)
2. Identify this as fixed-window vulnerability (if using fixed window)
3. Suggest sliding window as mitigation
4. Or confirm this is expected behavior for the chosen algorithm

### Anti-Features

What NOT to build and why - critical for keeping scope minimal.

| Anti-Feature | Why NOT to Build | What to Do Instead |
|--------------|------------------|-------------------|
| **Per-user dashboards** | High cardinality, scope creep | Aggregate metrics only, sample keys |
| **Automatic limit adjustment** | Too complex, out of scope | Observe and recommend only |
| **DDoS detection** | Different problem domain entirely | Stick to rate limiting behavior |
| **Request content analysis** | Not rate limiter's job | Just count requests, don't inspect |
| **Multi-tenancy isolation** | Complicates architecture | Single "demo" tenant |
| **Persistent violation history** | Overkill for proof of concept | In-memory is sufficient |
| **Alerting/paging integration** | Out of scope for demo | Terminal output only |
| **Baseline learning / ML-based thresholds** | Too complex, per CONTEXT.md decision | Fixed thresholds |

**Key principle:** The rate limiter is a vehicle for demonstrating AI diagnosis, not a production-grade rate limiter. Keep it simple enough that anomalies are easy to create and diagnose.

## Chaos Injection Ideas

How to create interesting failures for demo purposes.

### Easy Wins (Infrastructure Failures)

| Injection | How | Expected Anomaly |
|-----------|-----|------------------|
| **Kill a node** | `docker stop ratelimiter-1` | Node unreachable |
| **Redis disconnect** | Block Redis port for one node | Redis disconnected |
| **Redis latency** | `tc qdisc add ... delay 100ms` on Redis traffic | Redis latency spike |

### Interesting Scenarios (Behavioral Anomalies)

| Injection | How | Expected Anomaly |
|-----------|-----|------------------|
| **Counter drift** | Partition one node from Redis briefly, then restore | Nodes disagree on counter values |
| **Ghost allowing** | Send traffic burst at window boundary | Over-admission (if fixed window) |
| **Clock skew** | Adjust one node's clock +/- 30 seconds | Inconsistent decisions |
| **Hot key attack** | 90% of traffic to single key | Hot key imbalance |
| **Stale counter** | Delete key's TTL in Redis: `PERSIST key` | Counter never expires |
| **Race condition amplification** | High concurrency to single key | Counter drift / over-admission |

### Demo-Friendly Scenarios

These create clear "before/after" for demos:

1. **The Boundary Burst**
   - Setup: Rate limiter with 10 req/min limit, fixed window
   - Injection: Send 10 requests at :59, 10 at :00
   - Observable: 20 requests allowed in 2 seconds
   - AI diagnosis: "Fixed window algorithm vulnerable to boundary burst"

2. **The Drifting Counter**
   - Setup: 3 nodes, sliding window algorithm
   - Injection: Network partition node-1 from Redis for 5 seconds
   - Observable: Counter values diverge, then slowly converge
   - AI diagnosis: "Redis replication lag during partition caused temporary inconsistency"

3. **The Stuck Key**
   - Setup: Normal operation with TTLs
   - Injection: `PERSIST ratelimit:user:demo` in Redis
   - Observable: Counter grows without bound, eventually blocks all requests
   - AI diagnosis: "Key missing TTL, counter accumulated across windows"

## Feature Priority for Implementation

Given this is a proof-of-concept second subject:

### Phase 1: Foundation (Must Have)
- [ ] Node health check (reachable/unreachable)
- [ ] Redis connectivity check
- [ ] Basic counter inspection (get current value for key)

### Phase 2: Core Anomalies (Should Have)
- [ ] Counter drift detection (compare across nodes)
- [ ] Allow/deny ratio monitoring
- [ ] High latency detection

### Phase 3: Differentiators (Nice to Have)
- [ ] Boundary burst detection
- [ ] Hot key detection
- [ ] Stale counter detection

### Deferred (Out of Scope)
- Per-user analytics
- Automatic remediation
- Historical trending

## Confidence Assessment

| Area | Confidence | Reasoning |
|------|------------|-----------|
| Table stakes anomalies | HIGH | Well-documented in industry (rate limiter monitoring is common) |
| Counter drift detection | HIGH | Core distributed systems pattern, observable via Redis |
| Boundary burst pattern | HIGH | Classic algorithm limitation, easy to demonstrate |
| Chaos injection approaches | MEDIUM | Depends on actual rate limiter implementation details |
| Grace periods | MEDIUM | Copied from TiKV patterns, may need tuning |

## Sources

### Primary (HIGH confidence)
- [API7 Rate Limiting Guide](https://api7.ai/blog/rate-limiting-guide-algorithms-best-practices) - Algorithm tradeoffs and boundary issues
- [Hidden Complexity of Rate Limiting](https://bnacar.dev/2025/10/23/hidden-complexity-of-rate-limiting.html) - Distributed challenges, clock sync
- [Redis Rate Limiter Issues](https://medium.com/ratelimitly/why-you-shouldnt-use-redis-as-a-rate-limiter-part-1-of-2-3d4261f5b38a) - EXPIRE failures, cluster issues
- [Redis Split Brain](https://medium.com/@umeshcapg/when-redis-cluster-says-break-up-redis-cluster-split-brain-problem-and-solution-f9637e9984ed) - Consistency challenges
- [Distributed Rate Limiting Tools](https://blog.dreamfactory.com/how-distributed-rate-limiting-works-with-open-source-tools) - State consistency, clock sync

### Secondary (MEDIUM confidence)
- [Datadog AI Metrics Monitoring](https://www.datadoghq.com/blog/ai-powered-metrics-monitoring/) - Observability patterns
- [Chaos Engineering Guide](https://steadybit.com/blog/chaos-experiments/) - Fault injection approaches
- [API Gateway Resilience Testing](https://www.gremlin.com/blog/validating-the-resilience-of-your-api-gateway-with-chaos-engineering) - Rate limit testing patterns

### Existing Project Patterns (HIGH confidence)
- `/Users/jrtipton/x/operator/packages/operator-tikv/src/operator_tikv/invariants.py` - Invariant checking patterns
- `/Users/jrtipton/x/operator/.planning/phases/02-tikv-subject/02-RESEARCH.md` - Subject implementation patterns
