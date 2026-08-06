# EVIDENCE-001 — Brand Migration Verification

Task C was not started. Task A found a blocking contract-scope defect and
`CONTRACT-001` requires stopping before Task B. The command output below records only
the review-stage checks that were actually run.

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

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `scripts/check-brand.sh` | FAIL | Baseline output above; exit 1. Task B not started. |
| `make ruff interrogate` | NOT RUN | Stopped after Task A contract blocker. |
| `make test` | NOT RUN | Stopped after Task A contract blocker. |
| `make doctest` | FAIL | Output above; exit 2, one stale brand assertion. |
| `make build-ui` | NOT RUN as Task C | `make install-dev` built the bundle successfully, but the post-change acceptance run did not occur. |
| Login title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| OpenAPI title HTTP check | NOT RUN | No Task B build and no `make dev` acceptance server started. |
| Human light/dark wordmark review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |
| Human login-page visual review | NOT RUN | Wordmark was not implemented because work stopped after Task A. |

## Not verified

No Task B changes were made. Lint, the full test suite, the post-change UI build, live
HTTP responses, and visual coherence were therefore not verified.

## Findings routed back to architect

The brand gate omits live product-identity and operator-documentation surfaces and can
hide visible legacy branding when a protected identifier occurs on the same line. See
`docs/contracts/REVIEW-001.md` B-001 for the required scope decision.
