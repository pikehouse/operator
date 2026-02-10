#!/usr/bin/env bash
#
# GCP Setup Script for Chat DB App
#
# Provisions:
#   - Cloud SQL for PostgreSQL instance
#   - Artifact Registry repository
#   - Builds and pushes app + loadgen Docker images
#
# Prerequisites:
#   - gcloud CLI authenticated with appropriate permissions
#   - Docker installed and running
#   - APIs enabled: sqladmin.googleapis.com, artifactregistry.googleapis.com
#
# Usage:
#   ./scripts/gcp-setup.sh
#
# Environment variables (optional overrides):
#   GCP_PROJECT            - GCP project ID (default: from gcloud config)
#   GCP_REGION             - GCP region (default: us-central1)
#   CLOUD_SQL_INSTANCE     - Cloud SQL instance name
#   CLOUD_SQL_PASSWORD     - Cloud SQL chatapp user password
#   AR_REPO                - Artifact Registry repository name

set -euo pipefail

# ---------- Configuration ----------

GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
GCP_REGION="${GCP_REGION:-us-central1}"

CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-chatdb-eval}"
CLOUD_SQL_PASSWORD="${CLOUD_SQL_PASSWORD:-chatdb-$(openssl rand -hex 8)}"

AR_REPO="${AR_REPO:-chat-db-app}"
AR_LOCATION="${GCP_REGION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/../service"
REPO_ROOT="${SCRIPT_DIR}/../../.."

echo "=== Chat DB App GCP Setup ==="
echo "Project:   ${GCP_PROJECT}"
echo "Region:    ${GCP_REGION}"
echo "Instance:  ${CLOUD_SQL_INSTANCE}"
echo ""

# ---------- Enable APIs ----------

echo "--- Enabling APIs ---"
gcloud services enable \
    sqladmin.googleapis.com \
    artifactregistry.googleapis.com \
    --project="${GCP_PROJECT}" \
    --quiet

# ---------- Authorized Networks ----------

echo ""
echo "--- Resolving authorized networks ---"

# Get NAT IP from root .env or query GCP
ROOT_ENV="${REPO_ROOT}/.env"
NAT_IP=""
if [ -f "${ROOT_ENV}" ]; then
    NAT_IP=$(grep "^GCP_NAT_IP=" "${ROOT_ENV}" 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true)
fi
if [ -z "$NAT_IP" ]; then
    NAT_IP=$(gcloud compute addresses describe eval-nat-ip \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT}" \
        --format='value(address)' 2>/dev/null || true)
fi
if [ -z "$NAT_IP" ]; then
    echo "WARNING: Could not find NAT IP. Run eval/scripts/gcp-setup.sh first."
    echo "Falling back to 0.0.0.0/0 (open to all)."
    AUTHORIZED_NETWORKS="0.0.0.0/0"
else
    MY_IP=$(curl -s --max-time 5 https://ifconfig.me || true)
    if [ -z "$MY_IP" ]; then
        echo "WARNING: Could not detect public IP, using NAT IP only"
        AUTHORIZED_NETWORKS="${NAT_IP}/32"
    else
        echo "NAT IP: ${NAT_IP}, Caller IP: ${MY_IP}"
        AUTHORIZED_NETWORKS="${NAT_IP}/32,${MY_IP}/32"
    fi
fi

# ---------- Cloud SQL Instance ----------

echo ""
echo "--- Creating Cloud SQL Instance ---"
if gcloud sql instances describe "${CLOUD_SQL_INSTANCE}" \
    --project="${GCP_PROJECT}" &>/dev/null; then
    echo "Instance '${CLOUD_SQL_INSTANCE}' already exists, skipping creation."
else
    gcloud sql instances create "${CLOUD_SQL_INSTANCE}" \
        --database-version=POSTGRES_16 \
        --edition=ENTERPRISE \
        --tier=db-f1-micro \
        --region="${GCP_REGION}" \
        --root-password="${CLOUD_SQL_PASSWORD}" \
        --authorized-networks="${AUTHORIZED_NETWORKS}" \
        --project="${GCP_PROJECT}" \
        --quiet
    echo "Instance '${CLOUD_SQL_INSTANCE}' created."
fi

# Keep authorized networks in sync (for existing instances)
echo "Syncing authorized networks for ${CLOUD_SQL_INSTANCE}..."
echo "  Authorized: ${AUTHORIZED_NETWORKS}"
gcloud sql instances patch "${CLOUD_SQL_INSTANCE}" \
    --authorized-networks="${AUTHORIZED_NETWORKS}" \
    --project="${GCP_PROJECT}" \
    --quiet

# Get Cloud SQL IP
CLOUD_SQL_IP=$(gcloud sql instances describe "${CLOUD_SQL_INSTANCE}" \
    --project="${GCP_PROJECT}" \
    --format="value(ipAddresses[0].ipAddress)")

echo "Cloud SQL IP: ${CLOUD_SQL_IP}"

# ---------- Create Database and User ----------

echo ""
echo "--- Creating Database and User ---"
# Create chatapp user (idempotent - fails silently if exists)
gcloud sql users create chatapp \
    --instance="${CLOUD_SQL_INSTANCE}" \
    --password="${CLOUD_SQL_PASSWORD}" \
    --project="${GCP_PROJECT}" \
    --quiet 2>/dev/null || echo "User 'chatapp' already exists."

# Create chatdb database (idempotent)
gcloud sql databases create chatdb \
    --instance="${CLOUD_SQL_INSTANCE}" \
    --project="${GCP_PROJECT}" \
    --quiet 2>/dev/null || echo "Database 'chatdb' already exists."

# ---------- Artifact Registry ----------

echo ""
echo "--- Creating Artifact Registry Repository ---"
if gcloud artifacts repositories describe "${AR_REPO}" \
    --location="${AR_LOCATION}" \
    --project="${GCP_PROJECT}" &>/dev/null; then
    echo "Repository '${AR_REPO}' already exists, skipping creation."
else
    gcloud artifacts repositories create "${AR_REPO}" \
        --repository-format=docker \
        --location="${AR_LOCATION}" \
        --project="${GCP_PROJECT}" \
        --quiet
    echo "Repository '${AR_REPO}' created."
fi

# Configure Docker authentication
gcloud auth configure-docker "${AR_LOCATION}-docker.pkg.dev" --quiet

AR_PREFIX="${AR_LOCATION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}"

# ---------- Build and Push Images ----------

echo ""
echo "--- Building and Pushing Docker Images ---"

# App image
echo "Building chat-db-app image..."
docker build \
    --platform linux/amd64 \
    -t "${AR_PREFIX}/chat-db-app:latest" \
    "${SERVICE_DIR}/app"

echo "Pushing chat-db-app image..."
docker push "${AR_PREFIX}/chat-db-app:latest"

# Loadgen image
echo "Building loadgen image..."
docker build \
    --platform linux/amd64 \
    -t "${AR_PREFIX}/loadgen:latest" \
    "${SERVICE_DIR}/loadgen"

echo "Pushing loadgen image..."
docker push "${AR_PREFIX}/loadgen:latest"

# ---------- Save Configuration ----------

# Write to subject-local .env.gcp
ENV_FILE="${SCRIPT_DIR}/../.env.gcp"
cat > "${ENV_FILE}" <<EOF
# GCP Configuration for Chat DB App
# Generated by gcp-setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")

GCP_PROJECT=${GCP_PROJECT}
GCP_REGION=${GCP_REGION}

# Cloud SQL
CLOUD_SQL_INSTANCE=${CLOUD_SQL_INSTANCE}
CHATDB_CLOUD_SQL_IP=${CLOUD_SQL_IP}
CHATDB_CLOUD_SQL_PASSWORD=${CLOUD_SQL_PASSWORD}
CHATDB_DATABASE_URL=postgresql://chatapp:${CLOUD_SQL_PASSWORD}@${CLOUD_SQL_IP}:5432/chatdb

# Artifact Registry
AR_PREFIX=${AR_PREFIX}
CHATDB_APP_IMAGE=${AR_PREFIX}/chat-db-app:latest
CHATDB_LOADGEN_IMAGE=${AR_PREFIX}/loadgen:latest
EOF

# Append to project root .env (create if needed)
ROOT_ENV="${REPO_ROOT}/.env"
{
    echo ""
    echo "# Chat DB App (GCP) — generated by gcp-setup.sh $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "CHATDB_CLOUD_SQL_IP=${CLOUD_SQL_IP}"
    echo "CHATDB_CLOUD_SQL_PASSWORD=${CLOUD_SQL_PASSWORD}"
    echo "CHATDB_DATABASE_URL=postgresql://chatapp:${CLOUD_SQL_PASSWORD}@${CLOUD_SQL_IP}:5432/chatdb"
    echo "CHATDB_APP_IMAGE=${AR_PREFIX}/chat-db-app:latest"
    echo "CHATDB_LOADGEN_IMAGE=${AR_PREFIX}/loadgen:latest"
} >> "${ROOT_ENV}"

echo ""
echo "=== Setup Complete ==="
echo "Configuration saved to: ${ENV_FILE}"
echo "Configuration appended to: ${ROOT_ENV}"
echo ""
echo "Cloud SQL IP: ${CLOUD_SQL_IP}"
echo "App image:    ${AR_PREFIX}/chat-db-app:latest"
echo "Loadgen:      ${AR_PREFIX}/loadgen:latest"
echo ""
echo "Per-trial database creation (at eval runtime):"
echo "  CREATE DATABASE chatdb_trial_{instance_id};"
echo "  DROP DATABASE chatdb_trial_{instance_id};"
