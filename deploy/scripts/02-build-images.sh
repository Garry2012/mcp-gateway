#!/usr/bin/env bash
# Build the gateway image in ACR and push it.
#
# READ THIS BEFORE "FIXING" THE BUILD -------------------------------------
#
# 1. The build MUST run in ACR, not locally on an Apple Silicon Mac.
#    The UBI 10 base image requires the x86-64-v3 instruction set. QEMU
#    emulation does not provide it, so a `docker buildx --platform linux/amd64`
#    build on an ARM Mac dies with:
#        Fatal glibc error: CPU does not support x86-64-v3
#    That is a hardware/emulation limit, not a configuration problem. Any amd64
#    build needs real amd64 hardware: ACR Tasks, a GitHub amd64 runner, or an
#    amd64 VM.
#
# 2. ACR Tasks uses the CLASSIC Docker builder, which does not support BuildKit
#    syntax. `COPY --chmod=` fails with:
#        the --chmod option requires BuildKit
#    The Containerfile in this repo has been made classic-compatible (COPY plus
#    a separate RUN chmod). Do not reintroduce BuildKit-only directives, or
#    this script stops working.
#
# 3. Base images are passed explicitly. See the note in 00-config.sh.
#
# 4. The build context is a clean `git archive` export rather than the working
#    tree. In a git worktree, `.git` is a FILE pointing elsewhere, and the
#    working tree also carries .venv/.cache noise that inflates the upload.
# --------------------------------------------------------------------------
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/00-config.sh"

log "Preflight"
az account show -o none 2>/dev/null || die "not logged in - run 'az login'"
az acr show -n "$ACR_NAME" -o none 2>/dev/null || die "registry '$ACR_NAME' not found"
ok "registry $REGISTRY"

# Anchored to line start so the explanatory comment in the Containerfile, which
# mentions the directive by name, does not trip this guard.
if grep -qE "^COPY --chmod" "$ROOT_DIR/Containerfile" 2>/dev/null; then
  die "Containerfile uses 'COPY --chmod', which ACR's classic builder cannot handle.
       Replace with 'COPY ...' followed by 'RUN chmod ...' (see note 2 above)."
fi
ok "Containerfile is classic-builder compatible"

BUILD_CTX="$(mktemp -d)"
trap 'rm -rf "$BUILD_CTX"' EXIT
git -C "$ROOT_DIR" archive HEAD | tar -x -C "$BUILD_CTX"
ok "context exported ($(find "$BUILD_CTX" -type f | wc -l | tr -d ' ') files, from $(git -C "$ROOT_DIR" rev-parse --short HEAD))"

log "Building $IMAGE_REPO:$IMAGE_TAG in ACR (10-20 min)"
cd "$BUILD_CTX"
az acr build \
  --registry "$ACR_NAME" \
  --image "${IMAGE_REPO}:${IMAGE_TAG}" \
  --image "${IMAGE_REPO}:latest" \
  --file Containerfile \
  --build-arg UBI_BASE="$UBI_BASE" \
  --build-arg NODEJS_IMAGE="$NODEJS_IMAGE" \
  --build-arg UBI_MINIMAL="$UBI_MINIMAL" \
  --build-arg WHEELS_REF="$WHEELS_REF" \
  . || die "ACR build failed - see output above"

# Verify by listing tags. The build command's exit code alone is not proof the
# image was pushed.
log "Verifying push"
az acr repository show-tags -n "$ACR_NAME" --repository "$IMAGE_REPO" -o tsv 2>/dev/null \
  | grep -qx "$IMAGE_TAG" || die "tag '$IMAGE_TAG' not present in $ACR_NAME after build"
ok "$IMAGE"
echo "  Next: ./03-deploy-gateway.sh"
