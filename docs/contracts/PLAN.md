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
- [x] `04-smoke.sh` — 6 assertions against real HTTP, all green

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

## Milestone 3 — Tool call visibility — NOT STARTED

Requirement: see every tool an agent calls, with arguments and results.

Today: payloads are visible at the plugin boundary (`tool_pre_invoke`/`tool_post_invoke`)
but never persisted. `tool_metrics` stores timing only; `trace_tool_invocation` redacts
`password|token|key|secret` and keeps only status_code + response_size.

- [ ] Gate 0 — scope: retention, storage, replay in/out
- [ ] Gate 1 — design as a **plugin**, not a core change
- [ ] Build: capture plugin with `correlation_id`, configurable redaction (`full_capture` for dev)

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

### Housekeeping

- [x] Delete merged branches — remote is now `main` only. All were verified as zero-unique-commit
      ancestors of `main` before deletion.
- [ ] Rotate the local `:55040` dev instance password (was pasted into a chat transcript)

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
