#!/usr/bin/env bash
# MCP Gateway deploy orchestrator: prepare infra -> build -> deploy -> verify.
#
#   ./deploy.sh              full run
#   ./deploy.sh --skip-infra skip 01 (infra already exists)
#   ./deploy.sh --skip-build skip 02 (reuse the image already in ACR)
#
# Every step is idempotent, so a full run against an existing deployment is
# safe - it updates rather than duplicates.
set -euo pipefail
cd "$(dirname "$0")"
chmod +x ./*.sh

SKIP_INFRA=0; SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-infra) SKIP_INFRA=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

[ "$SKIP_INFRA" = "1" ] || ./01-prepare-azure.sh
[ "$SKIP_BUILD" = "1" ] || ./02-build-images.sh
./03-deploy-gateway.sh
./04-smoke.sh

echo
echo "✔ MCP Gateway deployed."
