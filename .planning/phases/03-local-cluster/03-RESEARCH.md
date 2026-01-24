# Phase 3: Local Cluster - Research

**Researched:** 2026-01-24
**Domain:** TiKV Docker Compose deployment, Prometheus/Grafana observability, load generation, containerized operator
**Confidence:** HIGH

## Summary

This phase transforms the Phase 1 stub docker-compose.yaml (nginx:alpine placeholder) into a fully functional TiKV cluster with observability and load generation. The research focused on four domains: TiKV/PD Docker deployment patterns, Prometheus/Grafana containerized monitoring, go-ycsb load generation, and Apple Silicon (OrbStack) compatibility.

TiKV provides official Docker images (`pingcap/tikv`, `pingcap/pd`) with ARM64 variants (`pingcap/tikv-arm64`, `pingcap/pd-arm64`) for native Apple Silicon support. The standard deployment is 3 PD nodes + 3 TiKV nodes using Docker Compose with user-defined bridge networking. Key configuration requires `--advertise-addr` for each service to enable inter-container and external communication. Prometheus scrapes TiKV on port 20180 (status address) and PD on port 2379.

PingCAP's `tidb-docker-compose` repository is archived (July 2025) but provides reference patterns. For our use case (TiKV-only, no TiDB), we create a simplified compose file. Load generation uses go-ycsb with TiKV raw mode against the PD endpoint.

**Primary recommendation:** Create docker-compose.yaml with 3 PD + 3 TiKV nodes using ARM64 images for native OrbStack performance. Use `depends_on` with `condition: service_healthy` to ensure proper startup order. Include Prometheus, Grafana, and a go-ycsb container for load testing.

## Standard Stack

The established images/tools for this domain:

### Core Docker Images
| Image | Version | Purpose | Why Standard |
|-------|---------|---------|--------------|
| pingcap/pd-arm64 | latest | Placement Driver cluster | Native ARM64 for OrbStack/Mac, manages TiKV scheduling |
| pingcap/tikv-arm64 | latest | Distributed KV store | Native ARM64, 3 replicas for fault tolerance |
| prom/prometheus | latest | Metrics collection | Multi-arch image, scrapes TiKV/PD metrics |
| grafana/grafana | latest | Dashboard visualization | Multi-arch image, displays cluster health |

### Supporting
| Image | Version | Purpose | When to Use |
|-------|---------|---------|-------------|
| pingcap/go-ycsb | - | Load generation | Custom build required - no official image |
| python:3.11-slim | latest | Operator container | Run operator-core in container |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ARM64 images | AMD64 with emulation | Slower performance, higher CPU via QEMU |
| Bridge network | Host network | Host mode unsupported on macOS/OrbStack |
| go-ycsb | sysbench-tpcc | go-ycsb has native TiKV support |

**Note on go-ycsb Docker Image:**
PingCAP does not publish an official go-ycsb Docker image. Options:
1. Build from source using Dockerfile in go-ycsb repo
2. Use third-party `pierrezemb/go-ycsb` image
3. Download binary and run directly

**Recommendation:** Build a custom go-ycsb image from source for Phase 3.

## Architecture Patterns

### Recommended File Structure
```
subjects/tikv/
├── docker-compose.yaml      # Main cluster definition
├── config/
│   ├── prometheus.yml       # Prometheus scrape config
│   ├── grafana/
│   │   └── datasources.yml  # Grafana datasource provisioning
│   │   └── dashboards.yml   # Dashboard provisioning config
│   │   └── dashboards/      # TiKV dashboard JSON files
│   ├── pd.toml              # PD configuration (optional)
│   └── tikv.toml            # TiKV configuration (optional)
└── Dockerfile.operator      # Operator container build
```

### Pattern 1: PD Cluster Configuration
**What:** 3-node PD cluster with initial cluster bootstrap
**When to use:** Always - PD must be available before TiKV starts
**Example:**
```yaml
# Source: https://tikv.org/docs/3.0/tasks/deploy/docker/
services:
  pd0:
    image: pingcap/pd-arm64:latest
    ports:
      - "2379:2379"
    volumes:
      - pd0-data:/data
    command:
      - --name=pd0
      - --data-dir=/data
      - --client-urls=http://0.0.0.0:2379
      - --advertise-client-urls=http://pd0:2379
      - --peer-urls=http://0.0.0.0:2380
      - --advertise-peer-urls=http://pd0:2380
      - --initial-cluster=pd0=http://pd0:2380,pd1=http://pd1:2380,pd2=http://pd2:2380
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:2379/pd/api/v1/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
```

### Pattern 2: TiKV Node Configuration
**What:** TiKV nodes that connect to PD cluster
**When to use:** After PD is healthy
**Example:**
```yaml
# Source: https://tikv.org/docs/3.0/tasks/deploy/docker/
services:
  tikv0:
    image: pingcap/tikv-arm64:latest
    ports:
      - "20160:20160"
    volumes:
      - tikv0-data:/data
    command:
      - --addr=0.0.0.0:20160
      - --advertise-addr=tikv0:20160
      - --status-addr=0.0.0.0:20180
      - --advertise-status-addr=tikv0:20180
      - --data-dir=/data
      - --pd=pd0:2379,pd1:2379,pd2:2379
    depends_on:
      pd0:
        condition: service_healthy
      pd1:
        condition: service_healthy
      pd2:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:20180/status"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 30s
```

### Pattern 3: Prometheus TiKV Scrape Configuration
**What:** Scrape config for PD and TiKV metrics
**When to use:** Observability stack
**Example:**
```yaml
# Source: https://tikv.org/docs/5.1/deploy/monitor/deploy/
# File: config/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'pd'
    honor_labels: true
    static_configs:
      - targets:
        - 'pd0:2379'
        - 'pd1:2379'
        - 'pd2:2379'

  - job_name: 'tikv'
    honor_labels: true
    static_configs:
      - targets:
        - 'tikv0:20180'
        - 'tikv1:20180'
        - 'tikv2:20180'
```

### Pattern 4: go-ycsb Load Generation
**What:** YCSB workload against TiKV cluster
**When to use:** Generate traffic for testing invariant detection
**Example:**
```bash
# Source: https://github.com/pingcap/go-ycsb
# Load phase - insert initial data
go-ycsb load tikv -P /workloads/workloada \
  -p tikv.pd="pd0:2379,pd1:2379,pd2:2379" \
  -p tikv.type="raw" \
  -p recordcount=100000 \
  -p threadcount=16

# Run phase - execute workload
go-ycsb run tikv -P /workloads/workloada \
  -p tikv.pd="pd0:2379,pd1:2379,pd2:2379" \
  -p tikv.type="raw" \
  -p operationcount=1000000 \
  -p threadcount=32
```

### Pattern 5: Grafana Provisioning
**What:** Auto-configure Grafana with Prometheus datasource
**When to use:** Avoid manual Grafana setup
**Example:**
```yaml
# Source: https://grafana.com/docs/grafana/latest/administration/provisioning/
# File: config/grafana/datasources.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

### Anti-Patterns to Avoid
- **Host network mode on Mac:** Does not work with Docker Desktop or OrbStack - use bridge networking
- **Missing advertise-addr:** PD/TiKV cannot communicate without correct advertise addresses
- **AMD64 emulation when ARM64 available:** Performance penalty up to 5x slower
- **No healthchecks:** Race conditions where TiKV starts before PD is ready
- **Single PD node:** Not fault tolerant, blocks region scheduling

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service startup ordering | Shell scripts with sleep | depends_on + condition: service_healthy | Docker-native, handles retries |
| Prometheus config | Hardcoded in image | Mounted prometheus.yml | Easy to modify, version controlled |
| Grafana setup | Manual UI clicks | Provisioning files | Reproducible, idempotent |
| TiKV healthcheck | Custom binary | wget to /status endpoint | Built into image, reliable |
| Load generator | Custom Python client | go-ycsb | Battle-tested, configurable workloads |

**Key insight:** Docker Compose healthchecks with `condition: service_healthy` solve the PD-before-TiKV ordering problem elegantly. Do not use sleep-based orchestration.

## Common Pitfalls

### Pitfall 1: Wrong advertise-addr Format
**What goes wrong:** TiKV nodes cannot find each other; PD shows stores as Down
**Why it happens:** Using container ID or wrong hostname in advertise-addr
**How to avoid:** Use Docker Compose service names (e.g., `tikv0:20160`) as advertise addresses
**Warning signs:** "connection refused" in TiKV logs, stores stuck in "Disconnected" state

### Pitfall 2: Port Confusion (20160 vs 20180)
**What goes wrong:** Prometheus cannot scrape TiKV metrics
**Why it happens:** TiKV exposes gRPC on 20160, status/metrics on 20180
**How to avoid:** Always scrape 20180 for Prometheus; 20160 is for gRPC clients
**Warning signs:** Prometheus targets show "connection refused" on port 20160

### Pitfall 3: OrbStack ARM64 Image Selection
**What goes wrong:** Slow performance, high CPU during emulation
**Why it happens:** Pulling AMD64 images on Apple Silicon
**How to avoid:** Explicitly use `pingcap/tikv-arm64:latest` and `pingcap/pd-arm64:latest`
**Warning signs:** "linux/amd64" warnings in docker pull, slow cluster startup

### Pitfall 4: PD Initial Cluster Not Matching
**What goes wrong:** PD nodes fail to form quorum
**Why it happens:** `--initial-cluster` parameter inconsistent across PD nodes
**How to avoid:** All PD nodes MUST have identical `--initial-cluster` values
**Warning signs:** "member is not the same" errors in PD logs

### Pitfall 5: Volume Permissions
**What goes wrong:** TiKV/PD fail to write data
**Why it happens:** Container user cannot write to mounted volumes
**How to avoid:** Use named volumes (Docker manages permissions) instead of bind mounts for data
**Warning signs:** "permission denied" errors on startup

### Pitfall 6: go-ycsb Without Docker Image
**What goes wrong:** Load generator cannot run in container
**Why it happens:** PingCAP does not publish official go-ycsb Docker image
**How to avoid:** Build custom image from Dockerfile in go-ycsb repo
**Warning signs:** "image not found" when starting load generator

## Code Examples

Verified patterns from official sources:

### Complete docker-compose.yaml Structure
```yaml
# Source: Synthesized from https://tikv.org/docs/3.0/tasks/deploy/docker/
# and https://github.com/pingcap/tidb-docker-compose
version: "3.8"

services:
  # PD Cluster (3 nodes)
  pd0:
    image: pingcap/pd-arm64:latest
    container_name: pd0
    ports:
      - "2379:2379"
    volumes:
      - pd0-data:/data
    command: >
      --name=pd0
      --data-dir=/data
      --client-urls=http://0.0.0.0:2379
      --advertise-client-urls=http://pd0:2379
      --peer-urls=http://0.0.0.0:2380
      --advertise-peer-urls=http://pd0:2380
      --initial-cluster=pd0=http://pd0:2380,pd1=http://pd1:2380,pd2=http://pd2:2380
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:2379/pd/api/v1/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  pd1:
    image: pingcap/pd-arm64:latest
    container_name: pd1
    volumes:
      - pd1-data:/data
    command: >
      --name=pd1
      --data-dir=/data
      --client-urls=http://0.0.0.0:2379
      --advertise-client-urls=http://pd1:2379
      --peer-urls=http://0.0.0.0:2380
      --advertise-peer-urls=http://pd1:2380
      --initial-cluster=pd0=http://pd0:2380,pd1=http://pd1:2380,pd2=http://pd2:2380
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:2379/pd/api/v1/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  pd2:
    image: pingcap/pd-arm64:latest
    container_name: pd2
    volumes:
      - pd2-data:/data
    command: >
      --name=pd2
      --data-dir=/data
      --client-urls=http://0.0.0.0:2379
      --advertise-client-urls=http://pd2:2379
      --peer-urls=http://0.0.0.0:2380
      --advertise-peer-urls=http://pd2:2380
      --initial-cluster=pd0=http://pd0:2380,pd1=http://pd1:2380,pd2=http://pd2:2380
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:2379/pd/api/v1/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  # TiKV Cluster (3 nodes)
  tikv0:
    image: pingcap/tikv-arm64:latest
    container_name: tikv0
    ports:
      - "20160:20160"
    volumes:
      - tikv0-data:/data
    command: >
      --addr=0.0.0.0:20160
      --advertise-addr=tikv0:20160
      --status-addr=0.0.0.0:20180
      --advertise-status-addr=tikv0:20180
      --data-dir=/data
      --pd=pd0:2379,pd1:2379,pd2:2379
    depends_on:
      pd0: { condition: service_healthy }
      pd1: { condition: service_healthy }
      pd2: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:20180/status"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 30s
    restart: on-failure

  # tikv1, tikv2 follow same pattern...

  # Prometheus
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=15d
      - --web.enable-lifecycle
    depends_on:
      tikv0: { condition: service_healthy }
    restart: on-failure

  # Grafana
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - ./config/grafana/datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml:ro
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - prometheus
    restart: on-failure

volumes:
  pd0-data:
  pd1-data:
  pd2-data:
  tikv0-data:
  tikv1-data:
  tikv2-data:
  prometheus-data:
  grafana-data:
```

### Verify Cluster Health
```bash
# Source: https://tikv.org/docs/3.0/tasks/deploy/docker/
# Check PD cluster health
curl http://localhost:2379/pd/api/v1/health

# Check store status
curl http://localhost:2379/pd/api/v1/stores

# Expected: All stores show "state_name": "Up"
```

### go-ycsb Dockerfile
```dockerfile
# Source: https://github.com/pingcap/go-ycsb
FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git make

WORKDIR /build
RUN git clone https://github.com/pingcap/go-ycsb.git .
RUN make

FROM alpine:latest
COPY --from=builder /build/bin/go-ycsb /usr/local/bin/
COPY --from=builder /build/workloads /workloads

ENTRYPOINT ["go-ycsb"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| tidb-docker-compose (Helm templates) | Direct docker-compose.yaml | July 2025 (archived) | Simpler, no Helm dependency |
| AMD64 images with emulation | Native ARM64 images | 2021+ | 2-5x performance improvement on Mac |
| Manual Grafana setup | Provisioning files | Grafana 5.0+ | Reproducible dashboards |
| sleep-based startup ordering | depends_on: service_healthy | Docker Compose 2.1+ | Reliable ordering |

**Deprecated/outdated:**
- **tidb-docker-compose:** Archived July 2025, use patterns but not directly
- **docker-compose (hyphen):** Use `docker compose` (space) command

## Open Questions

Things that couldn't be fully resolved:

1. **TiKV ARM64 Image Tags**
   - What we know: `pingcap/tikv-arm64:latest` exists
   - What's unclear: What specific version "latest" resolves to; whether v8.x tags available
   - Recommendation: Use `latest` initially, pin to specific version after verification

2. **go-ycsb Docker Best Practices**
   - What we know: No official image; Dockerfile available in repo
   - What's unclear: Whether third-party images are maintained
   - Recommendation: Build custom image from source for reliability

3. **TiKV Dashboard JSON Compatibility**
   - What we know: Dashboard JSONs available in tikv/tikv repo
   - What's unclear: Whether release-5.0 dashboards work with latest TiKV
   - Recommendation: Start without dashboards; add incrementally

4. **Operator Container Networking**
   - What we know: Operator needs access to PD (2379) and Prometheus (9090)
   - What's unclear: Best pattern for operator to run with cluster
   - Recommendation: Add operator as another service in same Docker network

## Sources

### Primary (HIGH confidence)
- [TiKV Docker Deployment](https://tikv.org/docs/3.0/tasks/deploy/docker/) - Official Docker deployment guide with PD/TiKV commands
- [TiKV Docker Compose](https://tikv.org/docs/3.0/tasks/deploy/docker-compose/) - Docker Compose overview
- [TiKV Monitoring Deployment](https://tikv.org/docs/5.1/deploy/monitor/deploy/) - Prometheus/Grafana setup
- [TiKV Key Metrics](https://tikv.org/docs/4.0/tasks/monitor/key-metrics/) - Critical metrics to monitor
- [Docker Hub pingcap/tikv-arm64](https://hub.docker.com/r/pingcap/tikv-arm64) - ARM64 TiKV image
- [Docker Hub pingcap/pd-arm64](https://hub.docker.com/r/pingcap/pd-arm64) - ARM64 PD image
- [go-ycsb GitHub](https://github.com/pingcap/go-ycsb) - Load generation tool
- [OrbStack Docker Docs](https://docs.orbstack.dev/docker/) - OrbStack compatibility

### Secondary (MEDIUM confidence)
- [tidb-docker-compose](https://github.com/pingcap/tidb-docker-compose) - Reference patterns (archived July 2025)
- [TiKV Configuration Flags](https://docs.pingcap.com/tidb/stable/command-line-flags-for-tikv-configuration/) - Command line options
- [Grafana Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/) - Dashboard automation
- [Docker Compose Healthchecks](https://docs.docker.com/compose/how-tos/startup-order/) - Startup ordering

### Tertiary (LOW confidence)
- Third-party go-ycsb Docker images (pierrezemb/go-ycsb) - May not be maintained

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official PingCAP images verified on Docker Hub
- Architecture: HIGH - Patterns from official TiKV documentation
- Pitfalls: HIGH - Common issues documented in TiKV troubleshooting guides
- OrbStack compatibility: MEDIUM - ARM64 images available, but not tested in this research

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - Docker images are stable)
