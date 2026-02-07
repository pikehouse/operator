#!/bin/bash
# GCP Cloud Eval Infrastructure Setup
#
# Idempotent setup script - safe to run multiple times.
# Creates resources if missing, updates .env with results.
#
# What it sets up:
#   1. Cloud SQL PostgreSQL instance
#   2. Database and user inside Cloud SQL
#   3. Artifact Registry for Docker images
#   4. Builds and pushes the worker image
#   5. Creates instance template for workers
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Docker installed locally
#
# Usage:
#   ./scripts/gcp-setup.sh                    # Uses current gcloud project
#   ./scripts/gcp-setup.sh my-project-id      # Explicit project

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVAL_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$EVAL_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

# --- Configuration ---
PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT" ]; then
    echo "Error: No project specified and none set in gcloud config"
    echo "Usage: $0 <project-id>"
    exit 1
fi

REGION="us-central1"
ZONE="${REGION}-a"
DB_INSTANCE="eval-db"
DB_NAME="eval-db"
DB_USER="postgres"
DB_TIER="db-f1-micro"

echo "=== GCP Cloud Eval Setup (Idempotent) ==="
echo "Project: ${PROJECT}"
echo "Region: ${REGION}"
echo "Env file: ${ENV_FILE}"
echo ""

# --- Helper: Update .env file ---
update_env() {
    local key="$1"
    local value="$2"

    # Create .env if it doesn't exist
    touch "$ENV_FILE"

    # Remove existing key (if any) and add new value
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        # Update existing
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
    else
        # Append new
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
    echo "    ${key}=${value}"
}

# --- Helper: Get .env value ---
get_env() {
    local key="$1"
    grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true
}

# Set project
gcloud config set project "${PROJECT}" --quiet

# --- Enable APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    compute.googleapis.com \
    sqladmin.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet

# --- Cloud SQL Instance ---
echo ""
echo ">>> Cloud SQL instance..."
if gcloud sql instances describe "${DB_INSTANCE}" &>/dev/null; then
    echo "    Instance ${DB_INSTANCE} already exists"
else
    echo "    Creating ${DB_INSTANCE} (this takes 3-5 minutes)..."

    # Generate password if not in .env
    DB_PASSWORD="$(get_env EVAL_DATABASE_PASSWORD)"
    if [ -z "$DB_PASSWORD" ]; then
        DB_PASSWORD="$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)"
    fi

    gcloud sql instances create "${DB_INSTANCE}" \
        --database-version=POSTGRES_15 \
        --tier="${DB_TIER}" \
        --region="${REGION}" \
        --root-password="${DB_PASSWORD}" \
        --authorized-networks=0.0.0.0/0 \
        --quiet

    echo "    Instance created"
fi

# Get instance details
echo ">>> Getting instance details..."
DB_IP=$(gcloud sql instances describe "${DB_INSTANCE}" --format='value(ipAddresses[0].ipAddress)')
CONNECTION_NAME=$(gcloud sql instances describe "${DB_INSTANCE}" --format='value(connectionName)')
echo "    IP: ${DB_IP}"
echo "    Connection: ${CONNECTION_NAME}"

# --- Database ---
echo ""
echo ">>> Database..."
if gcloud sql databases describe "${DB_NAME}" --instance="${DB_INSTANCE}" &>/dev/null; then
    echo "    Database ${DB_NAME} already exists"
else
    echo "    Creating database ${DB_NAME}..."
    gcloud sql databases create "${DB_NAME}" --instance="${DB_INSTANCE}" --quiet
fi

# --- Get or generate password ---
DB_PASSWORD="$(get_env EVAL_DATABASE_PASSWORD)"
if [ -z "$DB_PASSWORD" ]; then
    echo ""
    echo ">>> No password in .env, generating new one..."
    DB_PASSWORD="$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)"

    # Update the postgres user password
    gcloud sql users set-password "${DB_USER}" \
        --instance="${DB_INSTANCE}" \
        --password="${DB_PASSWORD}" \
        --quiet
    echo "    Password set for user ${DB_USER}"
fi

# --- Update .env ---
echo ""
echo ">>> Updating ${ENV_FILE}..."
update_env "GCP_PROJECT" "${PROJECT}"
update_env "GCP_DB_TIER" "${DB_TIER}"
update_env "GCP_DB_REGION" "${REGION}"
update_env "GCP_DB_PRIMARY_ADDRESS" "${DB_IP}"
update_env "GCP_DB_URL" "https://sqladmin.googleapis.com/sql/v1beta4/projects/${PROJECT}/instances/${DB_INSTANCE}"
update_env "GCP_DB_CONNECTION_NAME" "${CONNECTION_NAME}"
update_env "EVAL_DATABASE_PASSWORD" "${DB_PASSWORD}"
update_env "EVAL_DATABASE_URL" "\"postgresql://${DB_USER}:${DB_PASSWORD}@${DB_IP}:5432/${DB_NAME}?sslmode=require\""

# --- Artifact Registry ---
echo ""
echo ">>> Artifact Registry..."
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/eval"
IMAGE="${REGISTRY}/worker:latest"

if gcloud artifacts repositories describe eval --location="${REGION}" &>/dev/null; then
    echo "    Repository already exists"
else
    echo "    Creating repository..."
    gcloud artifacts repositories create eval \
        --repository-format=docker \
        --location="${REGION}" \
        --quiet
fi

# Configure Docker auth
echo ">>> Configuring Docker authentication..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# --- Build and Push Image ---
echo ""
echo ">>> Building Docker image..."
cd "${EVAL_DIR}"
docker build -t eval-worker .
docker tag eval-worker "${IMAGE}"

echo ">>> Pushing to Artifact Registry..."
docker push "${IMAGE}"

# --- Instance Template ---
echo ""
echo ">>> Instance template..."

# Delete existing template if it exists (templates are immutable)
gcloud compute instance-templates delete eval-worker-template --quiet 2>/dev/null || true

# Create startup script
STARTUP_SCRIPT=$(cat <<STARTUP_EOF
#!/bin/bash
set -e

# Wait for Docker to be ready (Container-Optimized OS)
while ! docker info &>/dev/null; do sleep 1; done

# Start Cloud SQL Proxy
docker run -d --name cloud-sql-proxy --restart=always --network=host \
    gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0 \
    --address 0.0.0.0 \
    ${CONNECTION_NAME}

# Wait for proxy to be ready
sleep 5

# Pull and run worker
docker pull ${IMAGE}
docker run -d --name eval-worker --restart=always --network=host \
    -e EVAL_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}" \
    -e GOOGLE_CLOUD_PROJECT="${PROJECT}" \
    ${IMAGE}
STARTUP_EOF
)

echo "    Creating template..."
gcloud compute instance-templates create eval-worker-template \
    --machine-type=e2-standard-2 \
    --image-family=cos-stable \
    --image-project=cos-cloud \
    --boot-disk-size=20GB \
    --scopes=cloud-platform \
    --metadata=startup-script="${STARTUP_SCRIPT}" \
    --quiet

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Cloud SQL:"
echo "  Instance: ${DB_INSTANCE}"
echo "  Database: ${DB_NAME}"
echo "  IP: ${DB_IP}"
echo "  Connection: ${CONNECTION_NAME}"
echo ""
echo "Docker Image: ${IMAGE}"
echo "Instance Template: eval-worker-template"
echo ""
echo "Configuration saved to: ${ENV_FILE}"
echo ""
echo "Next steps:"
echo ""
echo "  # Start workers"
echo "  ./scripts/gcp-workers.sh start 5"
echo ""
echo "  # Enqueue work from your laptop"
echo "  source ${ENV_FILE}"
echo "  eval run campaign config.yaml --cloud=gcp"
