# Fork Customizations

This repository (`Garry2012/mcp-gateway`) is a fork of
[`IBM/mcp-context-forge`](https://github.com/IBM/mcp-context-forge).

The fork tracks upstream as closely as possible. It carries only the divergences below.
Keep UI changes limited to the functional fixes listed below. Submit fixes upstream and avoid branding or cosmetic changes.

Last updated: **2026-10-06**.

## Syncing with upstream

The 2026-10-06 integration targets upstream `faa31eaf5`. It retains the divergences below.
The healthcare profile pins both MCP protocol modes to `legacy` to preserve deployed handshake behavior.
Automatic negotiation fails discovery against an older sample server that omits modern cache metadata.
Test modern negotiation separately before changing this profile.

The `upstream` remote has pushing disabled, so `git push upstream` fails loudly.

```bash
git fetch upstream
git checkout -b sync/upstream-<date> origin/main
git merge upstream/main
```

Use merge, not rebase. Merge resolves each conflict once and records the resolution in history.

### Upstream reset: 2026-10-02

The fork was reset to upstream `16e76efba` (v1.0.11 + 12 commits). The merge commit
records `upstream/main` as a parent. Its tree equals upstream plus the divergences below.
All earlier fork work was dropped: the MCP Gateway rebrand, the CSP-safe Alpine
observability fixes, the observability UI tool timelines, backend tool-execution
observations, Tailwind and CSS build changes, and fork-local docs. Git history keeps that work.

The CSP-safe Alpine observability fixes were restored on 2026-10-05 because the deployed
dashboard remained stuck on its loading placeholders. Divergence 4 describes this restoration.

Fixes still open upstream, which arrive on a later sync if merged:

- [#6126](https://github.com/IBM/mcp-context-forge/pull/6126) and
  [#6127](https://github.com/IBM/mcp-context-forge/pull/6127): blank observability dashboard
  under the CSP-safe Alpine build.
- [#6554](https://github.com/IBM/mcp-context-forge/pull/6554): team-scoped admins receive
  `403 Admin privileges required` on the bare `/admin` entry point.

## Divergences

### 1. Global `/mcp` team-token RBAC

`mcpgateway/transports/streamablehttp_transport.py::_check_any_team_for_streamable_rbac()`
enables team-role lookup for sessions and team-scoped API tokens on both global `/mcp` and
`/servers/<id>/mcp`. Upstream enables it only when a virtual-server ID is present. Upstream
therefore denies `tools.execute`, `servers.use`, and `admin.system_config` on global `/mcp`
to a team API token, even when the caller's team role grants the permission.

`PermissionService` still receives `token_teams`, so public-only API tokens (`teams: []`)
gain no team permissions. Visibility and token permission caps stay independent.

**Merge guidance:** do not restore a server-ID prerequisite. Keep
`test_check_any_team_for_streamable_rbac` and `test_global_tool_call_uses_token_scoped_roles`
in `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`, including the
public-only deny cases. Submit this fix upstream, then drop this divergence when it merges.

### 3. LLM Chat on MCP SDK 2.x (`langchain.mcp`)

Upstream moved to MCP SDK 2.x (#6868), but LLM Chat still used `langchain-mcp-adapters`, which
imports MCP 1.x APIs and fails at import time. Reported as
[IBM/mcp-context-forge#7090](https://github.com/IBM/mcp-context-forge/issues/7090).

`MCPClient` in `mcpgateway/services/mcp_client_chat_service.py` now loads tools through
`langchain.mcp.MCPAdapter` with FastMCP transports (`StreamableHttpTransport`, `SSETransport`,
`StdioTransport`). The `llmchat` extra replaces `langchain-mcp-adapters` with `langchain[mcp]` and
raises the `langchain-core` and `langgraph` caps. `langgraph-sdk` caps `websockets<17`, so the lock
resolves `websockets` 16.x. The import guard keeps the original `ImportError` in the error message.

LLM Chat runs a LangGraph agent without a checkpointer, so it cannot pause for user input. The
FastMCP client therefore declines MCP elicitation requests (`_decline_elicitation`); without it,
`MCPAdapter` turns them into a LangGraph interrupt and the chat returns an empty answer.

**Merge guidance:** when upstream fixes #7090, take upstream's version and drop this divergence.
Keep `test_llmchat_dependencies_import_against_installed_mcp_sdk`: it imports the real chat stack.

### 2. Azure deployment

`deploy/scripts/` and `deploy/README.md` build the image in Azure Container Registry and
deploy it with Key Vault secrets. These are new files, so they do not conflict with upstream.
`pyproject.toml` excludes `deploy/**` from the package manifest check.
`01-prepare-azure.sh` creates a Key Vault secret only after a confirmed `SecretNotFound` and aborts
on any other read error, so a transient failure never regenerates the encryption secret.
`provision_shared_db.py` refuses, before any change, a role or database that it cannot prove belongs
to the gateway. Proof is an ownership marker (role comment) written in the same transaction as
`CREATE ROLE`; an interrupted run resumes, and a pre-marker role needs one explicit
`PG_ADOPT_EXISTING_ROLE` run.
Per-target overrides live in `deploy/scripts/profiles/*.env` (for example `healthcare-rg.env`,
which reuses that resource group's registry, environment, Key Vault and Postgres server).

ACR Tasks uses the classic Docker builder, which rejects `COPY --chmod`. The `Containerfile`
replaces both `COPY --chmod=0755` lines with `COPY` plus `RUN chmod 0755`.
`deploy/scripts/02-build-images.sh` fails fast if a `COPY --chmod` line returns.

**Merge guidance:** if upstream adds a new `COPY --chmod` line, convert it to the same form.
Check new required settings (for example `DEFAULT_USER_PASSWORD`) against
`deploy/scripts/03-deploy-gateway.sh` before rollout.

The deployment scripts also forward opt-in OTLP exporter settings. The Jaeger Compose overlay
uses private host ports, persistent Badger storage, and the existing tool payload instrumentation.
Keep `OTEL_EMIT_LANGFUSE_ATTRIBUTES=true` for payload export until upstream adopts backend-neutral attribute names.
The healthcare Azure profile uses a separate Jaeger app with bounded in-memory storage and a password-protected HTTPS dashboard.
`deploy/jaeger/azure.template.yaml` keeps OTLP ingress private and references the dashboard hash through Key Vault.
The app uses a dedicated identity, with registry pull access and permission to read only its dashboard hash.
The healthcare profile sets token expiry and idle timeout to 480 minutes for eight-hour dashboard sessions.

### 4. CSP-compatible Observability dashboards

The Admin UI uses `@alpinejs/csp`. Its expression parser rejects methods inside inline
`x-data` objects. The Observability dashboard therefore never initializes or requests traces.
The four metrics views also reference unregistered controllers and contain unsupported expressions.

The dashboard and its Metrics, Tools, Prompts, and Resources controllers now live in
`mcpgateway/admin_ui/components/observability-*.js`. `alpine-setup.js` registers all five with
`Alpine.data()`. Their templates use registered names and CSP-compatible expressions.
Tab navigation uses `window.Admin.chartRegistry` for chart cleanup.

This restores the Observability changes from `332ec35f8`, `ca685d1a3`, and the isolated
dashboard fix `b197c1beb`. Unrelated changes from those commits remain excluded.

**Merge guidance:** retain the registered components until upstream includes equivalent fixes.
Port upstream template changes into the templates and controller changes into the JavaScript modules.
Run `npm test` and `make build-ui` after merging. The regression test
`tests/unit/js/observability-csp.test.js` initializes actual templates with the production Alpine
runtime and checks trace requests, navigation, and rendered metrics data.

### 5. Redaction inside JSON text payloads

MCP tool results can contain identical data in `structuredContent` and JSON-encoded `content[].text`.
The trace sanitizer previously masked sensitive fields only in the structured copy.
`sanitize_trace_text()` now parses JSON objects and arrays and applies the same recursive redaction.
This changes captured telemetry only; the tool response remains unchanged.

**Merge guidance:** retain the JSON text redaction tests in `tests/unit/mcpgateway/utils/test_trace_redaction.py`
until upstream provides equivalent protection. The Jaeger integration test exposed this gap using synthetic secrets.
