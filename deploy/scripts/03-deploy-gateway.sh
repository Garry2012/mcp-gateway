#!/usr/bin/env bash
# Create or update the MCP Gateway container app.
#
# Create explicitly selected images; preserve pinned images for configuration updates.
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
APP_ERROR="$(mktemp)"
trap 'rm -f "$APP_ERROR"' EXIT
APP_EXISTS=false
if az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query name -o tsv > /dev/null 2> "$APP_ERROR"; then
  APP_EXISTS=true
  CONTAINER_COUNT="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'length(properties.template.containers)' -o tsv)"
  [ "$CONTAINER_COUNT" = 1 ] || die "Deployment requires exactly one container; review multi-container apps separately"
elif ! grep -q '(ResourceNotFound)' "$APP_ERROR"; then
  die "Cannot read the existing app; no changes applied"
fi
[ "$APP_EXISTS" = true ] || [ -n "$IMAGE_TAG$IMAGE_DIGEST" ] || die "Set IMAGE_DIGEST or IMAGE_TAG for the first deployment"
IMAGE="$(resolve_image)"
# Validate availability before changing secret references or the app template.
az acr repository show -n "$ACR_NAME" --image "${IMAGE_REPO}@${IMAGE##*@}" -o none \
  || die "Selected digest is unavailable in ACR"
ok "image $IMAGE"

if [ "$APP_EXISTS" = true ]; then
  CONTAINER_NAME="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'properties.template.containers[0].name' -o tsv)"
  [ -n "$CONTAINER_NAME" ] || die "Cannot identify the gateway container"
  APP_CPU="${APP_CPU:-$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'properties.template.containers[0].resources.cpu' -o tsv)}"
  APP_MEMORY="${APP_MEMORY:-$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'properties.template.containers[0].resources.memory' -o tsv)}"
  APP_MIN_REPLICAS="${APP_MIN_REPLICAS:-$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'properties.template.scale.minReplicas' -o tsv)}"
  APP_MAX_REPLICAS="${APP_MAX_REPLICAS:-$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --query 'properties.template.scale.maxReplicas' -o tsv)}"
else
  APP_CPU="${APP_CPU:-1.0}"
  APP_MEMORY="${APP_MEMORY:-2.0Gi}"
  APP_MIN_REPLICAS="${APP_MIN_REPLICAS:-1}"
  APP_MAX_REPLICAS="${APP_MAX_REPLICAS:-1}"
fi
[ -n "$APP_CPU" ] && [ -n "$APP_MEMORY" ] && [ -n "$APP_MIN_REPLICAS" ] && [ -n "$APP_MAX_REPLICAS" ] \
  || die "Set CPU, memory and replica settings explicitly when live values are missing"
RESOURCE_ARGS=(--cpu "$APP_CPU" --memory "$APP_MEMORY" --min-replicas "$APP_MIN_REPLICAS" --max-replicas "$APP_MAX_REPLICAS")
ok "target resources: CPU=$APP_CPU memory=$APP_MEMORY replicas=$APP_MIN_REPLICAS..$APP_MAX_REPLICAS"

REQUIRED_SECRETS=("$KV_JWT_SECRET" "$KV_ENC_SECRET" "$KV_DB_URL" "$KV_ADMIN_PASSWORD" "$KV_DEFAULT_USER_PASSWORD")
[ -n "${KV_OTEL_HEADERS:-}" ] && REQUIRED_SECRETS+=("$KV_OTEL_HEADERS")
for s in "${REQUIRED_SECRETS[@]}"; do
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
[ -n "${KV_OTEL_HEADERS:-}" ] && SECRET_REFS+=("otel-headers=keyvaultref:${KV_URI}/${KV_OTEL_HEADERS},identityref:${UAMI_ID}")

# APP_DOMAIN must be the gateway's own public URL. On a first deploy the FQDN
# does not exist yet, so it is set on the follow-up update below.
RESOLVED_APP_DOMAIN="$APP_DOMAIN"
if [ -z "$RESOLVED_APP_DOMAIN" ] && [ "$APP_EXISTS" = true ]; then
  EXISTING_FQDN="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)"
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
# Unset preserves the live setting. Explicit empty removes only this owned variable.
REMOVE_ENV_VARS=()
for setting in DCR_ALLOWED_ISSUERS OTEL_REDACT_FIELDS KV_OTEL_HEADERS; do
  if [ "${!setting+x}" = x ]; then
    target="$setting"
    value="${!setting}"
    if [ "$setting" = KV_OTEL_HEADERS ]; then
      target=OTEL_EXPORTER_OTLP_HEADERS
      [ -z "$value" ] || value=secretref:otel-headers
    fi
    if [ -n "$value" ]; then
      ENV_VARS+=("${target}=${value}")
    else
      REMOVE_ENV_VARS+=("$target")
    fi
  fi
done
REMOVE_ARGS=()
if [ "${#REMOVE_ENV_VARS[@]}" -gt 0 ]; then
  REMOVE_ARGS=(--remove-env-vars "${REMOVE_ENV_VARS[@]}")
fi

# Secret reference updates are application-scoped and do not create revisions themselves.
REVISION_SUFFIX="r$(date -u +%Y%m%d%H%M%S)-$RANDOM"
if [ "$APP_EXISTS" = true ]; then
  log "Updating existing app: $APP_NAME_AZ"
  az containerapp secret set -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" --secrets "${SECRET_REFS[@]}" -o none
  DEPLOYED_REVISION="$(az containerapp update -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --revision-suffix "$REVISION_SUFFIX" --container-name "$CONTAINER_NAME" --image "$IMAGE" "${RESOURCE_ARGS[@]}" \
    --set-env-vars "${ENV_VARS[@]}" ${REMOVE_ARGS[@]+"${REMOVE_ARGS[@]}"} --query properties.latestRevisionName -o tsv)"
  ok "updated to $IMAGE"
else
  log "Creating app: $APP_NAME_AZ"
  DEPLOYED_REVISION="$(az containerapp create \
    --revision-suffix "$REVISION_SUFFIX" \
    --name "$APP_NAME_AZ" --resource-group "$RESOURCE_GROUP" --environment "$CAE_NAME" \
    --image "$IMAGE" \
    --user-assigned "$UAMI_ID" \
    --registry-server "$REGISTRY" --registry-identity "$UAMI_ID" \
    --target-port "$APP_PORT" --ingress external --transport http \
    "${RESOURCE_ARGS[@]}" \
    --secrets "${SECRET_REFS[@]}" \
    --env-vars "${ENV_VARS[@]}" --query properties.latestRevisionName -o tsv)"
  ok "created"
fi

[ "$DEPLOYED_REVISION" = "${APP_NAME_AZ}--${REVISION_SUFFIX}" ] || die "Azure did not return the requested revision"

FQDN="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

# APP_DOMAIN drives OAuth redirect URIs and production CORS origins. A supplied
# value (for example a custom domain) is authoritative and was already applied
# above. Only when none was supplied does the app's own hostname fill it in - on a
# first deploy the FQDN did not exist when the env vars were assembled.
TARGET_APP_DOMAIN="${APP_DOMAIN:-https://${FQDN}}"
if [ "$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
      --query "properties.template.containers[0].env[?name=='APP_DOMAIN'].value | [0]" -o tsv 2>/dev/null)" != "$TARGET_APP_DOMAIN" ]; then
  REVISION_SUFFIX="${REVISION_SUFFIX}-domain"
  DEPLOYED_REVISION="$(az containerapp update -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
    --revision-suffix "$REVISION_SUFFIX" --set-env-vars "APP_DOMAIN=${TARGET_APP_DOMAIN}" \
    --query properties.latestRevisionName -o tsv)"
  [ "$DEPLOYED_REVISION" = "${APP_NAME_AZ}--${REVISION_SUFFIX}" ] || die "Azure did not return the requested domain revision"
  ok "APP_DOMAIN set to ${TARGET_APP_DOMAIN}"
fi

if [ -n "${DEPLOY_RESULT_FILE:-}" ]; then
  printf '%s\n' "$DEPLOYED_REVISION" > "$DEPLOY_RESULT_FILE"
fi

log "Deployed"
echo "  URL  : https://${FQDN}"
echo "  Admin: ${PLATFORM_ADMIN_EMAIL}"
echo "  Pass : az keyvault secret show --vault-name ${KEYVAULT_NAME} --name ${KV_ADMIN_PASSWORD} --query value -o tsv"
printf '  Verify: EXPECTED_REVISION=%s IMAGE_DIGEST=%s ./04-smoke.sh (unset IMAGE_TAG first)\n' "$DEPLOYED_REVISION" "${IMAGE##*@}"
