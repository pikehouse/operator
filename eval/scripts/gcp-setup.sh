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
DB_TIER="db-g1-small"  # db-f1-micro too few connections for multiple workers

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
    iap.googleapis.com \
    --quiet

# --- IAM for Default Compute Service Account ---
echo ""
echo ">>> Granting IAM roles to default compute service account..."
PROJECT_NUM=$(gcloud projects describe "${PROJECT}" --format="value(projectNumber)")
COMPUTE_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

for role in roles/artifactregistry.reader roles/cloudsql.client roles/compute.admin roles/iam.serviceAccountUser roles/iap.tunnelResourceAccessor; do
    echo "    Granting ${role}..."
    gcloud projects add-iam-policy-binding "${PROJECT}" \
        --member="serviceAccount:${COMPUTE_SA}" \
        --role="${role}" \
        --quiet &>/dev/null
done

# --- Static IP for Cloud NAT ---
echo ""
echo ">>> Static NAT IP..."
if gcloud compute addresses describe eval-nat-ip --region="${REGION}" &>/dev/null; then
    echo "    Static IP eval-nat-ip already exists"
else
    echo "    Reserving static IP eval-nat-ip..."
    gcloud compute addresses create eval-nat-ip \
        --region="${REGION}" \
        --quiet
fi
NAT_IP=$(gcloud compute addresses describe eval-nat-ip --region="${REGION}" --format='value(address)')
echo "    NAT IP: ${NAT_IP}"
update_env "GCP_NAT_IP" "${NAT_IP}"

# --- Cloud NAT (outbound internet for VMs without public IPs) ---
echo ""
echo ">>> Cloud NAT..."
if gcloud compute routers describe eval-router --region="${REGION}" &>/dev/null; then
    echo "    Cloud Router eval-router already exists"
else
    echo "    Creating Cloud Router..."
    gcloud compute routers create eval-router \
        --region="${REGION}" \
        --network=default \
        --quiet
fi

if gcloud compute routers nats describe eval-nat --router=eval-router --region="${REGION}" &>/dev/null; then
    echo "    Cloud NAT eval-nat already exists"
else
    echo "    Creating Cloud NAT with static IP..."
    gcloud compute routers nats create eval-nat \
        --router=eval-router \
        --region="${REGION}" \
        --nat-external-ip-pool=eval-nat-ip \
        --nat-all-subnet-ip-ranges \
        --quiet
fi

# --- IAP Firewall Rule (for SSH without public IPs) ---
echo ""
echo ">>> IAP SSH firewall rule..."
if gcloud compute firewall-rules describe allow-ssh-iap &>/dev/null; then
    echo "    Firewall rule allow-ssh-iap already exists"
else
    echo "    Creating allow-ssh-iap..."
    gcloud compute firewall-rules create allow-ssh-iap \
        --source-ranges=35.235.240.0/20 \
        --allow=tcp:22 \
        --description="Allow SSH via IAP tunneling" \
        --quiet
fi

# --- Caller's public IP (for local CLI access to Cloud SQL) ---
echo ""
echo ">>> Detecting caller's public IP..."
MY_IP=$(curl -s --max-time 5 https://ifconfig.me || true)
if [ -z "$MY_IP" ]; then
    echo "    WARNING: Could not detect public IP, using NAT IP only"
    AUTHORIZED_NETWORKS="${NAT_IP}/32"
else
    echo "    Caller IP: ${MY_IP}"
    AUTHORIZED_NETWORKS="${NAT_IP}/32,${MY_IP}/32"
fi

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
        --authorized-networks="${AUTHORIZED_NETWORKS}" \
        --database-flags=\
idle_in_transaction_session_timeout=300000,\
tcp_keepalives_idle=60,\
tcp_keepalives_interval=10,\
tcp_keepalives_count=3,\
max_connections=100 \
        --quiet

    echo "    Instance created"
fi

# Keep authorized networks in sync (for existing instances)
echo ">>> Syncing authorized networks for ${DB_INSTANCE}..."
echo "    Authorized: ${AUTHORIZED_NETWORKS}"
gcloud sql instances patch "${DB_INSTANCE}" \
    --authorized-networks="${AUTHORIZED_NETWORKS}" \
    --quiet

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

# --- Build and Push Images ---
echo ""
echo ">>> Building worker Docker image (amd64)..."
cd "${PROJECT_ROOT}"
docker build --platform linux/amd64 -t eval-worker -f eval/Dockerfile .
docker tag eval-worker "${IMAGE}"

echo ">>> Pushing worker image to Artifact Registry..."
docker push "${IMAGE}"

# Build and push operator image
OPERATOR_IMAGE="${REGISTRY}/operator:latest"
echo ""
echo ">>> Building operator Docker image (amd64)..."
cd "${PROJECT_ROOT}"
docker build --platform linux/amd64 -t operator-eval -f subjects/tikv/Dockerfile.operator .
docker tag operator-eval "${OPERATOR_IMAGE}"

echo ">>> Pushing operator image to Artifact Registry..."
docker push "${OPERATOR_IMAGE}"

# Build and push tikv-chaos image (TiKV with chaos tools for cloud eval)
TIKV_CHAOS_IMAGE="${REGISTRY}/tikv-chaos:v8.5.5"
echo ""
echo ">>> Building tikv-chaos Docker image (amd64)..."
cd "${PROJECT_ROOT}/subjects/tikv"
docker build --platform linux/amd64 -t tikv-chaos:v8.5.5 -f Dockerfile.tikv-chaos .
docker tag tikv-chaos:v8.5.5 "${TIKV_CHAOS_IMAGE}"

echo ">>> Pushing tikv-chaos image to Artifact Registry..."
docker push "${TIKV_CHAOS_IMAGE}"

# Build and push YCSB load generator image
YCSB_IMAGE="${REGISTRY}/ycsb:latest"
echo ""
echo ">>> Building ycsb Docker image (amd64)..."
docker build --platform linux/amd64 -t ycsb -f Dockerfile.ycsb .
docker tag ycsb "${YCSB_IMAGE}"

echo ">>> Pushing ycsb image to Artifact Registry..."
docker push "${YCSB_IMAGE}"

# --- Instance Template ---
echo ""
echo ">>> Instance template..."

# Delete existing template if it exists (templates are immutable)
gcloud compute instance-templates delete eval-worker-template --quiet 2>/dev/null || true

# Create startup script
# Note: COS has a read-only /root, so docker-credential-gcr must write
# to a writable HOME directory. The Docker socket and credentials are
# mounted into the worker container so it can manage TiKV trial containers.
STARTUP_SCRIPT=$(cat <<STARTUP_EOF
#!/bin/bash
set -e

# Wait for Docker to be ready (Container-Optimized OS)
while ! docker info &>/dev/null; do sleep 1; done

# Configure Docker auth for Artifact Registry (COS has read-only /root)
export HOME=/tmp/docker-home
mkdir -p "\$HOME/.docker"
docker-credential-gcr configure-docker --registries=${REGION}-docker.pkg.dev

# Start Cloud SQL Proxy
docker run -d --name cloud-sql-proxy --restart=always --network=host \
    gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0 \
    --address 0.0.0.0 \
    ${CONNECTION_NAME}

# Wait for proxy to be ready
sleep 5

# Pull and run worker
# Note: SSH keys for trial VMs are generated inside the worker container
# and passed to each trial VM at creation time via --metadata=ssh-keys
docker pull ${IMAGE}
docker run -d --name eval-worker --restart=always --network=host \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "\$HOME/.docker:/root/.docker:ro" \
    -e EVAL_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}" \
    -e GOOGLE_CLOUD_PROJECT="${PROJECT}" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e CHATDB_CLOUD_SQL_IP="${CHATDB_CLOUD_SQL_IP}" \
    -e CHATDB_CLOUD_SQL_PASSWORD="${CHATDB_CLOUD_SQL_PASSWORD}" \
    -e CHATDB_APP_IMAGE="${CHATDB_APP_IMAGE}" \
    -e CHATDB_LOADGEN_IMAGE="${CHATDB_LOADGEN_IMAGE}" \
    ${IMAGE} \
    worker start --cloud=gcp --operator-image=${OPERATOR_IMAGE}
STARTUP_EOF
)

echo "    Creating template..."
gcloud compute instance-templates create eval-worker-template \
    --machine-type=e2-standard-4 \
    --image-family=cos-stable \
    --image-project=cos-cloud \
    --boot-disk-size=50GB \
    --scopes=cloud-platform \
    --no-address \
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
echo "Worker Image: ${IMAGE}"
echo "Operator Image: ${OPERATOR_IMAGE}"
echo "YCSB Image: ${YCSB_IMAGE}"
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
