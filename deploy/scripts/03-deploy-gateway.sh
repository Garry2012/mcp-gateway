#!/usr/bin/env bash
# Create or update the MCP Gateway container app.
#
# Idempotent: creates on first run, updates the image on subsequent runs.
#
# No credential appears anywhere in this script. The managed identity
# (UAMI_NAME) is used for BOTH pulling from ACR and reading Key Vault, and the
# secrets are wired as keyvaultref so their values never enter the container
# app's configuration, the CLI history, or CI logs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/00-config.sh"

log "Preflight"
case "$OTEL_ENABLE_OBSERVABILITY" in
  true)
    [ -n "$OTEL_EXPORTER_OTLP_ENDPOINT" ] || die "OTEL_EXPORTER_OTLP_ENDPOINT is required when tracing is enabled"
    case "$OTEL_EXPORTER_OTLP_PROTOCOL" in
      grpc|http) ;;
      *) die "OTEL_EXPORTER_OTLP_PROTOCOL must be grpc or http" ;;
    esac
    ;;
  false) ;;
  *) die "OTEL_ENABLE_OBSERVABILITY must be true or false" ;;
esac
az account show -o none 2>/dev/null || die "not logged in - run 'az login'"
[ -n "$UAMI_ID" ] || die "managed identity '$UAMI_NAME' not found"
az acr repository show-tags -n "$ACR_NAME" --repository "$IMAGE_REPO" -o tsv 2>/dev/null \
  | grep -qx "$IMAGE_TAG" || die "image $IMAGE not in registry - run ./02-build-images.sh first"
ok "image $IMAGE"

for s in "$KV_JWT_SECRET" "$KV_ENC_SECRET" "$KV_DB_URL" "$KV_ADMIN_PASSWORD" "$KV_DEFAULT_USER_PASSWORD"; do
  az keyvault secret show --vault-name "$KEYVAULT_NAME" --name "$s" -o none 2>/dev/null \
    || die "Key Vault secret '$s' missing - run ./01-prepare-azure.sh first"
done
ok "Key Vault secrets present"

SECRET_REFS=(
  "jwt-secret=keyvaultref:${KV_URI}/${KV_JWT_SECRET},identityref:${UAMI_ID}"
  "enc-secret=keyvaultref:${KV_URI}/${KV_ENC_SECRET},identityref:${UAMI_ID}"
  "db-url=keyvaultref:${KV_URI}/${KV_DB_URL},identityref:${UAMI_ID}"
  "admin-password=keyvaultref:${KV_URI}/${KV_ADMIN_PASSWORD},identityref:${UAMI_ID}"
  "default-user-password=keyvaultref:${KV_URI}/${KV_DEFAULT_USER_PASSWORD},identityref:${UAMI_ID}"
)

# APP_DOMAIN must be the gateway's own public URL. On a first deploy the FQDN
# does not exist yet, so it is set on the follow-up update below.
RESOLVED_APP_DOMAIN="$APP_DOMAIN"
if [ -z "$RESOLVED_APP_DOMAIN" ]; then
  EXISTING_FQDN="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
  [ -n "$EXISTING_FQDN" ] && RESOLVED_APP_DOMAIN="https://${EXISTING_FQDN}"
fi

ENV_VARS=(
  "JWT_SECRET_KEY=secretref:jwt-secret"  # pragma: allowlist secret
  "AUTH_ENCRYPTION_SECRET=secretref:enc-secret"  # pragma: allowlist secret
  "DATABASE_URL=secretref:db-url"  # pragma: allowlist secret
  "PLATFORM_ADMIN_PASSWORD=secretref:admin-password"  # pragma: allowlist secret
  "DEFAULT_USER_PASSWORD=secretref:default-user-password"  # pragma: allowlist secret
  "PLATFORM_ADMIN_EMAIL=${PLATFORM_ADMIN_EMAIL}"
  "HOST=0.0.0.0"
  "PORT=${APP_PORT}"
  "ENVIRONMENT=production"
  "MCPGATEWAY_UI_ENABLED=${MCPGATEWAY_UI_ENABLED}"
  "MCPGATEWAY_ADMIN_API_ENABLED=${MCPGATEWAY_ADMIN_API_ENABLED}"
  "ENABLE_HEADER_PASSTHROUGH=${ENABLE_HEADER_PASSTHROUGH}"
  "DCR_ENABLED=${DCR_ENABLED}"
  "DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=${DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS}"
  "DCR_TOKEN_ENDPOINT_AUTH_METHOD=${DCR_TOKEN_ENDPOINT_AUTH_METHOD}"
  "DB_POOL_SIZE=${DB_POOL_SIZE}"
  "DB_MAX_OVERFLOW=${DB_MAX_OVERFLOW}"
  "GUNICORN_WORKERS=${GUNICORN_WORKERS}"
  "TOKEN_EXPIRY=${TOKEN_EXPIRY}"
  "TOKEN_IDLE_TIMEOUT=${TOKEN_IDLE_TIMEOUT}"
  "MCP_CLIENT_CONNECT_MODE=${MCP_CLIENT_CONNECT_MODE}"
  "MCP_INBOUND_PROTOCOL_MODE=${MCP_INBOUND_PROTOCOL_MODE}"
  "OBSERVABILITY_ENABLED=${OBSERVABILITY_ENABLED}"
  "OTEL_ENABLE_OBSERVABILITY=${OTEL_ENABLE_OBSERVABILITY}"
  "OTEL_HTTPX_INSTRUMENTATION_ENABLED=${OTEL_HTTPX_INSTRUMENTATION_ENABLED}"
  "OTEL_TRACES_EXPORTER=otlp"
  "OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}"
  "OTEL_EXPORTER_OTLP_PROTOCOL=${OTEL_EXPORTER_OTLP_PROTOCOL}"
  "OTEL_EXPORTER_OTLP_INSECURE=${OTEL_EXPORTER_OTLP_INSECURE}"
  "OTEL_EMIT_LANGFUSE_ATTRIBUTES=${OTEL_EMIT_LANGFUSE_ATTRIBUTES}"
  "OTEL_CAPTURE_IDENTITY_ATTRIBUTES=${OTEL_CAPTURE_IDENTITY_ATTRIBUTES}"
  "OTEL_CAPTURE_INPUT_SPANS=${OTEL_CAPTURE_INPUT_SPANS}"
  "OTEL_CAPTURE_OUTPUT_SPANS=${OTEL_CAPTURE_OUTPUT_SPANS}"
)
[ -n "$RESOLVED_APP_DOMAIN" ] && ENV_VARS+=("APP_DOMAIN=${RESOLVED_APP_DOMAIN}")
[ -n "$DCR_ALLOWED_ISSUERS" ] && ENV_VARS+=("DCR_ALLOWED_ISSUERS=${DCR_ALLOWED_ISSUERS}")
[ -n "${OTEL_REDACT_FIELDS:-}" ] && ENV_VARS+=("OTEL_REDACT_FIELDS=${OTEL_REDACT_FIELDS}")

if az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  log "Updating existing app: $APP_NAME_AZ"
  az containerapp secret set -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --secrets "${SECRET_REFS[@]}" -o none
  az containerapp update -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --image "$IMAGE" --set-env-vars "${ENV_VARS[@]}" -o none
  ok "updated to $IMAGE_TAG"
else
  log "Creating app: $APP_NAME_AZ"
  az containerapp create \
    --name "$APP_NAME_AZ" --resource-group "$RESOURCE_GROUP" --environment "$CAE_NAME" \
    --image "$IMAGE" \
    --user-assigned "$UAMI_ID" \
    --registry-server "$REGISTRY" --registry-identity "$UAMI_ID" \
    --target-port "$APP_PORT" --ingress external --transport http \
    --min-replicas "$APP_MIN_REPLICAS" --max-replicas "$APP_MAX_REPLICAS" \
    --cpu "$APP_CPU" --memory "$APP_MEMORY" \
    --secrets "${SECRET_REFS[@]}" \
    --env-vars "${ENV_VARS[@]}" -o none
  ok "created"
fi

FQDN="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

# APP_DOMAIN drives OAuth redirect URIs and production CORS origins. A supplied
# value (for example a custom domain) is authoritative and was already applied
# above. Only when none was supplied does the app's own hostname fill it in - on a
# first deploy the FQDN did not exist when the env vars were assembled.
TARGET_APP_DOMAIN="${APP_DOMAIN:-https://${FQDN}}"
if [ "$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
      --query "properties.template.containers[0].env[?name=='APP_DOMAIN'].value | [0]" -o tsv 2>/dev/null)" != "$TARGET_APP_DOMAIN" ]; then
  az containerapp update -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --set-env-vars "APP_DOMAIN=${TARGET_APP_DOMAIN}" -o none
  ok "APP_DOMAIN set to ${TARGET_APP_DOMAIN}"
fi

log "Deployed"
echo "  URL  : https://${FQDN}"
echo "  Admin: ${PLATFORM_ADMIN_EMAIL}"
echo "  Pass : az keyvault secret show --vault-name ${KEYVAULT_NAME} --name ${KV_ADMIN_PASSWORD} --query value -o tsv"
echo "  Next : ./04-smoke.sh"
