# Eval worker Docker image for GCP cloud execution
#
# Build:
#   docker build -t eval-worker .
#
# Push to Artifact Registry:
#   docker tag eval-worker us-central1-docker.pkg.dev/PROJECT/eval/worker:latest
#   docker push us-central1-docker.pkg.dev/PROJECT/eval/worker:latest

FROM python:3.12-slim

# Install gcloud CLI + SSH client (needed for VM management and SSH)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates \
    openssh-client \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
       > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
       | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
    && apt-get update && apt-get install -y google-cloud-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install eval package with cloud dependencies
WORKDIR /app
COPY eval/pyproject.toml .
COPY eval/src/ src/

RUN pip install --no-cache-dir ".[cloud]"

# Copy variant configs (loaded at runtime by worker)
COPY eval/variants/ /app/variants/
ENV EVAL_VARIANTS_DIR=/app/variants

# Copy subject compose files needed for cloud trials
COPY subjects/tikv/docker-compose.cloud.yaml /usr/local/lib/subjects/tikv/docker-compose.cloud.yaml
COPY subjects/chat-db-app/docker-compose.cloud.yaml /usr/local/lib/subjects/chat-db-app/docker-compose.cloud.yaml
COPY subjects/chat-db-app/service/ /usr/local/lib/subjects/chat-db-app/service/
COPY subjects/chat-db-app-shard/docker-compose.cloud.yaml /usr/local/lib/subjects/chat-db-app-shard/docker-compose.cloud.yaml
COPY subjects/chat-db-app-shard/service/ /usr/local/lib/subjects/chat-db-app-shard/service/

# Default command: start worker
ENTRYPOINT ["eval"]
CMD ["worker", "start", "--cloud=gcp"]
