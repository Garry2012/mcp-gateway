#!/usr/bin/env bash
# Prove the deployment actually works. Every check asserts on real HTTP output,
# never on an exit code alone.
#
# Exits non-zero on the first failure, so `deploy.sh` stops rather than
# reporting success over a broken deployment.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/00-config.sh"

FQDN="$(az containerapp show -n "$APP_NAME_AZ" -g "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)" \
  || die "app '$APP_NAME_AZ' not found - run ./03-deploy-gateway.sh first"
URL="https://${FQDN}"

log "Smoke test: $URL"

# 1. Health. A cold start can take ~60s, so poll rather than fail immediately.
for i in $(seq 1 12); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/health" 2>/dev/null || echo 000)"
  [ "$CODE" = "200" ] && break
  [ "$i" = "12" ] && die "/health never returned 200 (last: $CODE)"
  sleep 10
done
ok "/health 200"

# 2. Database connectivity. The gateway reports unhealthy if Postgres is
#    unreachable, so a healthy status proves the Key Vault connection string
#    resolved and the firewall rule works.
curl -s --max-time 20 "$URL/health" 2>/dev/null | grep -q '"status":"healthy"' \
  || die "health endpoint reachable but status is not healthy"
ok "database reachable"

# 3. Login page renders.
LOGIN="$(curl -s --max-time 20 "$URL/admin/login" 2>/dev/null)"
echo "$LOGIN" | grep -q "<title>" || die "login page did not render"
ok "login page renders"

# 4. Branding. Guards against deploying a stale image built before the rebrand.
TITLE="$(printf '%s' "$LOGIN" | grep -oE '<title>[^<]*</title>' | head -1)"
printf '%s' "$LOGIN" | grep -q "$BRAND_NAME" || die "page does not mention '$BRAND_NAME' - stale image? ($TITLE)"
ok "brand present: $TITLE"

LEGACY="$(printf '%s' "$LOGIN" | grep -c 'ContextForge' || true)"
[ "$LEGACY" = "0" ] || die "$LEGACY legacy brand references on the login page - stale image"
ok "no legacy brand references"

# 5. Authentication is enforced. A public admin API would be a serious
#    misconfiguration, so assert the unauthenticated path is rejected.
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/gateways" 2>/dev/null || echo 000)"
case "$CODE" in
  401|403) ok "unauthenticated /gateways rejected ($CODE)" ;;
  *)       die "unauthenticated /gateways returned $CODE - expected 401/403" ;;
esac

log "All checks passed"
echo "  $URL/admin/login"
