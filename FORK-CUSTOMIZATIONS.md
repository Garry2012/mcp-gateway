# Fork Customizations

This repository (`Garry2012/mcp-gateway`) is a fork of
[`IBM/mcp-context-forge`](https://github.com/IBM/mcp-context-forge).

This file records everything that deliberately diverges from upstream, and how to keep
the fork in sync. It exists so that divergences are discoverable in one place rather
than discovered by surprise during a merge.

Last updated: **2026-09-17**. This record covers the fork snapshot and the separate
integration branch below; an integration entry does not mean it has been deployed.

## Syncing with upstream

The `upstream` remote is configured with pushing disabled, so an accidental
`git push upstream` fails loudly instead of attempting to write to IBM's repository.

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

**Use merge, not rebase, for upstream syncs.** Rebase rewrites the fork's commits on top
of upstream every time, which means re-resolving the same conflicts on every sync,
indefinitely. Merge resolves each conflict once and records the resolution permanently
in history.

This differs from the PR workflow described in `AGENTS.md`, which uses rebase. That
applies to feature branches within a single repository, which is a different situation
from tracking a fork.

### Latest integration: 2026-09-15

Merge `13a692e3c` on `Garry2012/upstream-integration-20260915` integrates upstream
`2af962ac8` (1.0.10) with fork snapshot `3643f5e9f`. The original workspace branch,
`Garry2012/gpt5-reasoning-effort-400-error`, retained `3643f5e9f` as its code
baseline. The integration was reviewed and tested locally; it was **not pushed or
deployed to Azure as part of that merge**.

- Preserved branding, CSP-safe Alpine components, tool observability, execution
  timelines and Azure build compatibility.
- Accepted upstream's removal of deprecated `mcpgateway/wrapper.py`; do not restore
  it merely to preserve former branding edits.
- Kept upstream's live input-schema validation, adding safe observation of rejected
  arguments (§5), and passwordless-user migration, with type-only corrections (§9).
- Resolved the secrets-baseline conflict using upstream's audited baseline, then
  regenerated it through the normal detection workflow.

Validation covered the full Python suite, JavaScript tests and UI builds, live
tool observations, protocol/RBAC on a two-worker Python gateway with PostgreSQL
and Redis, and SQLite/PostgreSQL migration round trips. Lint, package checks and
pre-commit passed. Full Bandit retained upstream's low-severity findings; the Rust
runtime and Azure AMD64 build were outside this validation. Detailed results and
waivers are in the integration worktree's local `.context/integration-verification.md`
(not committed).

**Deployment gates:** provision the dedicated default-user password secret (§7),
build the reviewed commit for Azure AMD64, and check real registered-tool payloads
against stricter input schemas. Keep stateless sessions enabled and session
affinity disabled, matching the validated deployment configuration. Optional
multi-worker stateful/affinity tests showed intermittent `Session terminated`
errors that also reproduced on the pre-merge source image; this remains unresolved.

### Repository configuration

Applied via `git config --local` (shared across all worktrees):

| Setting | Value | Why |
|---|---|---|
| `rerere.enabled` | `true` | Records conflict resolutions and replays them on recurrence |
| `rerere.autoupdate` | `true` | Stages replayed resolutions automatically |
| `fetch.prune` | `true` | Removes local refs for deleted upstream branches |
| `pull.ff` | `only` | Prevents accidental implicit merge commits on `git pull` |
| `merge.conflictstyle` | `zdiff3` | Shows the common ancestor in conflict markers, which makes resolution far easier |

`rerere` matters most here. The fork's largest divergence is a deletion (see below), and
deletions conflict with any upstream edit to the deleted lines. Those conflicts are
trivial to resolve but would otherwise recur on every sync.

## Upstream churn in files we modify

Measured over the 12 months preceding 2026-08-06. This is the data the divergence
strategy is based on.

| File | Upstream commits | Our change | Conflict risk |
|---|---|---|---|
| `mcpgateway/services/email_notification_service.py` | 5 | 4 strings | Low |
| `mcpgateway/templates/login.html` | 23 | title, one footer string | Moderate — see below |
| `mcpgateway/templates/admin.html` | 240 | 5 strings | Low, because we only touch strings |
| `mcpgateway/config.py` | 261 | 3 defaults | Low, same reason |
| `mcpgateway/main.py` | high | 3 strings | Low, same reason |

Upstream velocity is roughly 4 commits per day.

Re-measured over the 90 days preceding 2026-08-07, for the files touched by the
observability fixes (divergence 3):

| File | Upstream commits / 90d | Our change | Conflict risk |
|---|---|---|---|
| `templates/observability_partial.html` | 2 | 434 lines replaced by 1 | Low frequency, high cost if it hits |
| `templates/observability_{metrics,tools,prompts,resources}.html` | 1 each | script block removed, `x-data` renamed | Low |
| `admin_ui/tabs.js` | 4 | 14 lines | Low |
| `admin_ui/alpine-setup.js` | 3 | 10 lines | Low |
| `templates/admin.html` | 26 | 14 lines (Roots menu only) | Moderate frequency, tiny surface |
| `services/tool_service.py` | 20 | 29 lines in two hunks | Moderate frequency, tiny surface |

The two high-churn files carry deliberately small, localised hunks. The large rewrite
sits in the file upstream touches about twice a quarter, which is the trade we wanted.

These are historical measurements, not the current total fork diff. The changes
in §5–6 increase the tool-service and admin-observability surface; review their
shared helpers and regression tests on each future sync.

### login.html is the hot spot

Of the last 8 upstream commits to `login.html`, **6 modified lines 7-13** — the
`<head>`: Content Security Policy, stylesheet links, JS bundling. Our `<title>` change
sits at line 6, immediately adjacent. Git's default three-line context window means
adjacent edits conflict, not only overlapping ones, so expect to resolve this one
occasionally. The resolution is trivial (keep both changes), and `rerere` replays it
after the first time.

Three of those 8 commits also touched the right-hand feature panel, including
`c18218c9`, *"[CHORE][UI]: Consistent ContextForge logo and branding"* — worth knowing,
because upstream periodically does its own branding passes over that block.

## Divergences

### 1. Brand: ContextForge to MCP Gateway

Status: **implemented**, except logo assets. Design:
`docs/superpowers/specs/2026-08-06-mcp-gateway-ui-rebrand-design.md`.

Text only. Page titles, visible UI strings, email subjects and sender name, MCP
instructions advertised to clients, and three configuration defaults (`app_name`,
`smtp_from_name`, `dcr_client_name_template`).

**Deliberately not renamed**, because they are identifiers rather than brand text and
renaming breaks things:

| Category | Reason |
|---|---|
| `x-contextforge-*` HTTP headers | Wire protocol shared with the Rust runtime crate |
| `mcpContextForge.*` Helm value keys | Renaming invalidates existing `values.yaml` files |
| `contextforge:runtime:*` Redis keys | Cross-instance coordination; renaming mid-deploy splits the cluster |
| `contextforge_mcp_runtime` crate name | Cargo build identifier |
| "ContextForge Contributors" copyright | Upstream's legal attribution |

Docstrings and code comments were also left alone — not user-visible, and changing them
would put a large diff across the highest-churn files for no benefit.

**Outstanding:** six references to ContextForge logo *image files* remain in
`login.html`, `change-password-required.html`, and `admin.html`. Those pages still
display the ContextForge wordmark. Resolving this needs a logo asset or a switch to a
text wordmark.

### 2. Color theme

Status: **not pursued.**

A graphite-and-amber theme was designed and then dropped in favour of a text-only
rebrand. The UI keeps upstream's indigo/violet palette.

If revisited, the recommended approach is to redefine what the palette names resolve to
in `tailwind.config.js` rather than rewriting the roughly 1,629 utility class usages to a
new `brand-*` scale. Upstream modified color classes in `admin.html` 94 times in 12
months, so a rename would conflict on nearly every sync, whereas `tailwind.config.js`
was touched twice all year.

### 3. Observability admin UI — CSP-safe Alpine fixes

Status: **implemented**, and submitted upstream as
[#6126](https://github.com/IBM/mcp-context-forge/pull/6126) (Closes #6055) and
[#6127](https://github.com/IBM/mcp-context-forge/pull/6127) (Closes #6054).
If both merge, this divergence disappears on the next sync.

**Upstream status, checked 2026-09-17: both still OPEN, neither merged.**
Continue carrying the fixes and guard tests until upstream supplies equivalent
behavior. Re-check the PR status when updating this file rather than trusting
this dated status.

These are **bug fixes to upstream code**, not customisations. Every defect was verified
present in `upstream/main`; our fork had never touched `tabs.js` or any observability
template beforehand.

#### The constraint that causes all of it

The admin UI bundles the **CSP-safe Alpine build** (`@alpinejs/csp`, see
`admin_ui/alpine-setup.js:1`). Its expression parser is far stricter than the default
build, and — critically — **it fails silently**: the component initialises as `{}` with
no exception, so the symptom is a blank panel making no network request, which reads as
a backend problem.

Established empirically in a browser, not from documentation:

| Form | CSP build |
|---|---|
| `{ a: 1, cfg: { x: 2 } }` — plain data, nested | parses |
| property access, method calls, ternary, comparison, concat, index (in directives) | fine |
| `{ a: 1, greet() {…} }` — any function inside an inline `x-data` | **whole object fails** |
| `x-data="createFoo()"` where the factory is on `window` | **fails** |
| `x-data="overflowMenu('table')"` where the name **is registered** | fine — the call form is not the problem |
| optional chaining `a?.b` | **fails** — `Unexpected token: PUNCTUATION "."` |
| template literal `` `${a} ${b}` `` | **fails** — `Unexpected token: OPERATOR` |

Note `Alpine.evaluate()` uses a *different* code path from directive compilation and
reports false negatives. Trust the live console error count, not a probe built on it.

#### What changed

- `observability_partial.html` — the ~420-line inline `x-data` moved to
  `admin_ui/components/observability-dashboard.js`, registered via `Alpine.data()`.
  The old `x-init` body became the component's `init()`.
- `observability_{metrics,tools,prompts,resources}.html` — same treatment; their
  `window.createXController` factories became registered components.
- 12 optional-chaining and 10 template-literal directives rewritten to supported forms.
- `tabs.js` — `window.chartRegistry` corrected to `window.Admin.chartRegistry`.
- `admin.html` — Roots overflow menu: the `:style` template literal and three
  `window.Admin?.viewRoot?.()` handlers, which silently disabled View/Edit/Export.

#### Resolving a conflict here

If upstream edits `observability_partial.html`, the merge is mechanical:

1. Keep our one-line `<div … x-data="observabilityDashboard">`. Never restore an inline
   object literal — it will silently break the panel again.
2. Port upstream's **markup** changes into the template body as normal.
3. Port upstream's **JavaScript** changes into
   `admin_ui/components/observability-dashboard.js`, not the template.
4. If upstream's new markup uses `?.` or a template literal in a directive, rewrite it:
   `a?.b || 'x'` becomes `a && a.b ? a.b : 'x'`, and `` `${a} ${b}` `` becomes
   `a + ' ' + b`.
5. Run `pytest tests/unit/mcpgateway/test_template_alpine_csp.py` — it will name the
   file and line of anything still unsupported.

The same applies to the four sub-view templates and their component files.

#### The guard tests are the safety net

`tests/unit/mcpgateway/test_template_alpine_csp.py` fails the build if any of these
reappear. Since upstream still writes in the pre-CSP style, **expect these tests to fail
on some future merge** — that is the intended behaviour, not a broken test. A loud
failure beats a silently blank dashboard. Fix the merged code, do not weaken the guard.

Each guard was verified to fail on the pre-fix code, so they are known to be capable of
failing rather than merely green today.

#### Merge reality check

A dry-run merge of `upstream/main` on 2026-08-07 (2 commits ahead) was **clean, zero
conflicts**, with all fixes intact and all guard tests passing. Merge often — small
frequent merges are cheap; `admin.html` at 26 commits a quarter is not something to let
accumulate.

### 4. RBAC: team-scoped admins can reach the Admin UI

Status: **implemented** in this fork (PR #16). **Not yet submitted upstream.**

This is a **bug fix to upstream code**, not a customisation. It is also a
documentation contradiction, which makes it a strong upstream candidate:
`docs/docs/manage/rbac.md` lists `admin.dashboard` / `admin.overview` as
`team_admin`'s first two permissions, and
`docs/docs/architecture/multitenancy.md` states the Admin UI uses
"permission-based rendering" — yet a user whose only admin-bearing role is
team-scoped was rejected with `403 Admin privileges required`.

#### Cause

`AdminAuthMiddleware` calls `PermissionService.has_admin_permission()` with the
`team_id` parsed from the request query string. The bare `/admin` entry point
carries no `team_id`, so `team_id is None`, and `_get_user_roles()` then returns
only global, personal and `scope_id=NULL` team roles. A `team_admin` assigned to
a specific team is excluded, so no `admin.*` permission is found. The `?team_id=`
path already worked — only the bare entry point was missed, and the code comment
calls the no-team branch "(original behavior)", suggesting an incomplete
migration when multi-tenancy was layered on.

#### What changed

`mcpgateway/services/permission_service.py` — `has_admin_permission()` now passes
`include_all_teams=True` when no team context is supplied, so the user's real
team roles are considered.

Safe because both guards already existed in `_get_user_roles()`:

- **Personal-team roles stay excluded** under `include_all_teams`. Every user is
  auto-granted `team_admin` on their personal team, so including them would give
  every user admin-UI access.
- **`token_teams` narrowing still applies**, so public-only tokens
  (`token_teams=[]`) gain no team roles.

Blast radius is small: `has_admin_permission()` has only two callers, both
admin-UI access (`main.py` middleware, and the login-page redirect in
`admin.py`). The separate `check_admin_permission()` — used by
`require_admin_permission()`, which guards e.g.
`POST /admin/gateways/{id}/transfer-ownership` — is **unchanged** and requires
`admin.system_config` / `admin.user_management` / `admin.security_audit` / `*`,
not `admin.dashboard`.

#### Deliberate consequence

`viewer` and `developer` also carry `admin.dashboard`, so **any** team member can
now open the Admin UI, not just team admins. That matches the documented
permission-based rendering, and was verified: a throwaway `viewer` on a team
reached the console, saw only that team's gateways (not another tenant's), and
was refused every write, every admin surface (`observability`, `admin/logs`,
`admin/users/search`), member management, and ownership transfer — all 403.

#### Resolving a conflict here

If upstream edits `has_admin_permission()`, keep the `include_all_teams=(team_id
is None)` argument. Do **not** "simplify" it back to a bare call — that silently
restores the 403 for every team-scoped admin. The regression tests in
`tests/unit/mcpgateway/services/test_permission_service.py` (four cases: widened
lookup, team-scoped lookup, denial without `admin.*`, public-only token) will
fail loudly if it is removed.

### 5. Tool execution observations across catalog and direct-proxy paths

Status: **implemented** in snapshot `3643f5e9f`; integration `13a692e3c` adds
schema-rejection observation and global-server sentinel normalization.

`mcpgateway/services/tool_service.py` reuses `ObservabilityService`, the metrics
buffer, trace context and redaction helpers. `_start_tool_observation()` and
`_finish_tool_observation()` share the lifecycle across catalog invocation, direct
invocation and direct-proxy delegation. No parallel telemetry store was introduced.

- Catalog attribution is observation-only: `observation_tool_id` is separate from
  the execution ID. Lookup failures must not change routing or authorization.
- Registered calls record tool metrics; server-scoped calls also record server
  metrics. An unregistered direct tool can still record a server metric and span.
  Keep metric guards independent; server recording does not require a tool ID.
- Global `/mcp` calls have no virtual-server metric. Normalize the transport's
  `default_server_id` sentinel to `None` before passing it into tool invocation.
- One observation covers a logical invocation, including internal retries. Final
  MCP errors, exceptions, timeouts and cancellations close it with a failure
  outcome. Delegation must not double-count the invocation.
- Each sink is independently best-effort. Lookup, span, sanitization and metric
  failures must preserve the tool result or original exception. Keep independent
  observability sessions rather than using the routing transaction.
- Do not capture arguments or auth headers in the added metadata. In integration,
  invalid inputs use `tool.failure_reason=invalid_arguments` and a fixed error
  message: raw schema-validation errors can expose submitted values. Preserve
  rejection before execution, plugin post hooks and retries.

**Merge guidance:** keep upstream execution/validation behavior and route recording
through the shared helpers. Do not move schema rejection ahead of observation
startup or collapse the tool/server metric guards together.

Guards: `tests/unit/mcpgateway/services/test_tool_service.py`,
`tests/unit/mcpgateway/services/test_metrics_buffer_service.py`, and
`tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`. Retain the
transport instrumentation-failure cases: its broad exception handler can otherwise
turn a telemetry failure into a client error. The black-box test,
`tests/live_gateway/mcp/test_tool_observability.py`, covers catalog/direct calls;
integration adds global calls and schema-rejection privacy checks.

### 6. Tool names, outcomes and execution timelines in the Admin UI

Status: **implemented** in snapshot `3643f5e9f`, preserved in `13a692e3c`.

`mcpgateway/admin.py::_summarize_observability_traces()` supplies shared summaries
to the trace list/detail templates: original tool names, catalog names where
different, execution modes and outcomes. Requests without recorded tool spans
retain an HTTP-request fallback; historical traces are not backfilled. Tool-name
filtering matches both original and catalog names.

The dashboard, statistics and tool templates distinguish requests from tool
executions. The detail template reuses existing Gantt/flame renderers and a shared
payload serialized with Jinja's `tojson`, including `parent_span_id`. Previously,
HTML-escaped quote interpolation broke chart JavaScript, leaving timelines empty.
Empty and unfinished traces have explicit display states.

**Merge guidance:** retain shared summaries and chart payloads; do not duplicate
aggregation in templates or restore hand-built JavaScript string quoting. Keep
new directives compatible with CSP-safe Alpine (§3).

Guards: `tests/unit/mcpgateway/test_admin_observability_sql.py` covers rendering,
filtering and serialization; `tests/unit/js/observability-exec-strip.test.js`
covers partial-script execution, dashboard filters and time-range refresh. Retain
the template CSP tests in §3 as well.

### 7. Azure build and secret configuration

Status: Azure scripts/build compatibility are in the fork snapshot; the dedicated
default-user password wiring is **integration-only** in `13a692e3c`.

`deploy/scripts/` and `deploy/README.md` reuse the Containerfile, ACR and Key Vault.
Preserve classic-builder-compatible `COPY` plus `RUN chmod`, explicit base-image
arguments including `WHEELS_REF`, and the clean `git archive HEAD` build context.
Uncommitted source edits are not included in that archive. Use native AMD64
infrastructure for Azure builds; the scripts explain the Apple Silicon emulation
limitation with the selected base images.

Upstream startup validation requires a valid `DEFAULT_USER_PASSWORD` when email
auth is enabled. Integration adds `KV_DEFAULT_USER_PASSWORD` (default secret name
`mcpgw-default-user-password`). `01-prepare-azure.sh` creates a random value only
if absent; `03-deploy-gateway.sh` checks and maps it through Key Vault to
`DEFAULT_USER_PASSWORD`; `04-smoke.sh` checks the secret reference. Keep it separate
from the platform-admin password, preserve existing secrets, and do not rotate
JWT or encryption keys during an upstream sync.

**Merge guidance:** retain deployment overrides through Containerfile/configuration
changes and check new required settings before rollout. Reuse existing secret
helpers. Shell syntax checks passed; the merged Azure AMD64 build and rollout
remain pending.

### 8. Global MCP team-token permission checks

Status: **integration-only**, implemented in `13a692e3c`.

`mcpgateway/transports/streamablehttp_transport.py` uses
`_check_any_team_for_streamable_rbac()` for tool execution, logging and
`servers.use`. Previously the decision depended on a virtual-server ID, denying
team API tokens on global `/mcp` even when their team role granted access.

The shared helper enables team-role lookup for team-scoped API tokens and keeps
existing session-token behavior. `PermissionService` still receives `token_teams`;
visibility, permission scope caps and role checks remain independent. Public-only
API tokens do not gain team permissions.

**Merge guidance:** do not restore a server-ID prerequisite or reimplement team
claim interpretation. Keep the transport helper truth-table tests and
`test_global_tool_call_uses_token_scoped_roles`, including public-only denial.
Re-run live protocol/RBAC checks after changes.

### 9. Integration test isolation and migration typing

Status: **integration-only**, implemented in `13a692e3c`.

- `tests/unit/mcpgateway/services/test_session_affinity.py` detaches the real
  OpenTelemetry context attached by its trace-envelope test, asserts the trace ID
  and verifies restored context. Keep the `finally` cleanup: without it, subsequent
  tests inherit a stale trace ID and fail depending on execution order.
- `mcpgateway/alembic/versions/5e211ec89cad_allow_nullable_email_user_password_hash.py`
  uses SQLAlchemy's `ReflectedColumn` and a read-only `Sequence` annotation. These
  are type corrections only. Preserve upstream's revision chain and passwordless
  metadata snapshots; SQLite and PostgreSQL upgrade/downgrade checks passed.

### 10. Configured reasoning effort in gateway-backed LLM chat

Status: **implemented** before snapshot `3643f5e9f`, preserved in `13a692e3c`.

`GatewayProvider` in `mcpgateway/services/mcp_client_chat_service.py` forwards a
configured `reasoning_effort` into shared OpenAI-family client kwargs (`openai`,
`azure_openai`, `openai_compatible`), leaving it unset when not configured. This
allows an endpoint-supported effort for tool calls without a hardcoded default.

**Merge guidance:** retain the configured value through provider construction;
do not forward it indiscriminately to other providers. Regression coverage is in
`tests/unit/mcpgateway/services/test_mcp_client_chat_service_extended.py`.

### 11. Rust TLS dependency security update

Status: **integration-only**, added during the 2026-09-17 pre-merge checks.

`crates/mcp_runtime/Cargo.toml` requires `rustls >=0.23.45` within the 0.23 series,
and `Cargo.lock` resolves that patched version. This addresses
[RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html), which
the GitHub Rust dependency-policy check detected in upstream's locked 0.23.43.
The Azure image uses the Python runtime, but optional Rust builds must also use
the patched dependency. Do not restore the older minimum or lock entry during
future merges; retain the dependency-policy check.

The existing version-scoped `cargo-vet` exemption in `supply-chain/config.toml`
follows the patched version. It remains an explicit exemption, not an audit
certification; the independent vulnerability check must still pass.

## Conventions for future divergences

1. Prefer changing configuration over changing widely-edited source files.
2. Prefer adding new files over editing upstream files. New files never conflict.
3. When an upstream file must be edited, prefer many small edits over one large block.
4. Record every divergence here, including the reasoning, so the next person does not
   have to reconstruct it from a diff.
5. Do not add entries to `docs/docs/architecture/adr/`. Adding an ADR requires editing
   `.pages` and `index.md`, both of which upstream edits with every ADR they add.
   Upstream is at 054 and already carries a number collision at 005 from exactly this
   pattern.
