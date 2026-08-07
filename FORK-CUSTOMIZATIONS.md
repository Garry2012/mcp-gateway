# Fork Customizations

This repository (`Garry2012/mcp-gateway`) is a fork of
[`IBM/mcp-context-forge`](https://github.com/IBM/mcp-context-forge).

This file records everything that deliberately diverges from upstream, and how to keep
the fork in sync. It exists so that divergences are discoverable in one place rather
than discovered by surprise during a merge.

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
