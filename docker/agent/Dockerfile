FROM python:3.12-slim

WORKDIR /app

# Install CLI tools - HTTP, JSON, editing, version control, networking, monitoring, and Docker
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    jq \
    vim \
    git \
    netcat-openbsd \
    dnsutils \
    iputils-ping \
    htop \
    tcpdump \
    traceroute \
    nmap \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    anthropic \
    httpx \
    redis \
    pyyaml \
    pandas \
    numpy \
    prometheus-client

# Create audit logs directory
RUN mkdir -p /app/audit_logs
