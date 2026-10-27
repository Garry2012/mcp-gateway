# Deploying MCP Gateway to Azure

The scripts are the source of truth. This file explains **why**; `deploy/scripts/`
does the **how**.

```bash
cd deploy/scripts
az login
./deploy.sh                 # infra -> build -> deploy -> verify
./deploy.sh --skip-infra --skip-build  # update configuration using the live image digest

# A named target: overrides live in profiles/<name>.env
DEPLOY_PROFILE=profiles/healthcare-rg.env ./deploy.sh
```

Deployment updates the existing app. Build scripts archive committed `HEAD`; commit reviewed application changes before building.
Uncommitted files are not included in the image.

## Image and configuration updates

Container Apps receives immutable `repository@sha256:...` image references. New builds use a commit, timestamp and random suffix for their default tag.
Builds no longer publish a mutable `latest` alias. An explicit `IMAGE_TAG` is resolved to a digest before deployment.
The orchestrator carries the selected digest into deployment and smoke checks.

With no image selector, `03-deploy-gateway.sh` preserves the existing app's pinned digest.
It refuses a live tag reference because resolving that tag could select a different image.
For a first deployment, supply `IMAGE_TAG` or `IMAGE_DIGEST`, or run the full build flow.
Set only one selector. Use `--skip-build` when supplying `IMAGE_DIGEST`.

```bash
# Configuration only; preserve the deployed digest.
DEPLOY_PROFILE=profiles/healthcare-rg.env ./deploy.sh --skip-infra --skip-build

# Deploy or roll back to an explicitly selected release. Substitute its actual digest.
DEPLOY_PROFILE=profiles/healthcare-rg.env IMAGE_DIGEST="sha256:<64-hex-digest>" \
  ./deploy.sh --skip-infra --skip-build
```

`APP_CPU`, `APP_MEMORY`, `APP_MIN_REPLICAS` and `APP_MAX_REPLICAS` apply on both creation and update.
Unspecified resource values preserve live settings during updates.
Creation defaults to 1 CPU, 2 GiB and minimum/maximum replica counts of 1.
Profiles are authoritative; review their settings before deploying after a manual Azure resource change.
The scripts support one gateway container and reject multi-container updates for separate review.
Azure read errors stop deployment; only an explicit `ResourceNotFound` permits creation.

Three optional settings support deliberate removal:

| Script setting | Container environment variable |
|---|---|
| `DCR_ALLOWED_ISSUERS` | `DCR_ALLOWED_ISSUERS` |
| `OTEL_REDACT_FIELDS` | `OTEL_REDACT_FIELDS` |
| `KV_OTEL_HEADERS` | `OTEL_EXPORTER_OTLP_HEADERS` |

An unset setting preserves the live value. A nonempty setting replaces it. An explicit empty string removes the variable.
For example, `OTEL_REDACT_FIELDS=''` restores application defaults; it does not mean an empty redaction list.
Set removals in the selected profile when that profile already defines the setting.
Other environment variables and secrets remain intact. Removing an exporter reference does not delete its stored secret.
Fixed script-owned settings still reconcile to the selected profile and script defaults.
The update uses Azure CLI's targeted [environment variable operations](https://learn.microsoft.com/en-us/cli/azure/containerapp#az-containerapp-update).

Each deployment starts a fresh revision, including configuration-only updates, so changed secret references reload.
The orchestrator passes the returned revision name to smoke checks through a temporary file, then removes the file.
Smoke checks require that exact revision, the selected digest, health and 100% traffic.
Standalone `04-smoke.sh` defaults to the latest revision; set `EXPECTED_REVISION` to verify a specific rollout.
An older healthy revision with the same image cannot prove a configuration update succeeded.

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

## Langfuse tool tracing

The gateway exports traces through OpenTelemetry. The built-in Observability database remains separate.
Tool input and output payloads appear on exported `tool.invoke` spans in Langfuse.
Shared trace naming, propagation, credential masking, and call-ID grouping remain enabled.
Install the `observability` extra when running the gateway outside its container image.
`OTEL_CAPTURE_INPUT_SPANS=tool.invoke` and `OTEL_CAPTURE_OUTPUT_SPANS=tool.invoke` enable tool payload capture.
The deployment script requires an endpoint and a supported protocol when export is enabled.

### Healthcare Azure deployment

The `healthcare-rg` profile currently exports traces to Langfuse Cloud in the EU for an interface trial.
The endpoint is `https://cloud.langfuse.com/api/public/otel/v1/traces`, using HTTP with TLS verification.
`KV_OTEL_HEADERS` names the Key Vault secret containing the OTLP authorization and `x-langfuse-ingestion-version=4` headers.
Provision the secret before deployment. The preparation script grants the gateway identity access to that secret only.
The deployment script uses a Key Vault reference; it never reads the header value.

The trial uses the gateway's default credential masking, with no additional patient-field masking.
Tool input and output capture remains enabled, including test names, phone numbers, summary text, and knowledge queries.
Tool requests and responses remain unchanged. LLM Chat message and response capture remains disabled.
Remove any previous `OTEL_REDACT_FIELDS` override from the container app to restore the defaults.

When Langfuse attributes are enabled, send `X-Call-Id` with the same opaque identifier on each request in a voice conversation.
The gateway maps it to `langfuse.session.id` on HTTP request spans, tool invocations, and their outbound child spans.
Use Langfuse's Session ID filter or Sessions page to find the conversation's tool calls.
The identifier must contain 1–128 ASCII letters, digits, periods, underscores, colons, or hyphens, starting with a letter or digit.
The gateway omits call identifiers that existing redaction would alter, so masked values cannot merge different call labels.
Missing or invalid identifiers leave existing MCP session tracing unchanged. They do not reject the request.
This telemetry label does not establish caller identity or authorize appointment access.
The MCP protocol session stays unchanged; the Langfuse session label uses the call ID when valid.
Correlation IDs and forwarded request headers stay unchanged. The mapping applies only to new traces.

### Capture limits

The existing tool path exports successful tool results only. Tool failures retain error tracing but may have no output payload.
Payload serialization masks configured sensitive fields and truncates large values.
The default payload limit is 32,768 characters before any additional backend limits.
Default redaction targets secrets; it does not guarantee removal of patient information.
Review `OTEL_REDACT_FIELDS` before capturing real hospital traffic.
Custom field lists replace the defaults; retain the secret fields when adding hospital-specific fields.
Gateway traces cover gateway operations; instrument the voice agent separately for conversations and model usage.

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
