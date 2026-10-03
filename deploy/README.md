# Deploying MCP Gateway to Azure

The scripts are the source of truth. This file explains **why**; `deploy/scripts/`
does the **how**.

```bash
cd deploy/scripts
az login
./deploy.sh                 # infra -> build -> deploy -> verify
./deploy.sh --skip-build    # redeploy the image already in ACR

# A named target: overrides live in profiles/<name>.env
DEPLOY_PROFILE=profiles/healthcare-rg.env ./deploy.sh
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

| Piece | `vcare-rc-rg` (script defaults) | `healthcare-rg` (`profiles/healthcare-rg.env`) |
|---|---|---|
| Gateway | Container App `mcp-gateway` in `vcare-rc-cae` | Container App `mcp-gateway` in `cae-frontdesk-demo-hospital` |
| Database | Dedicated server `vcare-mcpgw-db` | Database `mcpgateway`, role `mcpgateway_app` on shared `pg-fd-demo-hospital-0574c1` |
| Image | `vcarercacr.azurecr.io/mcp-gateway` | `acrfd399536.azurecr.io/mcp-gateway` |
| Secrets | Key Vault `vcare-rc-kv`, prefix `mcpgw-` | Shared Key Vault `kv-fd-demo-hospi-0574c1`, prefix `mcpgw-` |
| Identity | `vcare-rc-uami` | Dedicated `id-mcp-gateway` |

The gateway's identity gets `AcrPull` on the registry and `Key Vault Secrets User`
on each `mcpgw-*` secret, not on the vault. In a shared vault the gateway therefore
cannot read other applications' secrets.

## Shared Postgres servers

When `PG_SERVER` already exists and `PG_ADMIN_URL_SECRET` names a Key Vault secret
holding an admin connection URL, `01-prepare-azure.sh` creates a dedicated login
role and database for the gateway. The admin URL is read only during that step and
never reaches the container app. **Never reset the admin password of a shared
server** - other applications depend on it.

`provision_shared_db.py` changes nothing until it proves the role is the gateway's.
The proof is an ownership marker, the role comment written in the same transaction
as `CREATE ROLE`. A role without the marker is refused, so a configuration that names
another application's role or database cannot change it. A marked role whose
database is missing is an interrupted run, and the next run resumes it. To adopt a
gateway role created before the marker existed, run once with
`PG_ADOPT_EXISTING_ROLE=<exact role name>`; the privilege and ownership checks
still apply.

Size the connection pool to the server. A Burstable B1ms server allows
`max_connections=50` across all of its databases. The gateway opens up to
`GUNICORN_WORKERS x (DB_POOL_SIZE + DB_MAX_OVERFLOW)` connections, and the role's
`CONNECTION LIMIT` enforces that budget plus a small margin on the server side.

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
`00-config.sh`. Their defaults are read from the `Containerfile`'s `ARG` lines,
so upstream base-image updates apply without editing the scripts.

## Secrets

| Secret | Rotatable? |
|---|---|
| `mcpgw-jwt-secret` | Yes. Invalidates active sessions. |
| `mcpgw-auth-encryption-secret` | **No.** Rotating makes every stored OAuth token undecryptable. |
| `mcpgw-database-url` | Yes, together with the gateway role's password. On a shared server, delete the secret and re-run `01-prepare-azure.sh` to rotate it. |
| `mcpgw-platform-admin-password` | Yes. Bootstrap password only; used on first start. |
| `mcpgw-default-user-password` | Yes. Required bootstrap default; keep distinct from the admin password. |

Run `01-prepare-azure.sh` before deploying an upgraded image so the default-user
secret exists. Both passwords must meet the gateway strength requirements. A
custom admin password distinct from the default does not trigger a forced password
change on first boot.

Retrieve one with:

```bash
az keyvault secret show --vault-name vcare-rc-kv \
  --name mcpgw-platform-admin-password --query value -o tsv
```

Writing secrets needs the **Key Vault Secrets Officer** role. Subscription Owner
is not sufficient - that grants control-plane rights only, not data-plane.
`01-prepare-azure.sh` grants it to the caller if missing, scoped to this vault.

## Headless deployments

Set `MCPGATEWAY_UI_ENABLED=false` and `MCPGATEWAY_ADMIN_API_ENABLED=false` in the
profile. Consuming platforms then use only the REST, MCP and A2A endpoints, and
`04-smoke.sh` asserts that `/admin/login` returns 404.

## A second environment

Add a profile under `profiles/`, or override `00-config.sh` values inline:

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
