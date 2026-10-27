#!/usr/bin/env bash
# MCP Gateway deploy orchestrator: prepare infra -> build -> deploy -> verify.
#
#   ./deploy.sh              full run
#   ./deploy.sh --skip-infra skip 01 (infra already exists)
#   ./deploy.sh --skip-build skip 02 (preserve the live digest unless explicitly selected)
#
# Every step is idempotent, so a full run against an existing deployment is
# safe - it updates rather than duplicates.
set -euo pipefail
cd "$(dirname "$0")"

SKIP_INFRA=0; SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-infra) SKIP_INFRA=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

source ./00-config.sh
if [ "$SKIP_BUILD" != "1" ]; then
  [ -z "$IMAGE_DIGEST" ] || die "IMAGE_DIGEST requires --skip-build"
  export IMAGE_TAG="${IMAGE_TAG:-$(new_build_tag)}"
fi
[ "$SKIP_INFRA" = "1" ] || bash ./01-prepare-azure.sh
[ "$SKIP_BUILD" = "1" ] || bash ./02-build-images.sh
IMAGE="$(resolve_image)"
export IMAGE_DIGEST="${IMAGE##*@}"
export IMAGE_TAG=""
DEPLOY_RESULT_FILE="$(mktemp)"
export DEPLOY_RESULT_FILE
trap 'rm -f "$DEPLOY_RESULT_FILE"' EXIT
bash ./03-deploy-gateway.sh
EXPECTED_REVISION="$(cat "$DEPLOY_RESULT_FILE")"
[ -n "$EXPECTED_REVISION" ] || die "Deployment did not report a revision"
export EXPECTED_REVISION
bash ./04-smoke.sh

echo
echo "✔ MCP Gateway deployed."
