FROM python:3.12-slim

WORKDIR /app

# Install CLI tools - HTTP, JSON, editing, version control, networking, monitoring
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
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI only (not daemon)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
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

# Copy and install operator packages (protocols first, then core)
COPY packages/operator-protocols /app/packages/operator-protocols
COPY packages/operator-core /app/packages/operator-core
RUN pip install --no-cache-dir -e /app/packages/operator-protocols
RUN pip install --no-cache-dir -e /app/packages/operator-core

# Create audit logs directory
RUN mkdir -p /app/audit_logs
