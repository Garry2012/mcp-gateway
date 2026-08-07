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

## 6b. AMENDMENT 2 — resolution of REVIEW-001 B-002 (2026-08-06)

The Developer's second blocker is **accepted in full**, and it is the most serious
finding of the engagement. Amendment 1 over-corrected: broadening the runtime tier to the
whole package meant the gate demanded renaming security-critical identifiers.

### What was wrong

`contextforge-internal-mcp-runtime-v1` is a **shared salt in a SHA-256 authentication
derivation**, present in both runtimes:

- `mcpgateway/auth_context.py:143`
- `crates/mcp_runtime/src/lib.rs:100`, used at `lib.rs:2489`

Renaming it in Python alone makes the two sides compute different digests and **breaks
cross-runtime authentication**. Renaming both violates the Rust exclusion in §7. The gate
was therefore demanding a change that was either impossible or a security break. The
Developer correctly refused and escalated rather than working around it.

Also confirmed: four stable OpenTelemetry attribute keys (`contextforge.gateway_id`,
`.runtime`, `.tool.id`, `.transport`) whose renaming would break dashboards, and the
Python class symbol `ContextForgeMCPServer`.

### Root cause

Enumeration. Amendment 1 replaced a too-narrow file list with a too-broad one. Both
failures share a cause: the gate was trying to distinguish brand text from identifiers
by *location*, which is not a property of location.

### Fix — allowlist by identifier shape

The distinction is grammatical and therefore durable:

| Form | Example | Treatment |
|---|---|---|
| Legacy brand as a standalone word | `ContextForge Support Bundle` | **must change** |
| Followed by a separator `[-_.:]` | `contextforge-internal-mcp-runtime-v1` | exempt — identifier |
| Continuing in CamelCase | `ContextForgeMCPServer` | exempt — symbol |

This protects the auth salt, telemetry keys, protocol headers, Redis keys, the crate
name, and any future identifier of the same shape **without needing to know it exists** —
which is the property both previous versions lacked.

Runtime tier drops from 233 to 149 lines. The removed 84 were identifiers that should
never have been in scope. Verified: real brand text in `siem_export_service.py`,
`support_bundle_service.py`, `well_known.py`, and `cli_export_import.py` is still caught,
and the six logo references are still caught by the `assets` tier.

### Standing rule

**No brand change may alter any value participating in authentication, authorisation,
session derivation, or cross-runtime protocol.** If the gate ever demands one, that is a
gate defect — stop and escalate, exactly as was done here. Do not satisfy the gate by
renaming such a value, and do not evade it with source-token tricks.

## 6c. AMENDMENT 3 — SIEM vendor identity resolved (2026-08-06)

The product owner has ruled on the escalation from Amendment 1 D2.

**Organisation name: `InTimeTec`.** Implemented as a configurable setting rather than a
literal, because this fork is heading for multi-tenant Azure deployment where tenants may
need their own vendor identity.

### Required change

Both SIEM header sites in `mcpgateway/services/siem_export_service.py`:

| Line | Current | Required |
|---|---|---|
| 1020 (CEF) | `CEF:0\|IBM\|ContextForge\|...` | vendor from new setting, product from `settings.app_name` |
| 1029 (LEEF) | `LEEF:2.0\|IBM\|ContextForge\|...` | same |

New setting in `mcpgateway/config.py`, placed with the other SIEM settings:

```python
siem_vendor_name: str = Field(
    default="InTimeTec",
    description="Vendor identity emitted in CEF/LEEF security event headers",
)
```

Add the matching commented entry to `.env.example` so `make check-env` stays consistent.
Do not hardcode `InTimeTec` at the call sites — read the setting.

### Header escaping — mandatory, do not skip

Hardcoded literals could never corrupt the log format. Configurable values can, so this
becomes a correctness requirement rather than a nicety.

CEF and LEEF both use `|` as the header delimiter. A vendor or product name containing
`|` or `\` would corrupt every event line, and a newline would forge a spurious event —
this is log injection, not just a formatting bug.

**Do not reuse `_cef_escape()` for header fields.** It escapes `=` as well
(`siem_export_service.py:1000`), which is required for extension *values* but is wrong in
the header, where `=` is not a delimiter. It would emit a literal backslash that parsers
render incorrectly.

Add a small header-specific helper that escapes `\` and `|` and strips newlines, and
apply it to **both** the vendor and product fields in **both** the CEF and LEEF headers.
Note the LEEF header currently applies no escaping at all.

Include a unit test covering a vendor name containing `|` and one containing a newline.

### Operator note

Changing CEF/LEEF vendor or product breaks existing SIEM correlation rules — filters
matching the old values silently stop matching, leaving dashboards quiet and apparently
healthy. No SIEM is currently connected, so this is free now and expensive later. Record
the change in the release notes for whoever wires up a SIEM.

## 6d. AMENDMENT 4 — deployment configuration in scope (2026-08-06)

The Developer's third blocker is **accepted in full**, and in practical terms it is the
highest-impact finding of the engagement: it would have defeated the entire migration on
our actual deployment path.

### What was wrong

`charts/mcp-stack/values.yaml:221` sets `APP_NAME: ContextForge` as an explicit
environment variable. An explicit env var **overrides the Python default**, so every Helm
install — which is the Azure deployment path — would have shipped the old brand across
OpenAPI, Swagger, MCP `serverInfo`, and the admin UI, no matter how thoroughly the
application source was migrated. The gate would have gone green regardless.

Also confirmed: `values.yaml:902` (`DCR_CLIENT_NAME_TEMPLATE`),
`values.schema.json` defaults, `templates/NOTES.txt:71` post-install output, and
`templates/configmap-monitoring.yaml:233,235` Grafana folder metadata.

### Two further instances the review did not find

Located by the Architect while generalising the finding:

- `docker-compose.yml:370` — `SMTP_FROM_NAME=${SMTP_FROM_NAME:-ContextForge}`, so mail
  from Docker deployments still identifies as ContextForge.
- `run.sh:106` — `APP_NAME=ContextForge`.

### Root cause — third instance of the same mistake

Amendment 1 scoped too narrowly, Amendment 2 too broadly, and this one scoped the **wrong
axis entirely**. All three share a cause: the gate was scoped by *where the Architect
assumed brand text lived* rather than by *what determines what the product says at
runtime*.

Application source is only half of that. Deployment configuration is the other half, and
it wins, because an explicit setting always beats a code default.

### Fix — a deployment tier

`scripts/check-brand.sh` gains a `deploy` tier covering `charts/`,
`docker-compose*.yml`, `Containerfile`, `docker-entrypoint.sh`, `run.sh`,
`run-gunicorn.sh`, `ansible/`, and `infra/`.

The shape allowlist already draws the right line here without modification:

| Form | Example | Treatment |
|---|---|---|
| Helm **key** | `mcpContextForge.config.APP_NAME` | exempt — identifier |
| Helm **value** | `APP_NAME: ContextForge` | **must change** — brand text |

Chart raw hits drop 931 → 93 after shape filtering, with zero false positives: the five
remaining lines that mention a Helm key also carry genuine brand text as a value or
label. `charts/**/CHANGELOG.md` is excluded as historical, consistent with the root
`CHANGELOG.md`.

### Revised definition of done

Task B is complete when **all four** exit 0:

```bash
scripts/check-brand.sh ui
scripts/check-brand.sh runtime
scripts/check-brand.sh assets
scripts/check-brand.sh deploy      # NEW
```

plus `README.md`, `DEVELOPING.md`, `charts/*.md` clean. The full run still fails on
`docs/docs/**`, which remains deferred to CONTRACT-002.

### Standing rule addition

**Changing an application default is not sufficient.** Any brand value that can be set by
deployment configuration must be changed in every place that sets it, or the default is
dead code. When changing a default in `config.py`, grep the deployment surfaces for the
same setting name before declaring it done.

## 6e. AMENDMENT 5 — prefix-qualified and bare identifiers (2026-08-06)

The Developer's fourth blocker is **accepted in full**. It correctly refutes the
"zero false positives" claim made in Amendment 4.

### How the Architect got that claim wrong

Amendment 4 verified false positives by inspecting only lines matching
`mcpContextForge\.[a-z]` — occurrences followed by a **dot** — and generalised the result
to the whole set. Bare `mcpContextForge` and all-lowercase `contextforge` were never in
the sample. The claim was true of the sample and false of the population.

This is the same error the contract forbids the Developer from making: asserting coverage
broader than the evidence. Recorded here rather than quietly fixed.

### Confirmed false positives

| Location | What it actually is | Consequence of renaming |
|---|---|---|
| `values.schema.json:208` `"mcpContextForge": {` | Helm top-level key | Breaks every `values.yaml` |
| `charts/README.md:755` `` `mcpContextForge` `` | Same key in prose | — |
| `ansible/ocp/vars/defaults.yml:6` `ocp_namespace: contextforge` | Kubernetes namespace **and** Helm release identity | **Orphans live cluster resources** |
| `docker-compose.with-langfuse.yml:100` `service.namespace=contextforge` | OpenTelemetry service namespace | **Splits historical observability data** |
| `docker-compose.with-langfuse.yml:162` Langfuse org ID | Stateful external identifier | Detaches existing Langfuse project |

### Root cause

The shape rule keyed only on what **follows** the brand. Two signals were missing:

- **Leading context.** `mcpContextForge` is a compound identifier, but the brand segment
  may be followed by `"`, a backtick, or nothing at all, so a trailing-only rule cannot
  see it.
- **Case.** All-lowercase `contextforge` standing alone is never prose. It is a
  namespace, release name, org ID, socket path, or image name.

### Fix

Two additions, and a second matching pass:

- `[A-Za-z0-9_][Cc]ontext[Ff]orge` — exempt when preceded by a word character.
- A **case-sensitive** pass exempting bare `contextforge` / `CONTEXTFORGE`. This cannot be
  folded into the main pattern, which runs case-insensitively and would then strip the
  CamelCase brand text the gate exists to find.

### Verification — exhaustive this time

All 250 flagged lines across `ui`, `runtime`, `assets` and `deploy` were re-tested
programmatically for identifier-only matches. Zero false positives. The only two lines
that trip an identifier test are the logo paths, which the `assets` tier reports
deliberately by bypassing the allowlist — without that bypass, `contextforge-logo` would
be exempt as identifier-shaped and never reported at all.

Critical overrides confirmed still caught: `values.yaml:221`, `values.yaml:902`,
`docker-compose.yml:370`, `run.sh:106`, `configmap-monitoring.yaml`.

Deploy tier: 93 → 87 lines.

### Architect decisions on the two escalated questions

Both were routed to the product owner. They are technical stability decisions, so the
Architect takes them:

**Kubernetes namespace / Helm release `contextforge` — REMAINS UNCHANGED, permanently.**
A namespace is the address of live cluster state, not a label. Renaming it does not
rename anything; it creates a second, empty namespace and orphans everything in the
first. There is no cosmetic benefit that justifies a migration of running workloads.

**Langfuse organisation ID and OpenTelemetry `service.namespace` — REMAIN UNCHANGED.**
These are join keys for historical observability data. Renaming them silently splits
dashboards and traces at the cut-over point, which is worse than an inconsistent label.

Both are now permanently out of scope, in the same category as the wire-protocol headers.

### Note on counts

The Developer observed 965 Helm keys against the 964 stated in Amendment 4. Counts drift
as files change; the guard asserts a floor, not equality. No protected identifier was
modified. Not a defect.

## 7. Out of scope

- Colour, theme, or layout changes
- Any functional, schema, API, or auth change
- `crates/mcp_runtime` Rust changes (no toolchain available; `server_name` is
  overridable at deploy time via `MCP_RUST_SERVER_NAME`, and the crate is marked
  deprecated upstream)
- Test fixtures, load-test scripts, and migration tooling under `tests/` that reference
  the old brand in descriptions only
