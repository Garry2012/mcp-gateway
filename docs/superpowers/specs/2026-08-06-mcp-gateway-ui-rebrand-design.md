# MCP Gateway UI Rebrand — Design

- **Date:** 2026-08-06
- **Branch:** `feature/ui-rebrand-mcp-gateway` (cut from `origin/main` @ `4092d336`)
- **Status:** Approved, not yet implemented

## Goal

Rebrand the Admin UI and auth pages from "ContextForge" to "MCP Gateway", change the
color theme to graphite + amber, and replace the login page's right-hand panel with a
diagram of what the gateway does.

This is a cosmetic rebrand of a fork. It changes no behaviour, no schema, no API, and
no auth logic.

## Context

`Garry2012/mcp-gateway` is a fork of `IBM/mcp-context-forge`, currently at release
1.0.7. Upstream releases will be pulled periodically. Every design decision below is
weighted toward keeping the fork's brand delta small and confined, so future rebases
stay clean.

Deployment target is multi-tenant on Azure, but tenants share a single brand. Per-tenant
theming is explicitly out of scope.

## Decisions

### D1 — Hardcode the brand; do not wire `APP_NAME`

`mcpgateway/config.py:239` defines `app_name: str = "ContextForge"` and no template
reads it. It stays unused.

Wiring it would allow per-tenant naming, but all tenants share one brand, so the
indirection buys nothing today. Revisit only if per-tenant branding becomes a
requirement.

### D2 — Recolor by redefining palette names, not by rewriting usages

The UI contains roughly 1,629 occurrences of `indigo-*`, `purple-*`, and `violet-*`
utility classes:

| Location | Occurrences |
|---|---|
| `mcpgateway/templates/admin.html` | 833 |
| Other templates | 517 |
| `mcpgateway/admin_ui/*.js` | 279 |

Rather than rewriting each usage to a new `brand-*` scale, `tailwind.config.js`
redefines what those palette names resolve to. One file changes; the whole app
recolors.

**Rationale:** a `brand-*` rename would put a ~1,629-line cosmetic diff across
`admin.html` and the other files upstream modifies most frequently, making every future
rebase a manual conflict resolution. Confining the delta to one config file keeps
rebases clean. This is the dominant consideration; effort is secondary.

**Accepted cost:** a class named `indigo-600` renders amber. This is misleading and
must be documented at the point of confusion (see D5).

**Known debt:** the honest fix is a `brand-*` scale with all usages rewritten. Deferred,
tracked in `FORK-CUSTOMIZATIONS.md` and a GitHub issue.

### D3 — Login right panel becomes a hero graphic

The current panel (`login.html:183` onward) shows a wordmark, tagline, and six feature
cards in two labelled groups. The cards restate marketing copy that will drift out of
date as the product changes, and they occupy a screen users see daily.

Replaced with an inline SVG showing many upstreams funnelling through one gateway to
many servers, plus the wordmark and a one-line tagline.

Inline SVG rather than a raster asset: no extra HTTP request, scales to any viewport,
and inherits theme colors without maintaining light and dark variants.

### D4 — Text wordmark, no logo file

The wordmark is text: "MCP" in near-white, "Gateway" in amber. No image asset.

The existing `<img src="/static/contextforge-logo-white.png">` at `login.html:220-224`
is removed. The surrounding link is retargeted from
`https://github.com/IBM/mcp-context-forge` to `https://github.com/Garry2012/mcp-gateway`
(verified public, so tenant users will not hit a 404).

The `contextforge-*` image files in `mcpgateway/static/` are left in place — they are
upstream files, and deleting them adds rebase conflict surface for no benefit.

### D5 — Track the fork delta in `FORK-CUSTOMIZATIONS.md`

The repo has `docs/docs/architecture/adr/` with 54 ADRs, which would be the natural
home. It is the wrong choice here: adding an ADR also requires editing `.pages` (manual
nav) and `index.md`, both of which upstream edits with every ADR they add. Upstream's
next ADR is 055 and so is ours — a guaranteed conflict on two shared files per rebase.
Upstream already carries a `005` number collision from this pattern.

Instead:

1. **`FORK-CUSTOMIZATIONS.md`** (new file, repo root) — durable record of what diverges
   from upstream and why. New file, so it never conflicts. Becomes the landing page for
   all future fork deltas, not just this one.
2. **Header comment in `tailwind.config.js`** — explains the palette remap where a
   confused reader will actually be, with a pointer to the file above.
3. **GitHub issue** on `Garry2012/mcp-gateway` for the eventual `brand-*` rename, so the
   debt lives in a tracker rather than only in prose.

## Color System

`tailwind.config.js`, under `theme.extend.colors`. `darkMode: "class"` is unchanged.

### `indigo` → amber (primary accent)

`indigo` carries primary actions: buttons, links, focus rings.

| Token | Hex | Note |
|---|---|---|
| 50 | `#fffbeb` | |
| 100 | `#fef3c7` | |
| 200 | `#fde68a` | |
| 300 | `#fcd34d` | |
| 400 | `#fbbf24` | |
| 500 | `#f59e0b` | bright amber; intended for use on dark backgrounds |
| 600 | `#b45309` | darkened; see contrast note |
| 700 | `#92400e` | |
| 800 | `#78350f` | |
| 900 | `#5c2c0c` | |
| 950 | `#451a03` | |

**Contrast note.** `indigo-600` is the most-used token and appears as both button fill
and body-weight text on white. Measured WCAG contrast ratios:

| Hex | On white | On `#09090b` (dark panel) |
|---|---|---|
| `#f59e0b` (stock amber-500) | 2.15:1 — fails | 9.26:1 — passes AAA |
| `#d97706` (stock amber-600) | 3.19:1 — fails normal text | 6.24:1 |
| `#b45309` (chosen for 600) | 5.02:1 — passes AA | 3.96:1 |

Tailwind's stock `amber-600` fails AA for normal text on white, so the ramp darkens 600
to `#b45309`. The consequence is that light-mode buttons read as a deeper amber than the
bright `#f59e0b` in the approved mockup; the mockup's panel is dark, where `indigo-500`
applies and the bright value holds comfortably (9.26:1).

Note the inversion in the table: tokens that pass on white degrade on the dark panel and
vice versa. Any light-mode-tuned token used on a dark surface (or the reverse) needs
checking rather than assuming the ramp handles it.

This split is deliberate and must be verified visually rather than assumed — see
Verification.

### `purple` and `violet` → graphite

These carry decorative gradient partners and secondary accents. Both map to the same
zinc-based neutral ramp (`#fafafa` at 50 through `#09090b` at 950), so gradients that
currently run indigo → purple become amber → graphite.

### `blue` — unchanged

`blue-*` is used for informational states, badges, and light text on dark panels.
Remapping it risks breaking semantic color meaning for no brand benefit. Left alone.

## Changes by File

### Titles — 5 templates

| File | Line | New title |
|---|---|---|
| `mcpgateway/templates/admin.html` | 10 | `MCP Gateway - Administration` |
| `mcpgateway/templates/login.html` | 6 | `Sign In - MCP Gateway` |
| `mcpgateway/templates/reset-password.html` | 6 | `Reset Password - MCP Gateway` |
| `mcpgateway/templates/change-password-required.html` | 6 | `Password Change Required - MCP Gateway` |
| `mcpgateway/templates/forgot-password.html` | 6 | `Forgot Password - MCP Gateway` (already correct) |

### Login right panel — `mcpgateway/templates/login.html`

- Remove the six feature cards and their two group headings (`Core Platform`,
  `Enterprise Ready`).
- Remove the logo `<img>` at lines 220-224.
- Add inline SVG hero graphic and text wordmark.
- Retarget the wrapping link to `https://github.com/Garry2012/mcp-gateway`.
- Keep the dot-pattern background and the three floating pulse accents.

**Write the new markup CSP-clean.** Upstream has an in-progress migration away from
inline event handlers (`docs/CSP_INLINE_HANDLERS_MIGRATION.md`), and several recent
`login.html` commits are part of it. Avoid inline `onclick`; prefer classes over inline
`style` attributes. Markup that fights that migration will be rewritten by a future
upstream commit, converting a clean merge into a conflict.

**Conflict expectation for this file.** Of the last 8 upstream commits to `login.html`,
6 modified lines 7-13 (the `<head>`) and 3 modified the right-panel region — including
`c18218c9`, *"[CHORE][UI]: Consistent ContextForge logo and branding"*. Our `<title>`
edit at line 6 is adjacent to the most-churned region, and Git's three-line context
window means adjacent edits conflict, not only overlapping ones. Hand-resolution here is
expected rather than exceptional. Resolutions should be mechanical, since our version
deletes most of the contested block, and `rerere` replays them after the first
occurrence.

### Remaining brand strings

| File | Occurrences |
|---|---|
| `mcpgateway/templates/admin.html` | 9 |
| `mcpgateway/templates/overview_partial.html` | 6 |
| `mcpgateway/admin_ui/a2aAgents.js` | 2 |
| `mcpgateway/admin_ui/admin.js` | 1 |

Text substitution only.

### Email — 3 templates plus Python

Template bodies, one string each:

- `mcpgateway/templates/password_reset_email.html:6`
- `mcpgateway/templates/password_reset_confirmation_email.html:6`
- `mcpgateway/templates/account_lockout_email.html:7`

Subject lines and sender name are hardcoded in Python, not in the templates. Without
these, mail would arrive from "ContextForge" with a ContextForge subject and an MCP
Gateway body:

- `mcpgateway/services/email_notification_service.py:180` — `"Reset your ContextForge password"`
- `mcpgateway/services/email_notification_service.py:200` — `"Your ContextForge password was changed"`
- `mcpgateway/services/email_notification_service.py:222` — `"Your ContextForge account was temporarily locked"`
- `mcpgateway/services/email_notification_service.py:128` — fallback sender name
- `mcpgateway/config.py:1057` — `smtp_from_name` default

**Deployment note:** `smtp_from_name` is settable via the `SMTP_FROM_NAME` environment
variable. Changing the default does not override an existing value set in a `.env` file
or Azure app setting. Confirm at deploy time.

### New file

`FORK-CUSTOMIZATIONS.md` at repo root, per D5.

## Verification

1. `make build-ui` — Vite bundle rebuilds without error.
2. `make dev` — inspect login, dashboard, and one data-heavy tab in **both light and
   dark mode**. The palette remap touches ~1,629 sites indirectly; the risk is not
   compile failure but unreadable combinations that only appear visually.
3. Confirm the `indigo-600` contrast decision holds in practice on light-mode buttons,
   links, and focus rings. If the deeper amber reads as brown against the approved
   design, adjust the 600 token and re-measure contrast rather than reverting to
   `#d97706` (3.19:1, fails AA).
   Check specifically for the inversion case: any `indigo-600` usage that sits on a dark
   surface drops to 3.96:1, so dark-mode text using that token needs `indigo-500` or
   lighter instead.
4. Check `tests/` (including Playwright specs) for assertions on brand strings or
   `<title>` values. Update assertions to match the new brand. Do not delete or weaken
   tests.
5. `make ruff interrogate pylint` — required for the Python changes in
   `email_notification_service.py` and `config.py`.
6. `make test`.

## Out of Scope

- `brand-*` scale rename (deferred debt, D2)
- Per-tenant theming
- Wiring `APP_NAME` (D1)
- Deleting upstream `contextforge-*` static image assets (D4)
- Remapping the `blue` palette
- Any Azure deployment work
