#!/usr/bin/env bash
# Create the infrastructure MCP Gateway needs: its managed identity, Postgres
# database and login, firewall rule, Key Vault secrets and role assignments.
#
# Idempotent. Every step checks before it creates, so re-running is safe and
# leaves existing resources untouched.
#
# Assumes these already exist and does NOT create them:
#   - the resource group
#   - the container registry     (ACR_NAME)
#   - the Container Apps env     (CAE_NAME)
#   - the Key Vault              (KEYVAULT_NAME, RBAC authorization mode)
#
# Postgres has two modes:
#   - PG_SERVER missing: create a dedicated server and use its admin login.
#   - PG_SERVER exists and PG_ADMIN_URL_SECRET is set: shared server. Create a
#     dedicated login role and database for the gateway. The role's connection
#     limit caps the gateway's share of the server's max_connections.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/00-config.sh"

PSYCOPG_SPEC="psycopg[binary]==3.2.10"
PG_APP_CONNECTION_LIMIT="${PG_APP_CONNECTION_LIMIT:-$(( GUNICORN_WORKERS * (DB_POOL_SIZE + DB_MAX_OVERFLOW) + 3 ))}"
GATEWAY_SECRETS=("$KV_JWT_SECRET" "$KV_ENC_SECRET" "$KV_DB_URL" "$KV_ADMIN_PASSWORD" "$KV_DEFAULT_USER_PASSWORD")

random_secret() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }
random_alnum() { python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print('Mg'+''.join(secrets.choice(a) for _ in range($1)))"; }

log "Preflight"
az account show -o none 2>/dev/null || die "not logged in - run 'az login'"
az keyvault show -n "$KEYVAULT_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null || die "Key Vault '$KEYVAULT_NAME' not found in $RESOURCE_GROUP"
az acr show -n "$ACR_NAME" -o none 2>/dev/null || die "registry '$ACR_NAME' not found"
ok "subscription $(az account show --query name -o tsv)"
KV_ID="$(az keyvault show -n "$KEYVAULT_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"
ACR_ID="$(az acr show -n "$ACR_NAME" --query id -o tsv)"

log "Managed identity: $UAMI_NAME"
if [ -n "$UAMI_ID" ]; then
  ok "already exists"
else
  az identity create -n "$UAMI_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" -o none
  UAMI_ID="$(az identity show -n "$UAMI_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"
  ok "created"
fi
UAMI_PRINCIPAL="$(az identity show -n "$UAMI_NAME" -g "$RESOURCE_GROUP" --query principalId -o tsv)"

# The caller needs Key Vault data-plane access to WRITE secrets. Being
# subscription Owner is not sufficient - Owner grants control-plane rights only.
log "Key Vault write access"
CALLER="$(az account show --query user.name -o tsv)"
if az role assignment list --assignee "$CALLER" --scope "$KV_ID" \
     --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)" -o tsv 2>/dev/null | grep -q '^[1-9]'; then
  ok "$CALLER already has Key Vault Secrets Officer"
else
  warn "granting Key Vault Secrets Officer to $CALLER (scoped to this vault only)"
  az role assignment create --assignee "$CALLER" --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none
  sleep 20   # RBAC propagation
  ok "granted"
fi

# Prints "present" or "missing". Only a confirmed SecretNotFound counts as missing:
# any other read failure aborts, so a transient error can never regenerate an
# existing secret (a new encryption secret would make stored credentials unreadable).
kv_state() {
  local err
  if err="$(az keyvault secret show --vault-name "$KEYVAULT_NAME" --name "$1" -o none 2>&1)"; then
    echo present
  elif printf '%s' "$err" | grep -q "SecretNotFound"; then
    echo missing
  else
    die "cannot read Key Vault secret '$1' (not a SecretNotFound error): $err"
  fi
}
kv_has() {
  local state
  state="$(kv_state "$1")" || exit 1
  [ "$state" = present ]
}
# Create a secret from a generator command only when it is confirmed missing.
ensure_secret() {
  local name="$1"; shift
  if kv_has "$name"; then ok "$name (exists)"; else kv_set "$name" "$("$@")"; fi
}
kv_set() {
  az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "$1" --value "$2" -o none \
    || die "could not write secret '$1' - check Key Vault permissions"
  ok "$1"
}

ensure_azure_services_firewall() {
  log "Firewall: allow Azure services"
  if az postgres flexible-server firewall-rule list -g "$RESOURCE_GROUP" -n "$PG_SERVER" \
       --query "[?startIpAddress=='0.0.0.0' && endIpAddress=='0.0.0.0'] | length(@)" -o tsv 2>/dev/null | grep -q '^[1-9]'; then
    ok "an Azure-services rule already exists"
  else
    # 0.0.0.0-0.0.0.0 is Azure's sentinel for "allow Azure-internal services",
    # not "allow the whole internet".
    az postgres flexible-server firewall-rule create -g "$RESOURCE_GROUP" -n "$PG_SERVER" \
      --rule-name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
    ok "created"
  fi
}

# Create or update the gateway's login role and database on a shared server.
# Pass a password to create the role or rotate its password; pass "" to keep the
# existing password. Credentials travel through environment variables, never the
# command line.
provision_shared_database() {
  command -v uv >/dev/null || die "uv is required to run the database provisioning step"
  PG_ADMIN_URL="$(az keyvault secret show --vault-name "$KEYVAULT_NAME" --name "$PG_ADMIN_URL_SECRET" --query value -o tsv 2>/dev/null)" \
    || die "cannot read Key Vault secret '$PG_ADMIN_URL_SECRET'"
  PG_ADMIN_URL="$PG_ADMIN_URL" PG_APP_USER="$PG_APP_USER" PG_APP_PASSWORD="$1" \
  PG_DATABASE="$PG_DATABASE" PG_APP_CONNECTION_LIMIT="$PG_APP_CONNECTION_LIMIT" \
  uv run --quiet --no-project --with "$PSYCOPG_SPEC" python "$SCRIPT_DIR/provision_shared_db.py" \
    || die "database provisioning refused or failed - nothing after the reported step was changed"
}

log "Postgres: $PG_SERVER"
if az postgres flexible-server show -n "$PG_SERVER" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  if [ -n "$PG_ADMIN_URL_SECRET" ]; then
    ok "shared server - gateway uses its own role '$PG_APP_USER' and database '$PG_DATABASE'"
    ensure_azure_services_firewall
    log "Database and login role"
    if kv_has "$KV_DB_URL"; then
      provision_shared_database ""
      ok "$KV_DB_URL (exists)"
    else
      APP_PASSWORD="$(random_alnum 30)"  # pragma: allowlist secret
      provision_shared_database "$APP_PASSWORD"
      kv_set "$KV_DB_URL" "postgresql+psycopg://${PG_APP_USER}:${APP_PASSWORD}@${PG_FQDN}:5432/${PG_DATABASE}?sslmode=require"
    fi
  elif kv_has "$KV_DB_URL"; then
    ok "already exists, $KV_DB_URL present"
  else
    die "$KV_DB_URL missing and server '$PG_SERVER' already exists.
       If other applications share this server, do NOT reset its admin password.
       Set PG_ADMIN_URL_SECRET to a Key Vault secret holding an admin connection URL;
       this script then creates a dedicated role and database for the gateway."
  fi
else
  PG_PASSWORD="$(random_alnum 28)"  # pragma: allowlist secret
  # NOTE: the CLI echoes the password in its creation output. Redirected to
  # /dev/null so it does not land in terminal scrollback or CI logs.
  az postgres flexible-server create \
    --name "$PG_SERVER" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" \
    --admin-user "$PG_ADMIN_USER" --admin-password "$PG_PASSWORD" \
    --sku-name "$PG_SKU" --tier "$PG_TIER" --storage-size "$PG_STORAGE_GB" \
    --version "$PG_VERSION" --public-access 0.0.0.0 --yes > /dev/null
  ok "created dedicated server ($PG_SKU, ${PG_STORAGE_GB}GB, PG${PG_VERSION})"
  # --database-name on server create only works for Elastic Clusters, so the
  # database is always created as a separate step.
  az postgres flexible-server db create -g "$RESOURCE_GROUP" -s "$PG_SERVER" -d "$PG_DATABASE" -o none
  ok "database $PG_DATABASE created"
  ensure_azure_services_firewall
  kv_set "$KV_DB_URL" "postgresql+psycopg://${PG_ADMIN_USER}:${PG_PASSWORD}@${PG_FQDN}:5432/${PG_DATABASE}?sslmode=require"
fi

log "Key Vault secrets"
ensure_secret "$KV_JWT_SECRET" random_secret 48
# Rotating this makes every previously stored OAuth token undecryptable, so it
# is generated once and never overwritten.
ensure_secret "$KV_ENC_SECRET" random_secret 48
ensure_secret "$KV_ADMIN_PASSWORD" random_secret 24
# Keep the bootstrap default distinct from the administrator's own password.
ensure_secret "$KV_DEFAULT_USER_PASSWORD" random_secret 24

log "Identity permissions (least privilege)"
GRANTED=0
ensure_role() {
  if az role assignment list --assignee "$UAMI_PRINCIPAL" --scope "$2" \
       --query "[?roleDefinitionName=='$1'] | length(@)" -o tsv 2>/dev/null | grep -q '^[1-9]'; then
    ok "$1 on ${2##*/} (exists)"
  else
    az role assignment create --assignee-object-id "$UAMI_PRINCIPAL" --assignee-principal-type ServicePrincipal \
      --role "$1" --scope "$2" -o none
    ok "$1 on ${2##*/}"
    GRANTED=1
  fi
}
ensure_role "AcrPull" "$ACR_ID"
for s in "${GATEWAY_SECRETS[@]}"; do
  ensure_role "Key Vault Secrets User" "${KV_ID}/secrets/${s}"
done
if [ "$GRANTED" = "1" ]; then
  sleep 30   # RBAC propagation before the container app pulls the image and secrets
fi

log "Infrastructure ready"
echo "  Identity : $UAMI_NAME"
echo "  Postgres : $PG_FQDN/$PG_DATABASE"
echo "  Key Vault: $KEYVAULT_NAME"
echo "  Next     : ./02-build-images.sh"
