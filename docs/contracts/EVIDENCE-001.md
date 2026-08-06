# EVIDENCE-001 — Brand Migration Verification

Task B and Task C are complete at implementation commit `a639ff55`. Amendments 1
through 5 resolved all four blocking review findings. The command output below records
checks that were actually run; earlier failed baselines are retained because they show
the stop-and-report sequence that led to the amended contract.

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

Development-only environment values are redacted from the recorded command.

```console
$ JWT_SECRET_KEY=REDACTED \
  AUTH_ENCRYPTION_SECRET=REDACTED \
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

## Amendment 5 implementation and Task C

The branch was at the requested Architect commit before implementation:

```console
$ git rev-parse HEAD
a2c7ec6a75ec9557f2ebd37ce0b6143f6e2ce16d
exit=0
```

### Required brand tiers

These are exact result lines from the four post-implementation commands. Each command
also ran the protected-identifier guard shown after the tier results.

```console
$ scripts/check-brand.sh ui
PASS  [ui] Admin UI templates
PASS  [ui] Admin UI JavaScript
PASS  [ui] Static assets referenced by name
BRAND CHECK PASSED
exit=0

$ scripts/check-brand.sh runtime
PASS  [runtime] Application package (all emitted strings, descriptions, docstrings)
PASS  [runtime] Environment template
BRAND CHECK PASSED
exit=0

$ scripts/check-brand.sh assets
PASS  [assets] Logo/icon image references
BRAND CHECK PASSED
exit=0

$ scripts/check-brand.sh deploy
PASS  [deploy] Helm chart configuration, schema and templates
PASS  [deploy] Container and process configuration
PASS  [deploy] Infrastructure and provisioning
BRAND CHECK PASSED
exit=0

Protected identifiers (must still be present):
  OK    x-contextforge-* headers (699)
  OK    mcpContextForge Helm keys (978)
  OK    contextforge:runtime keys (25)
  OK    Rust crate name (20)
```

The contract-aware operator-document scan passed:

```console
PASS README.md, DEVELOPING.md, charts/*.md
exit=0
```

The full gate remains intentionally non-zero only because the deferred documentation
tree is included. It reported 1,029 indented legacy-brand lines under that failure:

```console
$ scripts/check-brand.sh
PASS  [ui] Admin UI templates
PASS  [ui] Admin UI JavaScript
PASS  [ui] Static assets referenced by name
PASS  [runtime] Application package (all emitted strings, descriptions, docstrings)
PASS  [runtime] Environment template
PASS  [docs] Top-level documentation
FAIL  [docs] User-facing documentation tree
PASS  [docs] Operator guides
PASS  [deploy] Helm chart configuration, schema and templates
PASS  [deploy] Container and process configuration
PASS  [deploy] Infrastructure and provisioning
PASS  [assets] Logo/icon image references
BRAND CHECK FAILED
indented_match_lines=1029
exit=1
```

### Python validation

The focused SIEM and configuration tests passed before the full suite. The full doctest,
lint/docstring gate, and pytest suite then produced:

```console
$ make doctest
1218 passed, 56 skipped, 6 warnings in 11.97s
exit=0

$ make ruff interrogate
All checks passed!
TOTAL: 5214 definitions, 2 missed, 5212 covered, 100.0%
RESULT: PASSED (minimum: 100.0%, actual: 100.0%)
exit=0

$ make test
21695 passed, 810 skipped, 2 xfailed, 492 warnings in 375.17s (0:06:15)
exit=0
```

The first full test run exposed one stale `security.txt` assertion and otherwise
completed successfully (21,694 passed). The assertion was migrated and the complete
rerun above passed.

### Build, configuration, and deployment syntax

```console
$ make build-ui
✓ 68 modules transformed.
✓ built in 4.19s
exit=0

$ make check-env
✅ .env validated successfully with no warnings.
exit=0

$ bash -n run.sh docker-entrypoint.sh run-gunicorn.sh
exit=0

$ docker compose -f docker-compose.yml config --quiet
exit=0

$ docker compose -f docker-compose.yml -f docker-compose.with-langfuse.yml config --quiet
exit=0
```

`make check-env` used redacted development-only values for the required secrets. Both
Compose commands printed only warnings about an unset `KEY_FILE_PASSWORD`.

The repository hygiene gate also completed successfully:

```console
$ make pre-commit
check for added large files..............................................Passed
check json...............................................................Passed
check yaml...............................................................Passed
check toml...............................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
interrogate..............................................................Passed
IBM detect secrets.......................................................Passed
exit=0
```

The secret baseline regeneration reviewed 529 findings and reported no live,
unaudited, or real secrets.

### Live HTTP identity

With the development server running, the login response, wordmark markup, and
authenticated OpenAPI document returned:

```console
<title>Sign In - MCP Gateway</title>
MCP <span class="text-blue-200">Gateway</span>
MCP Gateway
http_checks_exit=0
```

The first line is the login page title, the second is the rendered login wordmark
markup, and the third is `openapi.json`'s `info.title`.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `make install-dev` | PASS | Exit 0; development dependencies installed and the UI bundle built. |
| `scripts/check-brand.sh ui` | PASS | Exit 0. |
| `scripts/check-brand.sh runtime` | PASS | Exit 0. |
| `scripts/check-brand.sh assets` | PASS | Exit 0. |
| `scripts/check-brand.sh deploy` | PASS | Exit 0. |
| Protected-identifier guard | PASS | 699 headers, 978 Helm-key occurrences, 25 Redis-key occurrences, 20 crate-name occurrences. |
| `README.md`, `DEVELOPING.md`, `charts/*.md` clean | PASS | Contract-aware scan exit 0. |
| Full brand gate | EXPECTED FAIL | Exit 1 only for `docs/docs/**`, deferred to CONTRACT-002. |
| `make ruff interrogate` | PASS | Exit 0; Ruff clean and interrogate 100.0%. |
| `make test` | PASS | 21,695 passed. |
| `make doctest` | PASS | 1,218 passed. |
| `make build-ui` | PASS | 68 modules transformed; exit 0. |
| Login title HTTP check | PASS | `Sign In - MCP Gateway`. |
| OpenAPI title HTTP check | PASS | `info.title` is `MCP Gateway`. |
| Human light/dark wordmark review | NOT VERIFIED | Requires product-owner visual judgment under CONTRACT-001 Task C. |
| Human login-page visual review | NOT VERIFIED | Requires product-owner visual judgment under CONTRACT-001 Task C. |

## Not verified

- Human approval of the light/dark admin wordmarks and login-page visual coherence.
- Helm rendering with the `helm` binary; it was unavailable. Chart schema and both
  Compose configurations were validated, and the full suite skipped the three chart
  tests that require Helm.
- End-to-end CEF/LEEF delivery to a connected SIEM. Unit tests cover configurable
  vendor/product values, pipe and backslash escaping, and newline removal.
- The deferred `docs/docs/**` migration outside `docs/docs/manage/dcr.md`; CONTRACT-002
  owns that decision.

## Findings routed back to architect

- B-001 through B-004 were accepted and resolved by Amendments 1 through 5. Task B was
  completed against the resulting executable gate.
- M-003 is non-blocking: Amendment 3 requires a SIEM operator release note, but every
  current release-note destination is historical, deferred, or assigned to the
  Architect. `REVIEW-001.md` records the routing gap without changing an out-of-scope
  file.
