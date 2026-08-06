# Project Plan — MCP Gateway (InTimeTec fork)

Single source of truth for what we are building and where we are.
Update the checkboxes; do not rewrite history.

**Product:** MCP Gateway · **Org:** InTimeTec · **Upstream:** IBM/mcp-context-forge 1.0.7
**Branch:** `feature/ui-rebrand-mcp-gateway`

---

## Milestone 1 — Brand migration ✅ COMPLETE

Cosmetic only. No behaviour, schema, API, or auth change.

- [x] Page titles, UI strings, emails
- [x] Runtime identity (`app_name`, MCP `serverInfo`, OpenAPI/Swagger)
- [x] SIEM CEF/LEEF — vendor `InTimeTec`, product from `app_name`, header escaping
- [x] Deployment config — `charts/values.yaml`, compose, `run.sh`
- [x] Logo slots → text wordmark
- [x] Doctest fix (`session_registry.py`)
- [x] Gate passes: `ui` `runtime` `assets` `deploy`
- [x] Protected identifiers intact: 699 headers / 978 Helm keys / 25 Redis keys / 20 crate refs

**Permanently out of scope** (renaming breaks running systems):
wire-protocol headers · Helm keys · Redis coordination keys · Rust crate name ·
auth salt `contextforge-internal-mcp-runtime-v1` · K8s namespace / Helm release ·
Langfuse org ID · OTel `service.namespace` · upstream copyright · CHANGELOGs · upstream ADRs

### Remaining before merge
- [ ] Visual check — wordmark light/dark, login page **(needs product owner)**
- [ ] `make test` + `make doctest` green on final state
- [ ] Reconcile `FORK-CUSTOMIZATIONS.md` *(architect)*

---

## Milestone 2 — Docs site rebrand — DEFERRED

- [ ] Decide whether we ship upstream's docs site at all **(needs product owner)**

~1,300 lines in `docs/docs/**`, which upstream edits 497×/year. Deferring costs nothing
if we end up writing our own docs. Do not start without an explicit decision.

---

## Milestone 3 — Tool call visibility — NOT STARTED

Requirement: see every tool an agent calls, with arguments and results.

Today: payloads are visible at the plugin boundary (`tool_pre_invoke`/`tool_post_invoke`)
but never persisted. `tool_metrics` stores timing only; traces redact `password|token|key|secret`.

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

Three CRMs surface as three tools (`{gateway_slug}-{tool}`); nothing decides which system
holds a given customer. Largest architectural gap for the target use case.

- [ ] Gate 0 — do the backends partition cleanly? Determines everything.
- [ ] Gate 1 — start with deterministic rules, fall back to scatter–gather. **Not** an index first.
- [ ] Depends on M4 (a logical tool fronting physical ones is a composite)

---

## Milestone 6 — Azure multi-tenant deploy — NOT STARTED

- [ ] Confirm `SMTP_FROM_NAME` / `APP_NAME` not overridden in Azure app settings
- [ ] Helm values for AKS
- [ ] Tenant isolation review against existing RBAC/teams model

---

## Working agreement

- Architect (Opus 5): Gates 0–1, contracts, review. Does not mark own work complete.
- Developer (GPT-5.6): Gate 2 build, evidence.
- Prompts: **short**. Point at files; do not restate them.
- Escalate only what genuinely blocks *all* work. Otherwise raise a finding and keep building.
