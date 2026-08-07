# MCP Gateway Rebrand — Design

- **Date:** 2026-08-06
- **Branch:** `feature/ui-rebrand-mcp-gateway` (cut from `origin/main` @ `4092d336`)
- **Status:** Implemented, except the logo assets (see Open Items)

## Goal

Replace the "ContextForge" brand with "MCP Gateway" everywhere a user or tenant sees it.

Scope is text only. No color, theme, or layout changes. No behaviour, schema, API, or
auth changes.

## Scope decision

The repository contains roughly 1,166 lines matching "ContextForge" across 145 files.
Most are not brand text, and replacing them indiscriminately would break the build or
the running system. The work was therefore split into tiers.

### Must not change

| Category | Approx. occurrences | Reason |
|---|---|---|
| `x-contextforge-*` HTTP headers | 743 | Wire protocol shared between the Python gateway and the `crates/mcp_runtime` Rust crate, asserted in live e2e tests. Renaming breaks interop. |
| `mcpContextForge.*` Helm value keys | 957 | Deployment identifiers. Renaming invalidates every existing `values.yaml`. |
| `contextforge:runtime:*` Redis keys | 4 | Cross-instance runtime coordination state. Renaming mid-deploy would split-brain a running cluster. |
| `contextforge_mcp_runtime` crate name | 11 | Cargo build identifier. |
| "ContextForge Contributors" copyright | 47 | Upstream's legal attribution, not ours to rewrite. |

### Changed — Tier 1, user-visible UI

Page titles, visible strings, and sample payloads in the Admin UI and auth pages.

### Changed — Tier 2, runtime product identity

Email subjects and sender name, MCP instructions advertised to connecting clients, and
the configuration defaults that feed them.

### Deliberately not changed — Tier 3

Docstrings, module headers, and code comments (roughly 500 occurrences, concentrated in
`config.py`, `tool_service.py`, and `main.py`). Not user-visible. Changing them would
put a large diff across the files upstream edits most — `config.py` alone receives about
261 upstream commits a year — for no visible benefit.

## Changes

### Titles

| File | New title |
|---|---|
| `mcpgateway/templates/admin.html` | `MCP Gateway - Administration` |
| `mcpgateway/templates/login.html` | `Sign In - MCP Gateway` |
| `mcpgateway/templates/reset-password.html` | `Reset Password - MCP Gateway` |
| `mcpgateway/templates/change-password-required.html` | `Password Change Required - MCP Gateway` |
| `mcpgateway/version.py` (fallback login page) | `Login - MCP Gateway` |

`forgot-password.html` already read "MCP Gateway" and was left alone.

The Swagger and ReDoc titles derive from `settings.app_name` via `main.py:2081`, so they
follow the `app_name` change rather than needing their own edit.

### UI strings

- `login.html` — "Secured by MCP Gateway Authentication"
- `overview_partial.html` — architecture diagram label and four comments
- `admin.html` — sample `User-Agent` payloads (now `MCP-Gateway/1.0`, hyphenated to stay
  a valid User-Agent token), the A2A test default message, and a sample bot username
- `admin_ui/a2aAgents.js`, `admin_ui/admin.js` — default test message, startup log line

### Runtime identity

- `services/email_notification_service.py` — three subject lines and the sender-name
  fallback
- Three email templates — body text
- `cache/session_registry.py` — MCP `instructions` advertised to clients.
  `serverInfo.name` already read `settings.app_name` and needed no edit.
- `services/tool_service.py` and `admin.py` — the A2A default query string, which is
  duplicated in both

### Configuration defaults

| Setting | Old | New |
|---|---|---|
| `app_name` | `ContextForge` | `MCP Gateway` |
| `smtp_from_name` | `ContextForge` | `MCP Gateway` |
| `dcr_client_name_template` | `ContextForge ({gateway_name})` | `MCP Gateway ({gateway_name})` |

`.env.example` updated to match, since `make check-env` compares the two.

### Tests

Seven test files had assertions on strings that changed. All were updated to the new
expected values; none were deleted or weakened.

One failure during the run was a genuine find rather than a test problem: the A2A
default query string is duplicated in `admin.py` and `tool_service.py`, and the initial
pass had missed both. The failing assertion located them.

## Deployment notes

- **`SMTP_FROM_NAME`** is a settable environment variable. Changing the default does not
  override a value already set in a `.env` file or an Azure app setting. Confirm at
  deploy time or outgoing mail will still say "ContextForge".
- **`DCR_CLIENT_NAME_TEMPLATE`** determines the name this gateway registers under with
  external OAuth authorization servers. Existing registrations keep the old name, so a
  deployment that has already registered will show a mix until those are re-registered.

## Verification

- `tests/unit/mcpgateway/test_main.py`, `test_admin.py` — pass
- `tests/unit/mcpgateway/test_config.py`, `services/test_dcr_service.py`,
  `services/test_email_notification_service.py`, `tests/integration/test_a2a_sdk_integration.py`
  — 280 pass
- Doctests in `config.py` and `version.py` — 24 pass
- `ruff check` on all changed Python files — clean
- Full `tests/unit/` suite — see commit message for result

Not run: Playwright tests (require a live gateway), and the Rust test suite (no Cargo
toolchain available in this environment).

## Open Items

### Logo assets — unresolved, user-visible

Six references to ContextForge logo image files remain, because they are images rather
than text and replacing them is an asset decision:

- `templates/login.html:221-222`
- `templates/change-password-required.html:261-262`
- `templates/admin.html:246-251` (logo and icon, light and dark variants)

Until these are replaced, the login page, the password-change page, and the admin header
display the ContextForge wordmark while every string around them says MCP Gateway. This
is the most prominent remaining inconsistency.

Options: supply MCP Gateway logo files for `mcpgateway/static/`, or replace the `<img>`
elements with a text wordmark.

### Rust runtime server name

`crates/mcp_runtime` advertises `server_name: "ContextForge"` (`config.rs:51`,
`lib.rs:10486`, plus test assertions). Not changed, because no Cargo toolchain was
available to build or test the result. The value is overridable at deploy time via the
`MCP_RUST_SERVER_NAME` environment variable, so it can be handled without a code change.
The crate is also marked deprecated in its own `Cargo.toml`.

### Documentation

`docs/` contains roughly 243 matching lines and `README.md` 8. Not in scope for this
change.
