# Fork Customizations

This repository (`Garry2012/mcp-gateway`) is a fork of
[`IBM/mcp-context-forge`](https://github.com/IBM/mcp-context-forge).

The fork tracks upstream as closely as possible. It carries only the divergences below.
Keep UI changes limited to the functional fixes listed below. Submit fixes upstream and avoid branding or cosmetic changes.

Last updated: **2026-11-05**.

## Syncing with upstream

The 2026-11-05 integration targets upstream `e712b1b8e`. It imports 46 commits and retains every
divergence below except divergence 3, which upstream resolved. It adopts upstream's removal of all
repository-owned Rust (EPIC #5817), so `crates/`, the Cargo manifests and `rust-toolchain.toml` are gone.
`tests/live_gateway/test_call_sessions.py` builds its stub upstream server on `mcp.server.mcpserver`,
because upstream's `llmchat` extra no longer supplies `fastmcp`.

The integration adopts upstream's documented requirement to send `auth_type` when updating a
credential field. `PUT /gateways/{gateway_id}` and `PUT /a2a/{agent_id}` now return 422 when a
request sets `auth_token`, `auth_password` or `auth_header_value` without `auth_type`. Upstream
records this under Breaking Changes in commit `937011adf` (PR #7172).

### Deferred upstream issues

**`auth_value` updates without `auth_type` are silently ignored.** `GatewayUpdate` and
`A2AAgentUpdate` accept `auth_value` without `auth_type`, because
`validate_auth_type_required_for_credential_rotation` checks only `auth_token`, `auth_password`
and `auth_header_value` (`mcpgateway/schemas.py:4126` and `:6220`). `GatewayService.update_gateway`
and `A2AAgentService.update_agent` then keep the stored credential. The caller receives success and
the old credential stays. This differs from the documented rejection of the other three fields.
Upstream introduced the behaviour in `937011adf` (PR #7172).

The reproduction builds real Pydantic models and compares service behaviour against pre-sync code.
HTTP-level confirmation remains pending.
Evidence lives in untracked review artifacts, so a fresh clone does not carry it:
`.context/review_auth_value_probe.py` and
`.context/independent-sync-review-20261105/whole-sync-auth-comparison.log`.

**Follow-up:** confirm the behaviour through HTTP, then report it upstream. Ask upstream to reject
ambiguous `auth_value` updates for consistency. Keep `mcpgateway/services/gateway_service.py` and
`mcpgateway/services/a2a_service.py` byte-identical to upstream until upstream decides.

**The Vault plugin E2E suite skips without `fastmcp`.** Upstream's `llmchat` extra no longer
supplies `fastmcp`, and `plugins/vault/echo_mcp.py` imports it for `Context`, `FastMCP` and
`get_http_headers`. The five tests in `tests/e2e/test_vault_plugin_a2a_e2e.py` therefore skip at
`pytest.importorskip("fastmcp")`. The sync keeps `fastmcp` out of the gateway's dependencies.

The code itself is sound. A temporary environment that pins every gateway dependency to its
locked version and adds `fastmcp==4.0.10` runs all five tests green. `fastmcp` changes no locked
version and adds 17 packages, so no version conflict exists.

**Follow-up:** add `fastmcp` to a test-only dependency group, or port `plugins/vault/echo_mcp.py`
to the MCP SDK. Until then, run the suite in a separate environment.

The 2026-10-26 integration targeted upstream `85dabf0be` (1.1.0).
The published baseline matches deployed source `0cdfa2109`; temporary LLM Chat changes remain excluded.

Upstream rewrites historical commits. The ancestry reconciliation maps `51a4ee414` to `2dd1c487e` and accepts three example-redaction changes.
The subsequent merge imports the 23 newer commits without replaying equivalent history.

Request-root tracing suppresses background spans by default. Preserve HTTP request roots, call-ID grouping, and tool payload attributes.
Keep `OTEL_HTTPX_INSTRUMENTATION_ENABLED=true` in the healthcare profile for HTTP trace propagation.
The per-user MCP-server rate-limiter plugin remains disabled unless explicitly configured.
The healthcare profile uses the EU Langfuse endpoint and its existing Key Vault header reference.
The healthcare profile accepts both inbound protocol eras with `MCP_INBOUND_PROTOCOL_MODE=auto`.
It keeps `MCP_CLIENT_CONNECT_MODE=auto` for outbound connections to upstream MCP servers.
LLM Chat no longer reads the setting; see divergence 3.
Set it to `legacy` when an upstream server rejects modern discovery or omits its required cache metadata.
The current voice client retains its `2025-11-25` handshake. Modern clients can use `2026-07-28` discovery.
Restore `MCP_INBOUND_PROTOCOL_MODE=legacy` to roll back inbound acceptance.
This configuration does not enable upstream session reuse or change upstream protocol negotiation.

Upstream now resolves exact tool names first and permits an original-name fallback only when one accessible tool matches.
A virtual-server request cannot also select an upstream through `X-Context-Forge-Gateway-Id`.
Catalog cache metadata adds a database lookup for virtual-server discovery; measure its cost during validation.

The `upstream` remote has pushing disabled, so `git push upstream` fails loudly.

```bash
git fetch upstream
git checkout -b sync/upstream-<date> origin/main
git merge upstream/main
```

Use merge, not rebase. Merge resolves each conflict once and records the resolution in history.
Preserve upstream secret-scan audit decisions when the filename and finding hash match. Re-run the scan after resolving `.secrets.baseline`.

The live E2E module keeps the synchronous Playwright resource-renaming test after the asynchronous MCP tests.
It uses the SDK v2 `is_error` property and accepts both existing detached-tool denial messages.
Pagination tests inspect response headers to distinguish stateful session isolation from stateless scope reuse.
Both modes retain team, permission, and anonymous-access denial checks.
Upstream #7258 deleted the Rust session-isolation suite, including its removed-member and
revoked-role session denial cases. Port them into `tests/live_gateway/e2e/test_e2e.py` if the
fork relies on bounded session-reuse denial.
Preserve these test compatibility fixes until upstream includes them.

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
public-only deny cases. New handlers, including `completion/complete`, must use this helper.
Upstream helper references can merge without conflicts after a fork rename.
Submit this fix upstream, then drop this divergence when it merges.

### 3. LLM Chat on MCP SDK 2.x — RESOLVED 2026-11-05

Upstream moved to MCP SDK 2.x (#6868), but LLM Chat still used `langchain-mcp-adapters`, which
imports MCP 1.x APIs and fails at import time. Reported as
[IBM/mcp-context-forge#7090](https://github.com/IBM/mcp-context-forge/issues/7090).
The fork loaded tools through `langchain.mcp.MCPAdapter` over FastMCP transports until upstream
shipped its own fix.

Upstream PR #7332 (`260d1abcf`) addresses #7090. It loads tools with the MCP SDK client directly.
The 2026-11-05 integration took upstream's version and retired this divergence.
`mcpgateway/services/mcp_client_chat_service.py` is now identical to upstream.
`fastmcp`, `langchain[mcp]`, `MCPAdapter` and `_decline_elicitation` are gone.
The `llmchat` extra is upstream's, which lowers the `langchain-core` cap from `1.6.4` to `1.5.1`.

Upstream's loader takes no `mode` argument, so LLM Chat no longer reads
`MCP_CLIENT_CONNECT_MODE` and uses the MCP SDK default. The setting still governs outbound
gateway connections to upstream MCP servers.

One piece survives: `test_llmchat_dependencies_import_against_installed_mcp_sdk` in
`tests/unit/mcpgateway/services/test_mcp_client_chat_service_extended.py`. It imports the real
chat stack, so a future MCP SDK upgrade that breaks LLM Chat fails there. It was rewritten onto
`mcp.client.Client` when the adapter went away.

**Merge guidance:** keep that test. Expect no other fork delta in this area.

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
replaces the remaining `COPY --chmod=0755` line with `COPY` plus `RUN chmod 0755`.
Upstream #7359 deleted the native-extension stage that held the second one.
`deploy/scripts/02-build-images.sh` fails fast if a `COPY --chmod` line returns.

**Merge guidance:** if upstream adds a new `COPY --chmod` line, convert it to the same form.
Check new required settings (for example `DEFAULT_USER_PASSWORD`) against
`deploy/scripts/03-deploy-gateway.sh` before rollout.

The deployment scripts forward opt-in OTLP exporter settings. The healthcare Azure profile exports to Langfuse Cloud over HTTPS.
Keep `OTEL_EMIT_LANGFUSE_ATTRIBUTES=true` for payload export until upstream adopts backend-neutral attribute names.
The gateway identity reads exporter headers through a secret-specific Key Vault grant.
The dedicated Jaeger deployment, dashboard proxy, and deployment tests are retired.
Shared trace naming, propagation, redaction, and call-ID grouping remain in use by Langfuse.
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
until upstream provides equivalent protection. Regression tests exercise this gap with synthetic secrets.
JSON text that exceeds decoder depth or integer limits is replaced with an error marker before export.

### 6. Readable virtual-server tool traces

MCP request traces show the virtual server name and original tool name for every virtual server.
The transport reuses its authorization lookup for the server name and passes request trace context into tool invocation.
Trace naming adds no separate database lookup and occurs after tool authorization.

**Merge guidance:** preserve `ToolTraceContext`, `record_tool_trace_name`, and their transport integration until upstream provides equivalent behavior.
Run `tests/unit/mcpgateway/test_tool_trace_names.py` and `tests/live_gateway/test_call_sessions.py`.
Unit tests cover server renames and multiple servers. The live OTLP test verifies named roots and call-session grouping.

#### FastAPI request tracing ownership

FastAPI native tracing is disabled with `telemetry={"tracing": False}` on the gateway application.
`OpenTelemetryRequestMiddleware` owns HTTP request tracing and applies the transport-path filter.
Native tracing bypasses that filter and creates unwanted HTTP roots for static, administrative, and probe requests.
It also duplicates request tracing for MCP calls. Native dependency, endpoint, and serialization spans are intentionally omitted.
ContextForge tool spans, payload capture, call-session grouping, and HTTPX tracing retain their existing configuration.
FastAPI requires version 0.143.0 or later, which supports this setting and makes automatic exporter setup opt-in.
Only tracing is disabled because this correction concerns trace ownership. Native metrics and logs retain their defaults.
ContextForge currently registers no global meter or logger provider. Adding either can reactivate the native wrapper and requires a separate telemetry review.
This override applies to the gateway application, not the separate applications in `mcpgateway.translate`.
Translator tracing requires separate review because those applications do not share the gateway's request middleware.

**Merge guidance:** retain the override until upstream provides one HTTP tracing owner with equivalent filtering and propagation.
Run `tests/live_gateway/mcp/test_request_trace_policy.py` with observability extras.
The live collector checks excluded routes, remote parents, generated roots, payload capture, and tracing failures.
For FastAPI dependency, endpoint, or serialization timing, temporarily set `tracing` to `True` in an isolated non-production build.
Expect duplicate and unfiltered HTTP spans during that diagnostic run. Restore `False` when the investigation finishes.

### 7. Deferred dashboard loading and partial errors

Admin panels fetch content when visible instead of loading every panel at startup.
The shared `partialLoadErrors.js` handler replaces failed loading placeholders with actionable errors.
Server edit requests remain serialized to avoid connection bursts.

**Merge guidance:** preserve lazy loading and the shared partial-error handler during template updates.
Run `tests/unit/js/partialLoadErrors.test.js` and the CSP tests.
The Jaeger test's concurrent dashboard-load check is retired with that test.
