#!/usr/bin/env bash
# Source this from the other scripts. Centralizes Azure config for MCP Gateway.
#
# Every value is overridable from the environment, so a second environment or a
# per-tenant deployment is a matter of exporting different values rather than
# editing this file:
#
#   RESOURCE_GROUP=vcare-rc-rg APP_NAME_AZ=mcp-gateway-dev ./deploy.sh
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-4e1c081a-9a6a-4e16-9da2-90217c22378b}"
RESOURCE_GROUP="${RESOURCE_GROUP:-vcare-rc-rg}"
LOCATION="${LOCATION:-centralindia}"

# Container registry and Container Apps environment (both pre-existing).
ACR_NAME="${ACR_NAME:-vcarercacr}"
REGISTRY="${ACR_NAME}.azurecr.io"
CAE_NAME="${CAE_NAME:-vcare-rc-cae}"

# Managed identity used for BOTH the ACR pull and the Key Vault reads, so no
# credential ever appears in a deploy command or in the app's configuration.
UAMI_NAME="${UAMI_NAME:-vcare-rc-uami}"
KEYVAULT_NAME="${KEYVAULT_NAME:-vcare-rc-kv}"

# Postgres. The server name is a GLOBAL DNS label, so it must be unique across
# all of Azure - "mcp-gateway-db" was already taken by someone else.
PG_SERVER="${PG_SERVER:-vcare-mcpgw-db}"
PG_ADMIN_USER="${PG_ADMIN_USER:-mcpadmin}"
PG_DATABASE="${PG_DATABASE:-mcpgateway}"
PG_SKU="${PG_SKU:-Standard_B1ms}"
PG_TIER="${PG_TIER:-Burstable}"
PG_STORAGE_GB="${PG_STORAGE_GB:-32}"
PG_VERSION="${PG_VERSION:-16}"

# Container app.
APP_NAME_AZ="${APP_NAME_AZ:-mcp-gateway}"
IMAGE_REPO="${IMAGE_REPO:-mcp-gateway}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
IMAGE="${REGISTRY}/${IMAGE_REPO}:${IMAGE_TAG}"
APP_PORT="${APP_PORT:-4444}"
APP_CPU="${APP_CPU:-1.0}"
APP_MEMORY="${APP_MEMORY:-2.0Gi}"
APP_MIN_REPLICAS="${APP_MIN_REPLICAS:-1}"
APP_MAX_REPLICAS="${APP_MAX_REPLICAS:-1}"

# Product identity (see FORK-CUSTOMIZATIONS.md).
BRAND_NAME="${BRAND_NAME:-MCP Gateway}"
PLATFORM_ADMIN_EMAIL="${PLATFORM_ADMIN_EMAIL:-admin@intimetec.com}"

# Key Vault secret names. Values are never stored in this repo.
KV_JWT_SECRET="${KV_JWT_SECRET:-mcpgw-jwt-secret}"
KV_ENC_SECRET="${KV_ENC_SECRET:-mcpgw-auth-encryption-secret}"
KV_DB_URL="${KV_DB_URL:-mcpgw-database-url}"
KV_ADMIN_PASSWORD="${KV_ADMIN_PASSWORD:-mcpgw-platform-admin-password}"

# --- Base images -------------------------------------------------------------
# MUST be passed explicitly to `az acr build`. The Containerfile declares
# `FROM ${WHEELS_REF}` where `WHEELS_REF` itself defaults to `${UBI_MINIMAL}`,
# and ACR's dependency scanner cannot resolve that nesting - it fails with
# "Failed to parse image reference: ${UBI_MINIMAL}:latest" before the build
# starts. Passing them flattens the reference.
UBI_BASE="${UBI_BASE:-registry.access.redhat.com/ubi10:10.2-1784668814}"
NODEJS_IMAGE="${NODEJS_IMAGE:-registry.access.redhat.com/ubi10/nodejs-24:10.2-1784784528}"
UBI_MINIMAL="${UBI_MINIMAL:-registry.access.redhat.com/ubi10/ubi-minimal:10.2-1784669047}"
WHEELS_REF="${WHEELS_REF:-$UBI_MINIMAL}"

# Derived
KV_URI="https://${KEYVAULT_NAME}.vault.azure.net/secrets"
PG_FQDN="${PG_SERVER}.postgres.database.azure.com"

UAMI_ID="$(az identity show -n "$UAMI_NAME" -g "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || true)"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[0;32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[0;33mWARN\033[0m %s\n' "$*"; }
die()  { printf '  \033[0;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
