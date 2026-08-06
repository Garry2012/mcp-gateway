# REVIEW-001 — Brand Migration Review

Review target: commit `ea3cf45d` and surrounding brand-migration commits through
`8323e96e`, assessed against `CONTRACT-001`.

## Blocking

### B-001 — The executable gate can pass while the shipped product still identifies itself as ContextForge

The contract says the migration must apply `MCP Gateway` consistently to every remaining
surface, but the runtime tier scans only five Python files
(`scripts/check-brand.sh:84-90`). Live, externally visible surfaces outside that list
still emit the old product name, including:

- generated support-bundle documentation (`mcpgateway/services/support_bundle_service.py:604-606`);
- CEF and LEEF product identity sent to SIEM systems (`mcpgateway/services/siem_export_service.py:1020`, `mcpgateway/services/siem_export_service.py:1029`);
- an OAuth authentication error returned to clients (`mcpgateway/transports/streamablehttp_transport.py:5613`);
- export/import and tools CLI help (`mcpgateway/cli_export_import.py:271`, `mcpgateway/tools/cli.py:44`);
- generated `security.txt` content (`mcpgateway/routers/well_known.py:108`); and
- configuration/schema descriptions exposed to operators (`mcpgateway/config.py:500-501`, `mcpgateway/config.py:544`, `mcpgateway/config.py:575`, `mcpgateway/config.py:1174`).

The documentation tier is similarly limited to `README.md` and `docs/docs/`
(`scripts/check-brand.sh:95-100`), omitting operator-facing material such as the Helm
guide (`charts/README.md:1`) and the development guide (`DEVELOPING.md:1`). Some omitted
documents are historical or upstream attribution, while others describe the current
product, so a blanket replacement is not safe.

In addition, `scan()` removes an entire matching line whenever that line also contains
an allowlisted identifier (`scripts/check-brand.sh:57-58`). This hides visible legacy
branding next to protected URLs or Helm keys. Current examples include the README image
alt text (`README.md:30`, `README.md:82`), the product description and roadmap link
(`README.md:68`, `README.md:84`), and the Helm value description
(`docs/docs/deployment/helm.md:654`). The protected identifier must survive, but the
visible text on the same line still needs review.

This is a contract blocker rather than an implementation-only defect: the Architect
must decide which omitted runtime identities and operator documents are in scope, which
historical/upstream references must remain, and what vendor/product values the fork
should emit in CEF/LEEF. Strengthening the scan or silently editing those surfaces would
change the executable scope. Per `CONTRACT-001` Task A, work stops before Task B.

## Functional

### F-001 — The full doctest target fails on the stale MCP initialization assertion

`make doctest` executes the example that `tests/unit/` misses and fails because the
expected value remains `'ContextForge'` (`mcpgateway/cache/session_registry.py:2142-2143`)
while runtime output correctly comes from `settings.app_name`
(`mcpgateway/cache/session_registry.py:2202`). The full run reported exactly one failure:
this doctest. No other doctest shared the stale expected-brand failure (1 failed, 1217
passed, 56 skipped).

### F-002 — Existing and new DCR registrations will show mixed names without an operator note

New registrations derive `client_name` from the new template
(`mcpgateway/services/dcr_service.py:187-204`), but an active registration is returned
unchanged (`mcpgateway/services/dcr_service.py:294-303`). Even the explicit update path
omits `client_name` (`mcpgateway/services/dcr_service.py:342-349`). Authentication is not
broken because existing client IDs and secrets remain valid, so automatic migration is
not warranted for a cosmetic change. However, authorization-server dashboards will show
both names until registrations are recreated. The existing DCR guide still illustrates
the old name and contains no compatibility note (`docs/docs/manage/dcr.md:82-98`). A
migration note is needed if this configuration default remains in scope.

### F-003 — The known logo references still visibly contradict the migrated page titles

The UI continues loading six `contextforge-*` image assets in the login,
change-password, and admin headers (`mcpgateway/templates/login.html:221`,
`mcpgateway/templates/change-password-required.html:261`,
`mcpgateway/templates/admin.html:246-251`). This is already anticipated by the contract,
but it confirms the existing implementation is not independently complete.

## Minor

### M-001 — The fork record overstates completion and conflicts with the current contract

The fork record says the rebrand is implemented except for logos
(`FORK-CUSTOMIZATIONS.md:76-83`) and says docstrings were deliberately left unchanged
(`FORK-CUSTOMIZATIONS.md:96-97`). The current contract instead includes user-facing
documentation and identifies module docstrings as a failing runtime tier
(`docs/contracts/CONTRACT-001-brand-migration.md:58-74`). The record should be reconciled
after the Architect resolves B-001.

### M-002 — The documented legacy-brand override does not affect scanning

`BRAND_LEGACY` populates `LEGACY_BRAND` for display, but `scan()` searches a hardcoded
`[Cc]ontext[Ff]orge` expression (`scripts/check-brand.sh:17`,
`scripts/check-brand.sh:57`). The advertised override therefore cannot validate a later
rename. This does not block the current fixed-name migration, but it makes the script's
documented interface misleading.

## Reviewed with no finding

The `app_name` default change itself is sound. Its live consumers use the value as an
opaque display string for MCP `serverInfo.name` (`mcpgateway/cache/session_registry.py:2202`),
the FastAPI/OpenAPI title (`mcpgateway/main.py:2080-2084`), the UI-disabled root response
(`mcpgateway/main.py:13277-13278`), the admin configuration view
(`mcpgateway/admin.py:2708-2713`), and version/support metadata
(`mcpgateway/version.py:1026-1029`). None of these paths assumes the old literal or uses
it as a schema, authorization, or storage identifier. The stale fallback in compliance
output (`mcpgateway/services/compliance_service.py:413`) is a missed brand surface
covered by B-001, not evidence that the default change is unsafe.

The protected identifiers were unchanged by `ea3cf45d`: exact counts before and after
that commit were identical for `x-contextforge-*`, `mcpContextForge`,
`contextforge:runtime:*`, `contextforge_mcp_runtime`, upstream copyright/SPDX text,
the upstream package name, and IBM repository URLs.
