# EVIDENCE-001 — Brand Migration Verification

Task C was not started. Amendments 1 and 2 resolved the first two review blockers. The
next inventory at `ce3e0ee7` found a third scope blocker before implementation: default
Helm values override the migrated runtime with the legacy brand, while the definition of
done scans only chart Markdown. The command output below records only checks that were
actually run.

## Commands run

### Development dependency installation

```console
$ make install-dev
✅  Virtual env already exists, skipping creation.
Resolved 311 packages in 976ms
   Building mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
      Built mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
Prepared 1 package in 2.61s
Uninstalled 1 package in 1ms
Installed 8 packages in 12ms
⏭️  Rust builds disabled (set ENABLE_RUST_BUILD=1 to enable)
🔨 Building Admin UI bundle...
✓ 68 modules transformed.
✓ built in 4.54s
exit=0
```

The installer also printed npm package and compressed-asset inventories; they are not
acceptance results. `git status --short` was empty after installation.

### Baseline brand gate

The full command produced 2,011 lines because it enumerated every unmatched occurrence.
These are exact excerpts from its output, including the final result:

```console
$ scripts/check-brand.sh
Brand check: 'ContextForge' -> 'MCP Gateway'
===========================================================

PASS  [ui] Admin UI JavaScript
FAIL  [assets] Logo/icon image references
        mcpgateway/templates/admin.html:246:            <img src="{{ root_path }}/static/contextforge-logo.png" alt="ContextForge logo" class="h-8 dark:hidden" />
        mcpgateway/templates/admin.html:247:            <img src="{{ root_path }}/static/contextforge-logo-white.png" alt="ContextForge logo" class="h-8 hidden dark:block" />
        mcpgateway/templates/admin.html:250:            <img src="{{ root_path }}/static/contextforge-icon.png" alt="ContextForge icon" class="h-8 w-8 dark:hidden" />
        mcpgateway/templates/admin.html:251:            <img src="{{ root_path }}/static/contextforge-icon-white.png" alt="ContextForge icon" class="h-8 w-8 hidden dark:block" />
        mcpgateway/templates/change-password-required.html:261:                  src="{{ root_path }}/static/contextforge-logo-white.png"
        mcpgateway/templates/login.html:221:                  src="{{ root_path }}/static/contextforge-logo-white.png"

Protected identifiers (must still be present):
  OK    x-contextforge-* headers (692)
  OK    mcpContextForge Helm keys (955)
  OK    contextforge:runtime keys (22)
  OK    Rust crate name (17)

BRAND CHECK FAILED
Fix the FAIL lines above, or route a scope change back to the architect.
exit=1
```

### Full doctest target

```console
$ JWT_SECRET_KEY=contract-review-development-secret-key-2026 \
  AUTH_ENCRYPTION_SECRET=contract-review-encryption-secret-2026 \
  ENVIRONMENT=development make doctest
🧪 Running doctest on all modules...
bringing up nodes...
bringing up nodes...

=================================== FAILURES ===================================
_ [doctest] mcpgateway.cache.session_registry.SessionRegistry.handle_initialize_logic _
2139             >>> result = asyncio.run(reg.handle_initialize_logic(body))
2140             >>> result.protocol_version
2141             '2025-06-18'
2142             >>> result.server_info.name
Expected:
    'ContextForge'
Got:
    'MCP Gateway'

/Users/garima/conductor/workspaces/mcp-gateway/pyongyang/mcpgateway/cache/session_registry.py:2142: DocTestFailure
=========================== short test summary info ============================
SKIPPED [56] .venv/lib/python3.12/site-packages/_pytest/doctest.py:458: all tests skipped by +SKIP option
FAILED mcpgateway/cache/session_registry.py::mcpgateway.cache.session_registry.SessionRegistry.handle_initialize_logic
1 failed, 1217 passed, 56 skipped, 6 warnings in 9.81s
make: *** [doctest] Error 1
exit=2
```

### Protected-identifier comparison around the implementation commit

```console
$ # git grep counts at ea3cf45d^ and ea3cf45d
ea3cf45d^
690 x-contextforge-
953 mcpContextForge
20 contextforge:runtime:
15 contextforge_mcp_runtime
50 ContextForge Contributors
1313 MCP-CONTEXT-FORGE
2036 mcp-context-forge
1604 github.com/IBM
ea3cf45d
690 x-contextforge-
953 mcpContextForge
20 contextforge:runtime:
15 contextforge_mcp_runtime
50 ContextForge Contributors
1313 MCP-CONTEXT-FORGE
2036 mcp-context-forge
1604 github.com/IBM
exit=0
```

### Amendment 1 baseline tier gates

The branch was already at the requested Architect commit after refresh:

```console
$ git fetch origin
$ git rev-parse HEAD
894c8c5cd665e197d64f9df6db13b5b984fe9fce
exit=0
```

The UI and asset gates still reported the six known logo references and the iframe
harness. The runtime gate additionally reported identifiers that cannot be changed
under the cosmetic-only contract. These are exact excerpts:

```console
$ scripts/check-brand.sh runtime
Brand check: 'ContextForge' -> 'MCP Gateway'
===========================================================

FAIL  [runtime] Application package (all emitted strings, descriptions, docstrings)
        mcpgateway/auth_context.py:143:_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT = "contextforge-internal-mcp-runtime-v1"
        mcpgateway/services/tool_service.py:3767:                    "contextforge.gateway_id": str(gateway.id),
        mcpgateway/services/tool_service.py:3768:                    "contextforge.runtime": "python",
        mcpgateway/services/tool_service.py:3769:                    "contextforge.transport": "streamablehttp",
        mcpgateway/transports/streamablehttp_transport.py:310:class ContextForgeMCPServer(Server[Any]):
        mcpgateway/transports/rust_mcp_runtime_proxy.py:46:_CONTEXTFORGE_SERVER_ID_HEADER = "x-contextforge-server-id"

Protected identifiers (must still be present):
  OK    x-contextforge-* headers (695)
  OK    mcpContextForge Helm keys (959)
  OK    contextforge:runtime keys (25)
  OK    Rust crate name (20)

BRAND CHECK FAILED
Fix the FAIL lines above, or route a scope change back to the architect.
exit=1
```

Cross-runtime source inspection confirmed that the authentication derivation value is
shared verbatim:

```console
$ git grep -n '_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT\|contextforge-internal-mcp-runtime-v1' -- .
crates/mcp_runtime/src/lib.rs:100:const INTERNAL_RUNTIME_AUTH_CONTEXT: &str = "contextforge-internal-mcp-runtime-v1";
mcpgateway/auth_context.py:87:    _INTERNAL_MCP_RUNTIME_AUTH_CONTEXT   (constant string used to derive headers)
mcpgateway/auth_context.py:143:_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT = "contextforge-internal-mcp-runtime-v1"
mcpgateway/auth_context.py:408:    material = f"{secret}:{_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT}".encode("utf-8")
tests/unit/mcpgateway/middleware/test_token_scoping.py:31:    expected = hashlib.sha256(f"{secret}:contextforge-internal-mcp-runtime-v1".encode("utf-8")).hexdigest()
exit=0
```

### Amendment 2 Helm deployment inventory

The required development installation completed successfully before this inventory:

```console
$ make install-dev
✅  Virtual env already exists, skipping creation.
Resolved 311 packages in 1.06s
   Building mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
      Built mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
Prepared 1 package in 2.47s
Uninstalled 1 package in 1ms
Installed 1 package in 9ms
⏭️  Rust builds disabled (set ENABLE_RUST_BUILD=1 to enable)
🔨 Building Admin UI bundle...
✓ 68 modules transformed.
✓ built in 4.16s
exit=0
```

The chart inventory shows active legacy defaults and live operator surfaces outside the
gate:

```console
$ git grep -nI -E '(^|[^[:alnum:]])ContextForge([^A-Z_.:-]|$)' -- charts/mcp-stack/values.yaml charts/mcp-stack/values.schema.json charts/mcp-stack/templates
charts/mcp-stack/templates/NOTES.txt:71:  - ContextForge    : {{ .Values.mcpContextForge.replicaCount }} replica(s) - {{ .Values.mcpContextForge.image.repository }}:{{ .Values.mcpContextForge.image.tag }}
charts/mcp-stack/templates/NOTES.txt:137:{{- /* ════════════  ContextForge  ════════════ */}}
charts/mcp-stack/templates/NOTES.txt:138:🔗 **ContextForge**
charts/mcp-stack/templates/configmap-monitoring.yaml:233:      - name: ContextForge Dashboards
charts/mcp-stack/templates/configmap-monitoring.yaml:235:        folder: ContextForge
charts/mcp-stack/templates/deployment-mcpgateway.yaml:2:# DEPLOYMENT - ContextForge (Gateway)
charts/mcp-stack/templates/platform/ocp/route.yaml:4:  This is the preferred way to expose ContextForge on OpenShift. The standard
charts/mcp-stack/values.schema.json:260:              "default": "ContextForge"
charts/mcp-stack/values.schema.json:2230:      "description": "ContextForge Gateway configuration"
charts/mcp-stack/values.yaml:221:    APP_NAME: ContextForge            # public-facing name of the gateway
charts/mcp-stack/values.yaml:600:      # ContextForge is a private API gateway
charts/mcp-stack/values.yaml:870:    # SMTP_FROM_NAME: "ContextForge"
charts/mcp-stack/values.yaml:902:    DCR_CLIENT_NAME_TEMPLATE: "ContextForge ({gateway_name})" # template for client_name in DCR requests
exit=0
```

The active application values are injected into the deployment:

```console
$ sed -n '20,24p' charts/mcp-stack/templates/configmap-gateway.yaml
{{- /* Iterate over every key in mcpContextForge.config */}}
{{- range $key, $val := .Values.mcpContextForge.config }}
  {{ $key }}: {{ $val | quote }}
{{- end }}
{{- end }}
exit=0
```

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `scripts/check-brand.sh` | FAIL | Baseline tiers remain failing; Task B stopped on B-003 before edits. |
| `make ruff interrogate` | NOT RUN | Stopped on Task B contract blocker B-003. |
| `make test` | NOT RUN | Stopped on Task B contract blocker B-003. |
| `make doctest` | FAIL | Output above; exit 2, one stale brand assertion. |
| `make build-ui` | NOT RUN as Task C | `make install-dev` built the bundle successfully, but the post-change acceptance run did not occur. |
| Login title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| OpenAPI title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| Human light/dark wordmark review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |
| Human login-page visual review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |

## Not verified

No Task B implementation changes were made after Amendment 2. Lint, the full test
suite, the post-change UI build, live HTTP responses, and visual coherence were
therefore not verified.

## Findings routed back to architect

Amendments 1 and 2 resolved B-001 and B-002. Default Helm values still override the
migrated Python identity, and live Helm/Grafana templates retain the old brand outside
the gate. See `docs/contracts/REVIEW-001.md` B-003 for the remaining scope decision.
