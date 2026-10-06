#!/usr/bin/env bash
# Source this from the other scripts. Centralizes Azure config for MCP Gateway.
#
# Every value is overridable from the environment, so a second environment or a
# per-tenant deployment is a matter of exporting different values rather than
# editing this file:
#
#   RESOURCE_GROUP=vcare-rc-rg APP_NAME_AZ=mcp-gateway-dev ./deploy.sh
#
# Or keep a target's overrides in a profile file and select it:
#
#   DEPLOY_PROFILE=profiles/healthcare-rg.env ./deploy.sh
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${DEPLOY_PROFILE:-}" ]; then
  case "$DEPLOY_PROFILE" in /*) PROFILE_PATH="$DEPLOY_PROFILE" ;; *) PROFILE_PATH="$SCRIPT_DIR/$DEPLOY_PROFILE" ;; esac
  [ -f "$PROFILE_PATH" ] || { echo "DEPLOY_PROFILE '$DEPLOY_PROFILE' not found" >&2; exit 1; }
  set -a
  # shellcheck disable=SC1090
  source "$PROFILE_PATH"
  set +a
fi

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-4e1c081a-9a6a-4e16-9da2-90217c22378b}"
RESOURCE_GROUP="${RESOURCE_GROUP:-vcare-rc-rg}"
LOCATION="${LOCATION:-centralindia}"

# Container registry and Container Apps environment (both pre-existing).
ACR_NAME="${ACR_NAME:-vcarercacr}"
REGISTRY="${ACR_NAME}.azurecr.io"
CAE_NAME="${CAE_NAME:-vcare-rc-cae}"

# Managed identity used for BOTH the ACR pull and the Key Vault reads, so no
# credential ever appears in a deploy command or in the app's configuration.
# 01-prepare-azure.sh creates it when missing and grants AcrPull on the registry
# plus Key Vault Secrets User on the gateway's own secrets only, so a shared
# vault does not expose other applications' secrets to the gateway.
UAMI_NAME="${UAMI_NAME:-vcare-rc-uami}"
KEYVAULT_NAME="${KEYVAULT_NAME:-vcare-rc-kv}"

# Postgres. The server name is a GLOBAL DNS label, so it must be unique across
# all of Azure - "mcp-gateway-db" was already taken by someone else.
PG_SERVER="${PG_SERVER:-vcare-mcpgw-db}"
PG_ADMIN_USER="${PG_ADMIN_USER:-mcpadmin}"
PG_DATABASE="${PG_DATABASE:-mcpgateway}"

# Shared Postgres server. When PG_SERVER already exists and belongs to other
# applications, the gateway gets its own login role and database on it instead
# of the server admin account. PG_ADMIN_URL_SECRET names a Key Vault secret that
# holds a connection URL for a role with CREATEROLE and CREATEDB; it is read only
# during 01-prepare-azure.sh and never reaches the container app. Never reset the
# server admin password of a shared server: other applications depend on it.
PG_ADMIN_URL_SECRET="${PG_ADMIN_URL_SECRET:-}"  # pragma: allowlist secret
PG_APP_USER="${PG_APP_USER:-mcpgateway_app}"
PG_SKU="${PG_SKU:-Standard_B1ms}"
PG_TIER="${PG_TIER:-Burstable}"
PG_STORAGE_GB="${PG_STORAGE_GB:-32}"
PG_VERSION="${PG_VERSION:-16}"

# Connection pool sizing MUST be matched to the server tier. config.py defaults
# to db_pool_size=200 + db_max_overflow=10, but a Burstable B1ms server allows
# max_connections=50 in total. Left at the default the app exhausts the server
# and every other client is refused with:
#   "remaining connection slots are reserved for roles with the SUPERUSER attribute"
# Budget ~20 for the app, leaving headroom for admin tools and health probes.
# Raise these in step with the tier (see docs: >50 req/s wants a larger SKU).
DB_POOL_SIZE="${DB_POOL_SIZE:-20}"
DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-5}"

# Gunicorn workers MUST be set explicitly. run-gunicorn.sh otherwise computes
# `nproc * 2 + 1` (capped at 16), and `nproc` inside a container reports the
# HOST's CPU count, not the cgroup limit set by --cpu. On a 1 CPU / 2Gi
# container that spawns up to 16 workers, each loading the full application,
# and the container OOMs in a crash loop:
#     Worker (pid:280) was sent SIGKILL! Perhaps out of memory?
# Keep roughly 2 workers per CPU, and raise APP_MEMORY before raising this.
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"

TOKEN_EXPIRY="${TOKEN_EXPIRY:-20}"
TOKEN_IDLE_TIMEOUT="${TOKEN_IDLE_TIMEOUT:-60}"

# --- Observability -----------------------------------------------------------
# Off by default in config.py. Enabling it writes traces/spans to Postgres
# (observability_traces / observability_spans) and needs no collector, no key,
# and no external service - the Admin UI reads them straight from the DB.
#
# Tracing is scoped by observability_include_paths, which is an ALLOWLIST
# (/rpc, /sse, /message, /mcp, /a2a). Page loads and static assets are never
# traced, so the extra DB load is proportional to tool calls, not to traffic.
# Each traced request opens several short-lived sessions of its own (issue
# #3883), so raise DB_POOL_SIZE with this if call volume grows.
OBSERVABILITY_ENABLED="${OBSERVABILITY_ENABLED:-true}"

# Payload capture applies to exported spans, not the built-in observability database.
# Tool output capture records successful results only.
OTEL_CAPTURE_INPUT_SPANS="${OTEL_CAPTURE_INPUT_SPANS:-tool.invoke}"
OTEL_CAPTURE_OUTPUT_SPANS="${OTEL_CAPTURE_OUTPUT_SPANS:-tool.invoke}"
OTEL_ENABLE_OBSERVABILITY="${OTEL_ENABLE_OBSERVABILITY:-false}"
OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}"
OTEL_EXPORTER_OTLP_INSECURE="${OTEL_EXPORTER_OTLP_INSECURE:-false}"
# Tool payload attributes use the langfuse.* namespace even with other OTLP backends.
OTEL_EMIT_LANGFUSE_ATTRIBUTES="${OTEL_EMIT_LANGFUSE_ATTRIBUTES:-true}"
OTEL_CAPTURE_IDENTITY_ATTRIBUTES="${OTEL_CAPTURE_IDENTITY_ATTRIBUTES:-false}"

# Container app.
APP_NAME_AZ="${APP_NAME_AZ:-mcp-gateway}"
IMAGE_REPO="${IMAGE_REPO:-mcp-gateway}"
# The tag MUST be unique per build. It was previously the fixed, mutable "v1",
# which made redeploys silently do nothing: `az containerapp update --image
# <repo>:v1` produces a template identical to the deployed one, and in Single
# revision mode Container Apps only rolls a new revision when the template
# changes. The build succeeded, the tag moved to the new digest, every script
# exited 0, and the old replica kept serving - with the smoke test passing
# against it, because those assertions only check the brand and cannot tell two
# post-rebrand builds apart.
# Defaulting to the commit SHA makes each deploy a distinct template, so a new
# revision always rolls and the running image is traceable to a commit.
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo latest)}"
IMAGE="${REGISTRY}/${IMAGE_REPO}:${IMAGE_TAG}"
APP_PORT="${APP_PORT:-4444}"
APP_CPU="${APP_CPU:-1.0}"
APP_MEMORY="${APP_MEMORY:-2.0Gi}"
APP_MIN_REPLICAS="${APP_MIN_REPLICAS:-1}"
APP_MAX_REPLICAS="${APP_MAX_REPLICAS:-1}"

PLATFORM_ADMIN_EMAIL="${PLATFORM_ADMIN_EMAIL:-admin@intimetec.com}"

# Admin UI and admin API. Set both to false for a headless deployment, where
# consuming platforms use only the REST, MCP and A2A endpoints.
MCPGATEWAY_UI_ENABLED="${MCPGATEWAY_UI_ENABLED:-true}"
MCPGATEWAY_ADMIN_API_ENABLED="${MCPGATEWAY_ADMIN_API_ENABLED:-true}"

# HTTP header passthrough (off by default in config.py). When on, each gateway
# registration's passthrough_headers allowlist decides which client headers reach
# that MCP server. Upstream servers that read trusted context from headers (for
# example the front-desk healthcare server's X-Call-Id / X-Turn-Context) need it.
ENABLE_HEADER_PASSTHROUGH="${ENABLE_HEADER_PASSTHROUGH:-false}"

# --- OAuth / Dynamic Client Registration ------------------------------------
# APP_DOMAIN is the gateway's own public URL. It defaults to
# http://localhost:4444 in config.py, and OAuth callback URLs and production
# CORS origins are both derived from it - so leaving it unset on a deployed
# instance makes the gateway hand out localhost redirect URIs.
# Resolved from the live app when not supplied.
APP_DOMAIN="${APP_DOMAIN:-}"

# Upstream MCP servers the gateway may dynamically register itself with.
# DCR_ALLOWED_ISSUERS is a JSON list of issuer URLs. When set, an issuer absent
# from it is refused. When empty, the variable is not passed and config.py's
# default applies (empty list = allow any issuer). Keep this OUT of a local
# .env - it makes tests in tests/unit/mcpgateway/services/test_dcr_service.py
# fail, because they use https://as.example.com as a fixture issuer.
DCR_ENABLED="${DCR_ENABLED:-true}"
DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS="${DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS:-true}"  # pragma: allowlist secret
DCR_ALLOWED_ISSUERS="${DCR_ALLOWED_ISSUERS:-}"
DCR_TOKEN_ENDPOINT_AUTH_METHOD="${DCR_TOKEN_ENDPOINT_AUTH_METHOD:-client_secret_post}"

# Key Vault secret names. Values are never stored in this repo.
KV_JWT_SECRET="${KV_JWT_SECRET:-mcpgw-jwt-secret}"  # pragma: allowlist secret
KV_ENC_SECRET="${KV_ENC_SECRET:-mcpgw-auth-encryption-secret}"  # pragma: allowlist secret
KV_DB_URL="${KV_DB_URL:-mcpgw-database-url}"
KV_ADMIN_PASSWORD="${KV_ADMIN_PASSWORD:-mcpgw-platform-admin-password}"  # pragma: allowlist secret
KV_DEFAULT_USER_PASSWORD="${KV_DEFAULT_USER_PASSWORD:-mcpgw-default-user-password}"  # pragma: allowlist secret

# --- Base images -------------------------------------------------------------
# MUST be passed explicitly to `az acr build`. The Containerfile declares
# `FROM ${WHEELS_REF}` where `WHEELS_REF` itself defaults to `${UBI_MINIMAL}`,
# and ACR's dependency scanner cannot resolve that nesting - it fails with
# "Failed to parse image reference: ${UBI_MINIMAL}:latest" before the build
# starts. Passing them flattens the reference.
# Defaults are read from the Containerfile's ARG lines, so upstream base-image
# bumps apply on the next sync without editing this file.
containerfile_arg() { sed -n "s/^ARG $1=//p" "$ROOT_DIR/Containerfile" | head -1; }
UBI_BASE="${UBI_BASE:-$(containerfile_arg UBI_BASE)}"
NODEJS_IMAGE="${NODEJS_IMAGE:-$(containerfile_arg NODEJS_IMAGE)}"
UBI_MINIMAL="${UBI_MINIMAL:-$(containerfile_arg UBI_MINIMAL)}"
WHEELS_REF="${WHEELS_REF:-$UBI_MINIMAL}"

# Derived
KV_URI="https://${KEYVAULT_NAME}.vault.azure.net/secrets"
PG_FQDN="${PG_SERVER}.postgres.database.azure.com"

UAMI_ID="$(az identity show -n "$UAMI_NAME" -g "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || true)"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[0;32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[0;33mWARN\033[0m %s\n' "$*"; }
die()  { printf '  \033[0;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
