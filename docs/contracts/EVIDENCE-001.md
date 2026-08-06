# EVIDENCE-001 — Brand Migration Verification

Task C was not started. Amendments 1 through 4 resolved the first three review blockers.
The baseline at `49fea8dd` found a fourth contract blocker before implementation: the
new deployment tier reports protected prefix-qualified keys and bare deployment
identifiers as brand text. The command output below records only checks that were
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

### Amendment 4 deployment-tier baseline

The branch was at the requested Architect commit, and the required development install
completed successfully:

```console
$ git rev-parse HEAD
49fea8dd0a0126b7a1c68ceb6c5ab48b02e40a0b

$ make install-dev
✅  Virtual env already exists, skipping creation.
Resolved 311 packages in 860ms
   Building mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
      Built mcp-contextforge-gateway @ file:///Users/garima/conductor/workspaces/mcp-gateway/pyongyang
⏭️  Rust builds disabled (set ENABLE_RUST_BUILD=1 to enable)
🔨 Building Admin UI bundle...
✓ 68 modules transformed.
✓ built in 5.42s
exit=0
```

The deploy command produced 93 match lines. These are exact excerpts showing the
identifier false positives and the final result:

```console
$ scripts/check-brand.sh deploy
Brand check: 'ContextForge' -> 'MCP Gateway'
===========================================================

FAIL  [deploy] Helm chart configuration, schema and templates
        charts/README.md:755:The feature is **off by default**. Switch `hpa` to `enabled: true` in the `mcpContextForge` section of `values.yaml` to enable.
        charts/mcp-stack/values.schema.json:208:    "mcpContextForge": {

FAIL  [deploy] Container and process configuration
        docker-compose.with-langfuse.yml:100:      - OTEL_RESOURCE_ATTRIBUTES=${OTEL_RESOURCE_ATTRIBUTES:-deployment.environment=docker,service.namespace=contextforge}
        docker-compose.with-langfuse.yml:162:      LANGFUSE_INIT_ORG_ID: ${LANGFUSE_INIT_ORG_ID:-contextforge}

FAIL  [deploy] Infrastructure and provisioning
        ansible/ocp/README.md:52:| `ocp_namespace` | `contextforge` | Namespace and Helm release name |
        ansible/ocp/vars/defaults.yml:6:ocp_namespace: contextforge

Protected identifiers (must still be present):
  OK    x-contextforge-* headers (697)
  OK    mcpContextForge Helm keys (965)
  OK    contextforge:runtime keys (25)
  OK    Rust crate name (20)

BRAND CHECK FAILED
Fix the FAIL lines above, or route a scope change back to the architect.
exit=1
```

The OpenShift value is consumed as both namespace and Helm release identity:

```console
$ git grep -n 'ocp_namespace' -- ansible/ocp/vars/defaults.yml ansible/ocp/playbooks/deploy.yml ansible/ocp/playbooks/uninstall.yml
ansible/ocp/playbooks/deploy.yml:45:          helm install {{ ocp_namespace }} {{ ocp_chart_path }}
ansible/ocp/playbooks/deploy.yml:46:          -n {{ ocp_namespace }}
ansible/ocp/playbooks/deploy.yml:61:          -l app={{ ocp_namespace }}-mcp-stack-mcpgateway
ansible/ocp/playbooks/deploy.yml:77:        namespace: "{{ ocp_namespace }}"
ansible/ocp/playbooks/uninstall.yml:52:        cmd: "helm uninstall {{ ocp_namespace }} -n {{ ocp_namespace }}"
ansible/ocp/vars/defaults.yml:6:ocp_namespace: contextforge
exit=0
```

The other bare matches are configured as telemetry/resource identifiers:

```console
$ git grep -n 'service.namespace=contextforge\|LANGFUSE_INIT_ORG_ID.*contextforge' -- docker-compose.with-langfuse.yml .env.example
.env.example:3349:# LANGFUSE_INIT_ORG_ID=contextforge
docker-compose.with-langfuse.yml:100:      - OTEL_RESOURCE_ATTRIBUTES=${OTEL_RESOURCE_ATTRIBUTES:-deployment.environment=docker,service.namespace=contextforge}
docker-compose.with-langfuse.yml:162:      LANGFUSE_INIT_ORG_ID: ${LANGFUSE_INIT_ORG_ID:-contextforge}
exit=0
```

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `make install-dev` | PASS | Exit 0 at `49fea8dd`; UI bundle built in 5.42s. |
| `scripts/check-brand.sh ui` | FAIL | Baseline has 9 match lines; no implementation edits made. |
| `scripts/check-brand.sh runtime` | FAIL | Baseline has 149 match lines; no implementation edits made. |
| `scripts/check-brand.sh assets` | FAIL | Baseline has the six expected logo references. |
| `scripts/check-brand.sh deploy` | FAIL | Exit 1; alongside real brand text, it reports the protected Helm key and stateful deployment identifiers shown above. |
| Protected-identifier guard | PASS | 697 headers, 965 Helm-key occurrences, 25 Redis-key occurrences, 20 crate-name occurrences. |
| `README.md`, `DEVELOPING.md`, `charts/*.md` clean | FAIL | Baseline remains unmodified; the chart guide also contains the B-004 key-only false positive. |
| `make ruff interrogate` | NOT RUN | Stopped on Task B contract blocker B-004. |
| `make test` | NOT RUN | Stopped on Task B contract blocker B-004. |
| `make doctest` | FAIL | Output above; exit 2, one stale brand assertion. |
| `make build-ui` | NOT RUN as Task C | `make install-dev` built the bundle successfully, but the post-change acceptance run did not occur. |
| Login title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| OpenAPI title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| Human light/dark wordmark review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |
| Human login-page visual review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |

## Not verified

No Task B implementation changes were made after Amendment 4. Lint, the full test
suite, the post-change UI build, live HTTP responses, and visual coherence were
therefore not verified.

## Findings routed back to architect

Amendments 1 through 4 resolved B-001 through B-003. The deployment gate now includes
the correct surfaces, but its suffix-only shape rule reports a protected Helm key and
bare stateful identifiers as brand text. See `docs/contracts/REVIEW-001.md` B-004 for
the remaining gate and compatibility decisions.
