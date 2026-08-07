# Project Plan — MCP Gateway (InTimeTec fork)

Single source of truth for what we are building and where we are.
Update the checkboxes; do not rewrite history.

**Product:** MCP Gateway · **Org:** InTimeTec · **Upstream:** IBM/mcp-context-forge
**Branch:** `main` (all feature branches merged)

**Live:** `https://mcp-gateway.ashyflower-2c14847d.centralindia.azurecontainerapps.io/admin/login`
Admin `admin@intimetec.com` · password:
`az keyvault secret show --vault-name vcare-rc-kv --name mcpgw-platform-admin-password --query value -o tsv`

---

## Milestone 1 — Brand migration ✅ COMPLETE

Cosmetic only. No behaviour, schema, API, or auth change. Merged and deployed.

- [x] Page titles, UI strings, emails
- [x] Runtime identity (`app_name`, MCP `serverInfo`, OpenAPI/Swagger)
- [x] SIEM CEF/LEEF — vendor `InTimeTec`, product from `app_name`, header escaping
- [x] Deployment config — `charts/values.yaml`, compose, `run.sh`
- [x] Logo slots → text wordmark
- [x] Doctest fix (`session_registry.py`)
- [x] Gate passes: `ui` `runtime` `assets` `deploy` (`scripts/check-brand.sh`)
- [x] Protected identifiers intact: 699 headers / 978 Helm keys / 25 Redis keys / 20 crate refs
- [x] Visual check by product owner
- [x] `FORK-CUSTOMIZATIONS.md` reconciled
- [x] Merged to `main`, deployed, brand verified live by `deploy/scripts/04-smoke.sh`

**Permanently out of scope** (renaming breaks running systems):
wire-protocol headers `x-contextforge-*` · Helm keys `mcpContextForge.*` · Redis keys
`contextforge:runtime:*` · Rust crate `contextforge_mcp_runtime` · auth salt
`contextforge-internal-mcp-runtime-v1` · K8s namespace / Helm release · Langfuse org ID ·
OTel `service.namespace` · upstream copyright + SPDX · CHANGELOGs · upstream ADRs

> **Standing rule:** no brand change may alter any value participating in authentication,
> authorisation, session derivation, or cross-runtime protocol. If a gate demands one, stop
> and escalate — never satisfy it by renaming.

---

## Milestone 6 — Azure deploy ✅ COMPLETE (single-tenant)

Reordered ahead of 2–5: needed a running system before extending it.
Container Apps, not AKS. See `deploy/README.md` for the "why" and the traps.

- [x] Resource group `vcare-rc-rg` (pre-existing, nothing else disturbed)
- [x] Scripted, idempotent, re-runnable: `deploy/scripts/00`–`04`
- [x] Secrets via Key Vault `keyvaultref` + UAMI — no credential in repo, CLI history, or app config
- [x] Postgres Flexible Server `vcare-mcpgw-db`, password rotated
- [x] `04-smoke.sh` — 7 assertions against real HTTP, all green

### Three container-constraint bugs found in production

All three were config defaults that are correct on a host and wrong in a container.
Each is now pinned in `deploy/scripts/00-config.sh` **with the reason in a comment**.

| Symptom | Cause | Fix |
|---|---|---|
| `remaining connection slots are reserved…` | `db_pool_size=200` vs B1ms `max_connections=50` | `DB_POOL_SIZE=20` / `DB_MAX_OVERFLOW=5` |
| OAuth handed out `localhost` redirect URIs | `APP_DOMAIN` defaults to `http://localhost:4444` | resolved from ingress FQDN in `03-deploy-gateway.sh` |
| `Worker (pid:280) was sent SIGKILL!` crash loop | `nproc*2+1` — `nproc` reports **host** CPUs, not the cgroup limit | `GUNICORN_WORKERS=2` |

Also: `Containerfile` — two `COPY --chmod=0755` split into `COPY` + `RUN chmod`.
ACR's classic builder has no BuildKit; **without this the image will not build at all.**
`02-build-images.sh` guards against the pattern coming back via an upstream merge.

### A fourth: the deploy that silently did nothing

`IMAGE_TAG` was the fixed, mutable tag `v1`. Redeploying the same tag produces a container
app template identical to the deployed one, and in Single revision mode Container Apps only
rolls a revision when the template changes. So the ACR build succeeded, the tag moved to the
new digest, all three scripts exited `0` — and the old replica kept serving:

```
revision mcp-gateway--0000005   created 04:41:13Z
image tag v1 (sha256:8d86d7bd)  pushed  07:18:12Z   # 2h37m AFTER the replica started
```

The smoke test could not catch it: its stale-image guards assert on the brand in the login
page, which cannot tell two post-rebrand builds apart. All six checks passed against the
stale image and declared success.

`IMAGE_TAG` now defaults to the short commit SHA, so every deploy is a distinct template and
the running image is traceable to a commit. `04-smoke.sh` gained assertion #0: a revision
that is both **active and Running** must be serving the image this deploy built. It reads the
revision, not the app template — the app template reflects desired state the moment
`az containerapp update` returns, so it reports the new image while the old revision is still
answering, and stays green even if the new revision provisions then crashes.

Both directions were verified against the live deployment; `IMAGE_TAG=v1` now exits 1.

### Still open

- [ ] Multi-tenant: currently one app, one Postgres. Isolation today is the RBAC/teams model,
      not infrastructure. Decide app-per-tenant vs shared-app-with-teams **(needs product owner)**
- [ ] Derive `DB_POOL_SIZE` from the server's real `max_connections` instead of a pinned number
- [ ] Azure resource lock on `vcare-mcpgw-db` (a `az containerapp` typo should not be able to
      take the database with it)
- [ ] CI build on an amd64 GitHub runner — builds are currently manual and workstation-bound
      (local amd64 build dies with `Fatal glibc error: CPU does not support x86-64-v3`)

---

## Zoho MCP server (Sun-TV tenant) ✅ COMPLETE

First real federated backend. Proves the DCR + OAuth path end to end.

- [x] Team `Sun-TV` — `d4e8e181698e489993ebf3cfcbd34f9a`
- [x] Gateway `zoho-mcp` — `b800430077474eb08851e0a3acb63c0e`, `reachable=True`
- [x] OAuth DCR (RFC 7591) + authorization_code + PKCE S256, authorised via UI
- [x] 4 tools discovered

`DCR_ALLOWED_ISSUERS` is **fail-closed** and lives in the Azure app config, deliberately
**not** in a local `.env` — putting it there breaks
`tests/unit/mcpgateway/services/test_dcr_service.py` (9 failures), which uses
`https://as.example.com` as a fixture issuer and expects a different error.

---

## Observability ✅ ENABLED AND WORKING

`OBSERVABILITY_ENABLED=true` on Azure. Traces and spans persist to Postgres and the Admin UI
reads them from there — **no collector, no key, no external service**. Set in
`deploy/scripts/00-config.sh` so a redeploy cannot silently drop it.

Tracing is scoped by `observability_include_paths`, an **allowlist** covering `/rpc`, `/sse`,
`/message`, `/mcp`, `/a2a`. Page loads and static assets are never traced, so DB load tracks
tool calls rather than traffic.

### The UI was completely broken, and it was not obvious

The backend wrote traces correctly the whole time. The panel rendered blank and made **no
network request at all**, which reads as a backend or data problem. Root cause: the admin UI
bundles the CSP-safe Alpine build (`@alpinejs/csp`), whose expression parser is far stricter
than the default build — and **it fails silently**, initialising a component as `{}` without
raising.

Established empirically in the browser (`Alpine.evaluate` uses a *different* code path than
directive compilation and reports false negatives — trust the live error count, not a probe):

| Form | CSP build |
|---|---|
| `{ a: 1, cfg: { x: 2 } }` — plain data, nested | parses |
| property access, method calls, ternary, comparison, concat, index | fine in directives |
| `{ a: 1, greet() {…} }` — any function in an inline `x-data` | **whole object fails** |
| `x-data="createFooController()"` where the factory is on `window` | **fails** — see below |
| optional chaining `a?.b` | **fails** — `Unexpected token: PUNCTUATION "."` |
| template literal `` `${a} ${b}` `` | **fails** — `Unexpected token: OPERATOR` |

`x-data` resolves names against the `Alpine.data()` registry and never evaluates globals. The
call form itself is fine — `overflowMenu('table')` works, arguments and all — but only for a
**registered** name.

Six templates were affected. Fixes: five controllers moved to `admin_ui/components/` and
registered; 12 optional-chaining and 10 template-literal directives rewritten; `tabs.js` read
`window.chartRegistry` where `app.js` defines `Admin.chartRegistry`, and the resulting
TypeError escaped the tab-switch handler ("Failed to switch to <name> tab").

Measured on a headless browser, before → after: **page errors 47 → 0**, trace rows 1 → 6,
and the `/traces` request fires for the first time. Verified against Azure too: **13 checks,
0 failures**.

`tests/unit/mcpgateway/test_template_alpine_csp.py` pins all of it — no inline `x-data` may
contain a function, no directive may use optional chaining or template literals, `x-data`
names must resolve to a registered component, `window.chartRegistry` must not be read, and
templates may not link stylesheets that are not shipped. **Every guard was verified to fail
on the pre-fix code**, not merely to pass today. That matters because all these defects were
invisible failures, and because upstream still writes in the pre-CSP style.

### What tracing does and does not give you

A trace records `tool.name`, `integration_type`, timing, `success`, and `arguments_count` —
**the count, not the arguments**. Payload capture (`OTEL_CAPTURE_INPUT_SPANS`) is set but
**inert**: there are two separate span writes, and only the OpenTelemetry one honours it.

| Where | Attributes | Destination |
|---|---|---|
| `tool_service.py:5315` | hardcoded six fields, never payloads | Postgres → Admin UI |
| `tool_service.py:5351` | adds `user.email`, `team.scope`, payloads when enabled | OTLP exporter only |

So the built-in UI will **never** show arguments regardless of configuration. That gap is
Milestone 3.

---

## Open bug — CSRF on non-form admin POSTs 🔴

**Not fixed.** Reproduces identically on the tool-control instance, so it is upstream,
not something we introduced.

`get_jwt_user_email_from_payload()` returns `None` because a **session** JWT carries
`sub` = user UUID and no `email` claim. `csrf_middleware.py:177` then fails closed
*before* the double-submit and HMAC checks ever run.

Surfaces as `CSRF validation failed` on "refresh tools" and any other non-form admin POST.
Commit `812dfc87` (send CSRF token on bulk refresh) does **not** fix it — the token is sent;
the middleware rejects it earlier for a different reason.

- [ ] Gate 0 — fix locally or upstream? Check whether IBM already has an issue open
- [ ] Fix must be in the *lookup*, not by weakening the check

---

## Milestone 2 — Docs site rebrand — DEFERRED

- [ ] Decide whether we ship upstream's docs site at all **(needs product owner)**

~1,300 lines in `docs/docs/**`, which upstream edits 497×/year. Deferring costs nothing
if we end up writing our own docs. Do not start without an explicit decision.

---

## Milestone 3 — Tool call visibility — NOT STARTED (now the top priority)

Requirement: see every tool an agent calls, with arguments and results.
This is the original ask, and it is still unmet — observability gives you *that* a call
happened and how long it took, never *what was in it*.

Ground already established, so Gate 0 does not start from zero:

- The DB span (`tool_service.py:5315`) writes a **hardcoded** attribute list and can never
  carry payloads. The Admin UI reads only this. Widening it is the shortest path to the
  requirement.
- The OTel span (`:5351`) does honour `OTEL_CAPTURE_INPUT_SPANS` / `OTEL_CAPTURE_OUTPUT_SPANS`
  (both already set to `tool.invoke`), but only reaches an OTLP backend such as Langfuse —
  which means an external service and a key.
- Output capture was gated on `success`, so failed calls — the ones worth inspecting —
  recorded nothing. **Fixed**; the gate is gone.
- `trace_tool_invocation()` (`observability_service.py:722`) is the purpose-built helper and
  has **zero production call sites**. Its docstring stores only status_code + response_size.
- Payloads are visible at the plugin boundary (`tool_pre_invoke`/`tool_post_invoke`) but
  nothing persists them.
- Redaction already exists: `serialize_trace_payload` / `sanitize_trace_attribute_value` in
  `utils/trace_redaction.py`. Reuse it; do not write another.

- [ ] Gate 0 — scope: retention, storage, replay in/out. Decide **DB span vs Langfuse** first;
      everything else follows from that one choice
- [ ] Gate 1 — design as a **plugin** where possible, not a core change
- [ ] Build: capture with `correlation_id`, configurable redaction (`full_capture` for dev)

A worked example of why this matters: diagnosing a failing Twilio tool took an hour and
direct API calls, because the gateway reported `HTTP 400` and discarded the upstream's
`{"code":21910,"message":…}`. That specific discard is now fixed, but the general case —
"what arguments did the agent actually send?" — is exactly this milestone.

---

## Milestone 4 — Composite tools — NOT STARTED

No tool-to-tool composition exists. Virtual servers group; `plugin_chain_*` is middleware.

- [ ] Investigate whether `mcpgateway/toolops/` already provides a primitive
- [ ] Gate 1 — declarative composites; decide failure semantics first
- [ ] Per-step observability (depends on M3)

---

## Milestone 5 — Multi-backend routing — NOT STARTED

Three CRMs surface as three tools (`{gateway_slug}{sep}{tool_name}`, `db.py:3409`); nothing
decides which system holds a given customer. Largest architectural gap for the target use case.

- [ ] Gate 0 — do the backends partition cleanly? Determines everything.
- [ ] Gate 1 — start with deterministic rules, fall back to scatter–gather. **Not** an index first.
- [ ] Depends on M4 (a logical tool fronting physical ones is a composite)

---

## Upstream sync

`main` contains IBM upstream with **zero** commits behind. Procedure and divergence record:
`FORK-CUSTOMIZATIONS.md`.

Merge (not rebase), `rerere` on, `zdiff3` conflict style. The one real merge so far:
3 upstream commits, 21 files, **1 trivial conflict** (`.secrets.baseline` timestamp).
For `.secrets.baseline` conflicts always take `main`'s version.

Confining the brand delta to as few files as possible is what keeps this cheap. Do not spread it.

### Every bug we fixed is upstream's, not ours

Verified against `upstream/main` file-by-file. Our fork had **never** touched `tabs.js` or any
observability template before these fixes; the only prior change to `tool_service.py` was
docstring brand text. Most are unreachable until `OBSERVABILITY_ENABLED=true`, which defaults
to false — that is why upstream has not hit them.

| Our fix | Upstream issue |
|---|---|
| Dashboard blank (inline `x-data` + CSP) | **#6054** open — same file, same lines, no PR |
| `window.chartRegistry` tab-switch failure | **#6055** open — cites `tabs.js:357-360`, no PR |
| REST error body discarded | **#6027** open — has open **PR #6043**, different approach |
| `auth-animations.css` 404 | **#5999** open, no PR |
| Sub-views blank (`createXController` under CSP) | **unreported** — #3966/#3967 fixed the same *symptom* pre-CSP; PR #5111's CSP migration regressed it in a way that fix cannot cover |
| Optional chaining / template literals in directives | **unreported** — #5155 fixed only the Roots `x-data` wrapper; the dead View/Edit/Export buttons and the `:style` binding are still live upstream |
| Output capture gated on `success` | **unreported** |

- [ ] Decide whether to upstream. No matched issue has a merged fix, so nothing is redundant.
      #6054/#6055 were filed by a third party two days before our fixes and are file-line
      accurate — **link to them, do not file duplicates**. #6027 needs reconciling against
      PR #6043, which enumerates `error`/`errors`/`message`/`detail` envelopes with a
      truncated raw-body fallback where we serialise the parsed body into
      `structured_content["body"]`.

Until this is upstreamed, expect recurring merge friction: upstream keeps writing these
templates in the pre-CSP style, and our guard tests will fail the merge. That is the intended
behaviour — a loud failure beats a silently blank dashboard — but it is ongoing cost.

**Correction to an earlier claim:** `auth-animations.css` was described in commit
`ca685d1a3` as having "never existed in this repo or upstream". Wrong — it existed and was
deleted in `9dfdcf545` during the Tailwind migration, leaving the `<link>` tags orphaned.

### Housekeeping

- [x] Delete merged branches — remote is now `main` only. All were verified as zero-unique-commit
      ancestors of `main` before deletion.
- [ ] Rotate the local `:55040` dev instance password (was pasted into a chat transcript)
- [ ] Rotate the Twilio auth token, or split the accounts. `send_payment_link` on Azure reuses
      the credential from tool-control's DB, so both deployments now share one token and
      rotating it in Twilio breaks both.

The `send_payment_link` template `intimetec_mock_paymentlink` builds its own button URL as
`https://buy.stripe.com/{{1}}`, so variable `1` is a **suffix only** — a full URL gets
concatenated and rejected. `To` must carry the `whatsapp:` prefix or Twilio returns `21910`
("From and To should be of the same channel"). Both mistakes surface only as `HTTP 400`.

`gh` had no default repo in this clone and resolved to `IBM/mcp-context-forge`, so a PR was
nearly opened against upstream. Now pinned with `gh repo set-default Garry2012/mcp-gateway`.
A fresh clone will need that again — or pass `--repo Garry2012/mcp-gateway` explicitly.

---

## Working agreement

- Architect (Opus 5): Gates 0–1, contracts, review. Does not mark own work complete.
- Developer (GPT-5.6): Gate 2 build, evidence.
- Prompts: **short**. Point at files; do not restate them.
- Escalate only what genuinely blocks *all* work. Otherwise raise a finding and keep building.

**Never rotate `AUTH_ENCRYPTION_SECRET`** — every stored OAuth token becomes undecryptable.
