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

## Jaeger tool tracing

The Jaeger overlay enables OpenTelemetry export without changing gateway request handling.
The built-in Observability database remains separate. Tool payloads appear in Jaeger, not in that database.

### Docker Compose

After configuring the base Compose stack's required secrets, start the gateway with the overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.with-jaeger.yml up -d gateway
```

Open `http://localhost:16686`, select service `mcp-gateway`, and search after making a tool call.
Expand the `tool.invoke` span. Its attributes include:

- `langfuse.observation.input`: the captured input arguments.
- `langfuse.observation.output`: the captured successful tool result.
- `tool.name`, `success`, and `duration.ms`: execution details.

These attribute names do not require Langfuse. ContextForge currently uses the `langfuse.*` namespace for payloads.
The overlay sets `OTEL_EMIT_LANGFUSE_ATTRIBUTES=true` so the exporter retains them.
It explicitly disables caller identity attributes.

Jaeger uses a named Docker volume with Badger storage and a 48-hour trace retention period.
Traces survive container restarts. Removing the volume deletes them.
Badger supports this single-instance deployment; scaling Jaeger requires a different storage design.
The UI and collector bind to loopback on the host. Keep them private because payloads can contain hospital data.

Set `JAEGER_UI_PORT` or `JAEGER_OTLP_GRPC_PORT` if another local service uses ports 16686 or 4317.
To run only Jaeger for a gateway started outside Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.with-jaeger.yml up -d --no-deps jaeger
```

Set the host gateway's exporter endpoint to `http://127.0.0.1:4317` and use the settings below.
Install the gateway's `observability` extra when running outside the provided container image.

### Azure exporter configuration

Deploy Jaeger with private collector access before enabling gateway export.
The local Compose overlay does not provision an Azure Jaeger service.
Use authenticated or private access for its query UI; do not expose captured payloads through unauthenticated public ingress.

Add these settings to the selected deployment profile, using the collector's reachable hostname:

```bash
OTEL_ENABLE_OBSERVABILITY=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://YOUR_PRIVATE_JAEGER_HOST:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_INSECURE=true
OTEL_EMIT_LANGFUSE_ATTRIBUTES=true
OTEL_CAPTURE_IDENTITY_ATTRIBUTES=false
OTEL_CAPTURE_INPUT_SPANS=tool.invoke
OTEL_CAPTURE_OUTPUT_SPANS=tool.invoke
```

Use `https://` and `OTEL_EXPORTER_OTLP_INSECURE=false` for a TLS-enabled collector.
Remove any previous `LANGFUSE_OTEL_ENDPOINT` override or exporter authentication headers when switching from another tracing backend.
The Azure deployment script now forwards these settings on creation and update.
It rejects enabled export without an endpoint or with an unsupported transport protocol.
Export remains disabled unless `OTEL_ENABLE_OBSERVABILITY=true` is supplied.

### Healthcare Azure deployment

The `healthcare-rg` profile enables export to `http://mcp-gateway-jaeger:4317`.
The receiver accepts traffic only from the existing Container Apps environment.
The `mcp-gateway-jaeger` app contains Jaeger and a password-protected dashboard proxy.
Each container receives 0.25 CPU and 0.5 GiB. The app runs exactly one replica.

Azure uses `deploy/jaeger/config-memory.yaml`, which retains at most 1,000 traces in memory.
Restarting or deploying Jaeger deletes all traces. Older traces are evicted as new traces arrive.
The memory limiter can refuse ingestion under memory pressure. This setup provides temporary debugging storage.
It does not provision a database, storage account, or persistent volume.

Dashboard: `https://mcp-gateway-jaeger.icytree-6543aaa9.centralindia.azurecontainerapps.io`

- Username: `garima`.
- Password: secret `jaeger-dashboard-password` in Key Vault `kv-fd-demo-hospi-0574c1`.
- Dashboard authentication uses HTTPS Basic authentication, separate from the gateway login.
- Microsoft sign-in requires an Entra administrator to provision an application registration.

The dedicated identity `id-mcp-gateway-jaeger` has `AcrPull` on `acrfd399536`.
It can read only the `jaeger-dashboard-htpasswd` secret from Key Vault.
The proxy receives a bcrypt hash through a secret reference. It never receives the plaintext password.
HTTP access redirects to HTTPS. The proxy protects both the dashboard and query API.
Port 4317 remains internal even when the dashboard ingress is external.
Jaeger's unprotected query port 16686 has no ingress mapping.

Build both images from the `deploy/jaeger` directory with unique tags:

```bash
az acr build --registry acrfd399536 --image mcp-gateway-jaeger:YOUR_TAG --file Containerfile .
az acr build --registry acrfd399536 --image mcp-gateway-jaeger-proxy:YOUR_TAG --file Containerfile.proxy .
```

Render `azure.template.yaml` with `LOCATION`, `JAEGER_IDENTITY_ID`, `ENVIRONMENT_ID`, `REGISTRY`,
`KEYVAULT_URI`, `JAEGER_IMAGE`, and `JAEGER_PROXY_IMAGE`.
The template contains secret references only. Keep plaintext passwords outside deployment files and command arguments.
The identity and Key Vault secrets must exist before deployment.
Apply the rendered template with `az containerapp create --resource-group healthcare-rg --name mcp-gateway-jaeger --yaml RENDERED_FILE`.
The template starts with private ingress. Verify the password boundary before enabling external dashboard ingress:

```bash
az containerapp ingress update --resource-group healthcare-rg --name mcp-gateway-jaeger \
  --type external --target-port 8080 --transport http
```

Run the real-container authentication checks locally with Docker and `htpasswd` installed:

```bash
RUN_JAEGER_DOCKER_TESTS=1 .venv/bin/python -m pytest \
  tests/integration/test_jaeger_dashboard_auth.py --noconftest --with-integration
```

These checks reject anonymous access, incorrect passwords, and unknown users on the UI and trace API.
They also verify successful login and startup refusal when the secret is absent.
After Azure deployment, repeat these checks against its HTTPS endpoint and verify a gateway tool trace.

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
