# Deploying MCP Gateway to Azure

The scripts are the source of truth. This file explains **why**; `deploy/scripts/`
does the **how**.

```bash
cd deploy/scripts
az login
./deploy.sh                 # infra -> build -> deploy -> verify
./deploy.sh --skip-build    # redeploy the image already in ACR
```

Every script is idempotent. Re-running against an existing deployment updates it
rather than duplicating anything.

## Why Container Apps, not AKS

A single container, one replica, no service mesh. Kubernetes earns its
complexity at multi-node scale and rolling deploys across many replicas; none of
that applies yet. Container Apps provides HTTPS, a hostname and scale-to-zero
without a cluster to operate.

Revisit if per-tenant isolation ends up requiring separate network policies.

## What runs where

| Piece | Where | Notes |
|---|---|---|
| Gateway | Container App `mcp-gateway` in `vcare-rc-cae` | 1 CPU / 2 GB, 1 replica |
| Database | `vcare-mcpgw-db` (Postgres 16 Flexible, B1ms) | ~$13/month |
| Image | `vcarercacr.azurecr.io/mcp-gateway` | built by ACR Tasks |
| Secrets | Key Vault `vcare-rc-kv`, names prefixed `mcpgw-` | values never in this repo |
| Identity | `vcare-rc-uami` | ACR pull + Key Vault read |

No password appears in any script, deploy command or environment variable. The
managed identity covers both the registry pull and the secret reads, and secrets
reach the container as `keyvaultref`, so their values are not visible in the
container app's configuration.

## Two hardware traps

These cost an afternoon to discover. Both are enforced by guards in
`02-build-images.sh`, but read them before changing the build.

**You cannot build this image on an Apple Silicon Mac.** The UBI 10 base image
requires the `x86-64-v3` instruction set, which QEMU does not emulate. A
`docker buildx --platform linux/amd64` build fails with:

```
Fatal glibc error: CPU does not support x86-64-v3
```

That is a hardware limit, not a configuration problem. Builds need real amd64
hardware: ACR Tasks (what these scripts use), a GitHub amd64 runner, or an amd64
VM.

**ACR Tasks uses the classic Docker builder, not BuildKit.** `COPY --chmod=`
fails with `the --chmod option requires BuildKit`. The `Containerfile` has been
made classic-compatible using `COPY` followed by a separate `RUN chmod`. Do not
reintroduce BuildKit-only directives, or ACR builds stop working.

There is a third, smaller trap: ACR's dependency scanner cannot resolve
`FROM ${WHEELS_REF}` where `WHEELS_REF` itself defaults to `${UBI_MINIMAL}`. The
base images are therefore passed explicitly as `--build-arg` values from
`00-config.sh`.

## Secrets

| Secret | Rotatable? |
|---|---|
| `mcpgw-jwt-secret` | Yes. Invalidates active sessions. |
| `mcpgw-auth-encryption-secret` | **No.** Rotating makes every stored OAuth token undecryptable. |
| `mcpgw-database-url` | Yes, together with the Postgres admin password. |
| `mcpgw-platform-admin-password` | Yes. Bootstrap password only; used on first start. |

Retrieve one with:

```bash
az keyvault secret show --vault-name vcare-rc-kv \
  --name mcpgw-platform-admin-password --query value -o tsv
```

Writing secrets needs the **Key Vault Secrets Officer** role. Subscription Owner
is not sufficient - that grants control-plane rights only, not data-plane.
`01-prepare-azure.sh` grants it to the caller if missing, scoped to this vault.

## A second environment

Everything in `00-config.sh` is overridable, so no file needs editing:

```bash
RESOURCE_GROUP=my-rg APP_NAME_AZ=mcp-gateway-dev \
PG_SERVER=my-gw-db IMAGE_TAG=dev ./deploy.sh
```

`PG_SERVER` is a **global** DNS label and must be unique across all of Azure.

## Known gaps

- **Zoho OAuth** redirect URIs point at whichever host performed the consent.
  A deployment on a new hostname needs re-consent.
- **Tenant data does not travel.** Tenants and gateways are database rows, so a
  fresh deployment starts empty.
- **No CI.** Builds are run manually from a workstation. A GitHub Actions
  workflow on an amd64 runner would remove that step.
