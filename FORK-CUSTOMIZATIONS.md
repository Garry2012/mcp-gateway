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
| `tailwind.config.js` | 2 | entire color theme | Very low |
| `mcpgateway/services/email_notification_service.py` | 5 | 4 strings | Low |
| `mcpgateway/templates/login.html` | 23 | right panel rewrite, title | **Elevated — see below** |
| `mcpgateway/templates/admin.html` | 240 (94 touching color classes) | 9 strings | Low, because we only touch strings |
| `mcpgateway/config.py` | 261 | 1 string | Low, same reason |

Upstream velocity is roughly 4 commits per day.

### login.html is the hot spot

Of the last 8 upstream commits to `login.html`:

- **6 modified lines 7-13** — the `<head>`: Content Security Policy, stylesheet links,
  JS bundling. Our `<title>` change sits at line 6, immediately adjacent. Git's default
  three-line context window means adjacent edits conflict, not only overlapping ones.
- **3 modified the right-panel region** (lines 207, 285, 384), including commit
  `c18218c9`, *"[CHORE][UI]: Consistent ContextForge logo and branding"*.

Expect to hand-resolve conflicts in this file. They should be mechanical — our version
deletes most of the contested region, so the resolution is usually "keep the deletion" —
and `rerere` will replay that decision after the first time.

### Keep the new login panel CSP-clean

Upstream has an in-progress migration away from inline event handlers, documented in
`docs/CSP_INLINE_HANDLERS_MIGRATION.md`. Several of the `login.html` commits above are
part of it. Any markup we add to that file should avoid inline `onclick` handlers and
prefer classes over inline `style` attributes, so our panel is not rewritten by a future
upstream CSP commit.

## Divergences

### 1. Brand: ContextForge to MCP Gateway

Status: **planned, not yet implemented.** Design:
`docs/superpowers/specs/2026-08-06-mcp-gateway-ui-rebrand-design.md`.

Page titles, visible UI strings, email subject lines and sender name, and the login
page's right-hand panel.

### 2. Color theme via palette redefinition

Status: **planned, not yet implemented.**

`tailwind.config.js` redefines what the palette names `indigo`, `purple`, and `violet`
resolve to, rather than rewriting the roughly 1,629 utility class usages across the
codebase to a new `brand-*` scale.

**A class named `indigo-600` renders amber.** This is intentional. The reason is
directly visible in the churn table above: a `brand-*` rename would place an
approximately 1,629-line diff across `admin.html`, where upstream modified color classes
94 times in 12 months. Redefining the palette confines the change to a file upstream
touched twice.

**Known debt.** The honest implementation is a `brand-*` scale with all usages rewritten.
It is deferred, not rejected. Revisit if the fork ever stops tracking upstream, at which
point the conflict argument no longer applies.

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
