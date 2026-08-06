# CONTRACT-001 — Brand Migration

| | |
|---|---|
| **Author** | Architect (Opus 5) |
| **Assignee** | Developer |
| **Gate** | 1 (Design) passed → ready for Gate 2 (Build) |
| **Date** | 2026-08-06 |
| **Branch** | `feature/ui-rebrand-mcp-gateway` |

---

## 1. Context

`Garry2012/mcp-gateway` is a fork of `IBM/mcp-context-forge` (Apache-2.0, currently
1.0.7). We are personalising it: our own name and look. **Cosmetic only** — no
behaviour, schema, API, or auth changes.

The fork tracks upstream, which ships roughly 4 commits per day. Every decision below is
weighted toward keeping our delta small and confined so merges stay cheap.

Partial work already exists on this branch (commits `14747709`, `202a9793`, plus
uncommitted changes). It is **not** complete and has not been independently reviewed.
That is Task A.

---

## 2. Tasks

### Task A — Review the existing work

Review the uncommitted diff and the two commits on `feature/ui-rebrand-mcp-gateway`
against this contract. You are reviewing an architect's implementation; assume it has
gaps and find them.

Specific things worth attacking:

1. **Scope honesty.** The changes were scoped to "UI strings + runtime identity" and
   deliberately excluded documentation and docstrings. Is that boundary defensible, or
   does it ship a product that visibly contradicts itself?
2. **Missed live assertions.** `mcpgateway/cache/session_registry.py:2143` contains a
   doctest expecting `'ContextForge'`. The `tests/unit/` suite passed, which suggests
   this doctest is not collected there. Determine whether `make doctest` breaks, and
   whether other doctests have the same problem.
3. **Correctness of the config change.** `app_name` now defaults to `MCP Gateway`, and
   it feeds `serverInfo.name` advertised over MCP, the OpenAPI title, and the Swagger
   title. Confirm nothing else consumes it in a way that assumed the old value.
4. **`dcr_client_name_template`.** Changing this alters the name the gateway registers
   under with external OAuth authorization servers. Existing registrations keep the old
   name. Is a mixed state acceptable, or does this need a migration note?
5. **Anything the brand check misses.** `scripts/check-brand.sh` encodes my
   understanding of the surfaces. If there is a user-visible surface it does not scan,
   that is a finding against the contract, not just the code.

Output: `docs/contracts/REVIEW-001.md`, findings grouped **blocking / functional /
minor**, each citing `file:line`.

### Task B — Complete the migration

Make `scripts/check-brand.sh` exit 0, without violating any constraint in §4.

Current state (run it yourself to confirm):

| Tier | Status |
|---|---|
| `ui` — Admin UI JavaScript | PASS |
| `ui` — Admin UI templates | FAIL (logo/icon `<img>` refs and alt text) |
| `ui` — Static assets | FAIL (`iframe-test-harness.html`) |
| `runtime` — product identity | FAIL (module docstrings, SSO role descriptions) |
| `runtime` — `.env.example` | FAIL |
| `docs` — `README.md`, `docs/docs/` | FAIL |
| `assets` — logo/icon images | FAIL |

### Task C — Review your own work

After Task B, re-run the full gate in §5 and record results in
`docs/contracts/EVIDENCE-001.md`. Include actual command output, not summaries. State
explicitly what you could not verify and why.

---

## 3. Naming — DECIDED

**The product name is `MCP Gateway`.** Confirmed by the product owner on 2026-08-06.

This is already the value in `app_name`, `smtp_from_name`, `dcr_client_name_template`,
and the page titles, so **no rename is required** — the existing partial work used the
correct string. Task B is unblocked.

Apply `MCP Gateway` consistently to every remaining surface. Do not spread literal brand
strings any wider than they already are; prefer `settings.app_name` where a template or
service can read it, so a future rename stays cheap.

The check defaults to this value, so it needs no argument:

```bash
scripts/check-brand.sh
```

### Logo and wordmark

No logo asset exists for MCP Gateway. Unless the product owner supplies image files,
implement a **text wordmark**: "MCP" in the default foreground colour, "Gateway" in the
existing accent colour, replacing the `<img>` elements at:

- `mcpgateway/templates/login.html:220-224`
- `mcpgateway/templates/change-password-required.html:260-263`
- `mcpgateway/templates/admin.html:246-251` (header logo and icon, light and dark
  variants — note the icon slot is small and square; a two-word wordmark may not fit,
  so `MCP` alone or a monogram is acceptable there)

Rationale: text scales, themes for both modes without maintaining two assets, needs no
extra HTTP request, and is trivially replaced later when a real asset exists. This is a
reversible default chosen so the work is not blocked — not a final visual identity
decision.

Leave the `contextforge-*` image files on disk (see §4). Only the references change.

---

## 4. Constraints — violating any of these is a blocking defect

These are identifiers, not brand text. Renaming any of them breaks a running system.
`scripts/check-brand.sh` asserts they survive; do not weaken that assertion.

| Identifier | Count | Why it must not change |
|---|---|---|
| `x-contextforge-*` HTTP headers | 687 | Wire protocol between the Python gateway and the `crates/mcp_runtime` Rust crate. Asserted in live e2e tests. |
| `mcpContextForge.*` Helm value keys | 951 | Deployment identifiers. Renaming invalidates every existing `values.yaml`. |
| `contextforge:runtime:*` Redis keys | 18 | Cross-instance coordination. Renaming mid-deploy splits a live cluster. |
| `contextforge_mcp_runtime` | 13 | Cargo crate name. |
| `ContextForge Contributors`, `MCP-CONTEXT-FORGE` | ~47 | Upstream copyright and SPDX headers. Not ours to rewrite. Apache-2.0 requires attribution be preserved. |
| `mcp-context-forge`, `github.com/IBM` | many | Upstream package name and repository URLs. |

Further constraints:

- **Do not delete the `contextforge-*` image files** in `mcpgateway/static/`. They are
  upstream files; deleting them adds merge conflict surface. Add new assets alongside.
- **Do not weaken or delete tests.** If a test asserts an old brand string, update the
  expected value. If a test fails for a real reason, fix the code.
- **Keep `login.html` edits minimal.** Of the last 8 upstream commits to that file, 6
  touched lines 7–13 (`<head>`) — adjacent to our `<title>` at line 6. It is our highest
  conflict-risk file.
- **CSP compliance.** Upstream is migrating away from inline event handlers
  (`docs/CSP_INLINE_HANDLERS_MIGRATION.md`). New markup must avoid inline `onclick` and
  prefer classes over inline `style`.

---

## 5. Acceptance criteria

Machine-checkable. All must pass:

```bash
scripts/check-brand.sh          # exit 0
make ruff interrogate           # clean on changed files
make test                       # full suite, no new failures
make doctest                    # see Task A item 2
make build-ui                   # bundle builds
```

Then, with `make dev` running, confirm by HTTP request (not by eye alone):

```bash
curl -s localhost:8000/admin/login | grep -o '<title>[^<]*</title>'
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/openapi.json | jq -r .info.title
```

**Human judgement required** — these cannot be automated, flag them for the product
owner rather than deciding alone:

- Does the logo/wordmark look right in light and dark mode?
- Is the login page visually coherent after the asset change?

### Known environment traps

- `make build-ui` rewrites `package-lock.json`, changing the package name to your
  working directory name, because `package.json` has no `name` field. Revert that file;
  it is not part of your change.
- Running `pytest` without the full dependency set produces ~10 spurious failures in
  gRPC, Redis, and plugin-CLI tests. Run `make install-dev` first. Do not report those
  as findings.

---

## 6. Evidence format

`docs/contracts/EVIDENCE-001.md`:

```markdown
## Commands run
<command, then actual output>

## Acceptance criteria
| Criterion | Result | Evidence |

## Not verified
<what you could not check, and why>

## Findings routed back to architect
<contract defects, scope questions>
```

Claims without command output are not evidence. If something was not run, say so.

---

## 6a. AMENDMENT 1 — resolution of REVIEW-001 B-001 (2026-08-06)

The Developer's Task A review is **accepted in full**. Every finding was independently
reproduced by the Architect. Two were defects in the gate itself.

### Gate defects — fixed by the Architect

- **Whole-line allowlist suppression.** `scan()` dropped any line containing an
  allowlisted identifier, hiding visible branding on the same line (`README.md:30`, the
  image alt text, sat next to an allowlisted upstream URL). Now strips allowlisted
  *substrings* and re-tests the remainder, printing the original line.
- **`BRAND_LEGACY` was inert.** The scan pattern is now derived from the variable, so the
  documented override actually works.

### Scope decisions

**D1 — Runtime tier now scans the whole application package.** Enumerating five files
was unsafe. `scripts/check-brand.sh` scans `mcpgateway/` entirely. This deliberately
includes docstrings and config `description=` strings, which the review correctly showed
are operator-visible via generated docs and the admin configuration view. Roughly 233
lines. Prose rarely collides with upstream edits, unlike the colour-class churn that
drove earlier scoping.

**D2 — CEF/LEEF SIEM identity.** `siem_export_service.py:1020,1029` emits
`CEF:0|IBM|ContextForge|...`.
- *Product field* → derive from `settings.app_name`. In scope. Do not hardcode a literal.
- *Vendor field* (`IBM`) → **out of scope, escalated to the product owner.** Emitting
  another organisation as SIEM vendor is a factual and possibly legal question, not a
  cosmetic one. Leave `IBM` untouched until the owner rules.

Note for the owner: changing CEF vendor/product breaks existing SIEM correlation rules.
No SIEM is currently deployed, so the cost of changing it now is zero and rises later.

**D3 — Documentation split.** The review is right that omitted operator docs are a real
gap, but they do not all carry the same cost or the same answer:

| Surface | Decision | Reason |
|---|---|---|
| `README.md` (19 lines) | **IN SCOPE** | Front door of the product. 128 upstream commits/yr, small diff. |
| `DEVELOPING.md`, `charts/*.md` | **IN SCOPE** | Describe our current product's operation. |
| `docs/docs/**` (~1,300 lines) | **DEFERRED to CONTRACT-002** | 497 upstream commits/yr. Rebranding it is a permanent, heavy merge tax, and we may not ship upstream's docs site at all. Separate decision, separate cost profile. |
| `docs/docs/architecture/adr/**` | **PERMANENTLY OUT** | Historical records of decisions upstream made under their name. Rewriting falsifies history. |
| `docs/docs/media/kit/**` | **PERMANENTLY OUT** | Upstream's own brand/media kit. |
| `CHANGELOG.md` | **PERMANENTLY OUT** | Historical release record. |

The `docs` tier of the gate currently fails on `docs/docs/**`. Until CONTRACT-002 exists,
**Task B is complete when `ui`, `runtime`, and `assets` tiers pass**, plus `README.md`,
`DEVELOPING.md` and `charts/*.md`. Run tiers individually:

```bash
scripts/check-brand.sh ui
scripts/check-brand.sh runtime
scripts/check-brand.sh assets
```

**D4 — F-002 (DCR mixed names).** Accepted as correct. No automatic migration; existing
client IDs and secrets stay valid. Add a short compatibility note to
`docs/docs/manage/dcr.md` — this one file is in scope despite D3, because it documents a
behaviour we changed.

**D5 — F-001 (doctest).** In scope for Task B. Fix the expected value at
`session_registry.py:2143`. `make doctest` must pass.

**D6 — M-001 (fork record drift).** The Architect will reconcile `FORK-CUSTOMIZATIONS.md`
after Task B lands. Not the Developer's task.

## 7. Out of scope

- Colour, theme, or layout changes
- Any functional, schema, API, or auth change
- `crates/mcp_runtime` Rust changes (no toolchain available; `server_name` is
  overridable at deploy time via `MCP_RUST_SERVER_NAME`, and the crate is marked
  deprecated upstream)
- Test fixtures, load-test scripts, and migration tooling under `tests/` that reference
  the old brand in descriptions only
