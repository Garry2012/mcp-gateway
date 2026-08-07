#!/usr/bin/env bash
# Create the infrastructure MCP Gateway needs: Postgres, its database and
# firewall rule, and the Key Vault secrets.
#
# Idempotent. Every step checks before it creates, so re-running is safe and
# leaves existing resources untouched.
#
# Assumes these already exist and does NOT create them:
#   - the resource group
#   - the container registry     (ACR_NAME)
#   - the Container Apps env     (CAE_NAME)
#   - the managed identity       (UAMI_NAME) with AcrPull + Key Vault Secrets User
#   - the Key Vault              (KEYVAULT_NAME)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/00-config.sh"

log "Preflight"
az account show -o none 2>/dev/null || die "not logged in - run 'az login'"
[ -n "$UAMI_ID" ] || die "managed identity '$UAMI_NAME' not found in $RESOURCE_GROUP"
ok "subscription $(az account show --query name -o tsv)"
ok "identity $UAMI_NAME"

# The caller needs Key Vault data-plane access to WRITE secrets. Being
# subscription Owner is not sufficient - Owner grants control-plane rights only.
log "Key Vault write access"
CALLER="$(az account show --query user.name -o tsv)"
KV_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.KeyVault/vaults/${KEYVAULT_NAME}"
if az role assignment list --assignee "$CALLER" --scope "$KV_SCOPE" \
     --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)" -o tsv 2>/dev/null | grep -q '^[1-9]'; then
  ok "$CALLER already has Key Vault Secrets Officer"
else
  warn "granting Key Vault Secrets Officer to $CALLER (scoped to this vault only)"
  az role assignment create --assignee "$CALLER" --role "Key Vault Secrets Officer" \
    --scope "$KV_SCOPE" -o none
  sleep 20   # RBAC propagation
  ok "granted"
fi

log "Postgres flexible server: $PG_SERVER"
if az postgres flexible-server show -n "$PG_SERVER" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  ok "already exists"
  PG_PASSWORD=""
else
  PG_PASSWORD="$(python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print('Mg'+''.join(secrets.choice(a) for _ in range(28)))")"
  # NOTE: the CLI echoes the password in its creation output. Redirected to
  # /dev/null so it does not land in terminal scrollback or CI logs.
  az postgres flexible-server create \
    --name "$PG_SERVER" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" \
    --admin-user "$PG_ADMIN_USER" --admin-password "$PG_PASSWORD" \
    --sku-name "$PG_SKU" --tier "$PG_TIER" --storage-size "$PG_STORAGE_GB" \
    --version "$PG_VERSION" --public-access 0.0.0.0 --yes > /dev/null
  ok "created ($PG_SKU, ${PG_STORAGE_GB}GB, PG${PG_VERSION})"
fi

log "Database: $PG_DATABASE"
if az postgres flexible-server db show -g "$RESOURCE_GROUP" -s "$PG_SERVER" -d "$PG_DATABASE" -o none 2>/dev/null; then
  ok "already exists"
else
  # --database-name on server create only works for Elastic Clusters, so the
  # database is always created as a separate step.
  az postgres flexible-server db create -g "$RESOURCE_GROUP" -s "$PG_SERVER" -d "$PG_DATABASE" -o none
  ok "created"
fi

log "Firewall: allow Azure services"
if az postgres flexible-server firewall-rule show -g "$RESOURCE_GROUP" -n "$PG_SERVER" \
     --rule-name AllowAzureServices -o none 2>/dev/null; then
  ok "already exists"
else
  # 0.0.0.0-0.0.0.0 is Azure's sentinel for "allow Azure-internal services",
  # not "allow the whole internet".
  az postgres flexible-server firewall-rule create -g "$RESOURCE_GROUP" -n "$PG_SERVER" \
    --rule-name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
  ok "created"
fi

log "Key Vault secrets"
kv_has() { az keyvault secret show --vault-name "$KEYVAULT_NAME" --name "$1" -o none 2>/dev/null; }
kv_set() {
  az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "$1" --value "$2" -o none \
    || die "could not write secret '$1' - check Key Vault permissions"
  ok "$1"
}

kv_has "$KV_JWT_SECRET" && ok "$KV_JWT_SECRET (exists)" \
  || kv_set "$KV_JWT_SECRET" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"

# Rotating this makes every previously stored OAuth token undecryptable, so it
# is generated once and never overwritten.
kv_has "$KV_ENC_SECRET" && ok "$KV_ENC_SECRET (exists)" \
  || kv_set "$KV_ENC_SECRET" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"

kv_has "$KV_ADMIN_PASSWORD" && ok "$KV_ADMIN_PASSWORD (exists)" \
  || kv_set "$KV_ADMIN_PASSWORD" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"

if kv_has "$KV_DB_URL"; then
  ok "$KV_DB_URL (exists)"
elif [ -n "$PG_PASSWORD" ]; then
  kv_set "$KV_DB_URL" "postgresql+psycopg://${PG_ADMIN_USER}:${PG_PASSWORD}@${PG_FQDN}:5432/${PG_DATABASE}?sslmode=require"
else
  die "$KV_DB_URL missing but the Postgres server already exists, so its password is unknown.
       Reset it and store the new connection string:
         az postgres flexible-server update -g $RESOURCE_GROUP -n $PG_SERVER --admin-password <new>"
fi

log "Infrastructure ready"
echo "  Postgres : $PG_FQDN/$PG_DATABASE"
echo "  Key Vault: $KEYVAULT_NAME"
echo "  Next     : ./02-build-images.sh"
