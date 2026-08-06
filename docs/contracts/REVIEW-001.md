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

This was a contract blocker rather than an implementation-only defect: the Architect
needed to decide which omitted runtime identities and operator documents were in scope,
which historical/upstream references must remain, and what vendor/product values the
fork should emit in CEF/LEEF. Amendment 1 accepted and resolved this finding in commit
`894c8c5c`.

### B-002 — The amended runtime gate requires prohibited identifier and authentication changes

After Amendment 1, the runtime tier scans every textual occurrence in `mcpgateway/`
(`scripts/check-brand.sh:103-104`), although D1 describes its intended scope as emitted
strings, descriptions, docstrings, and comments
(`docs/contracts/CONTRACT-001-brand-migration.md:221-228`). The broader textual scan
also catches identifiers that cannot be renamed under the contract:

- Python derives its trusted runtime-auth header from the literal
  `contextforge-internal-mcp-runtime-v1` (`mcpgateway/auth_context.py:143`,
  `mcpgateway/auth_context.py:408`). The Rust runtime uses the identical derivation
  string (`crates/mcp_runtime/src/lib.rs:100`). Changing only Python breaks cross-runtime
  authentication; changing both touches the explicitly out-of-scope Rust crate and
  changes authentication behavior.
- `contextforge.tool.id`, `contextforge.gateway_id`, `contextforge.runtime`, and
  `contextforge.transport` are emitted OpenTelemetry attribute keys
  (`mcpgateway/services/tool_service.py:3767-3769`,
  `mcpgateway/services/tool_service.py:6033-6036`). Tests and operator-configurable
  mappings consume those exact keys
  (`tests/integration/test_span_attribute_mapping_integration.py:206-237`). Renaming
  them is a telemetry schema migration that can break dashboards and mappings, not a
  cosmetic string change.
- The scan also catches Python symbols such as `ContextForgeMCPServer`
  (`mcpgateway/transports/streamablehttp_transport.py:310-326`) and private header
  constants whose values are protected wire identifiers
  (`mcpgateway/transports/rust_mcp_runtime_proxy.py:46-60`). Renaming symbols is not
  needed to alter product identity and broadens the fork delta; treating a potentially
  imported class as private would also be an unapproved API assumption.

The protected-value allowlist did not cover the runtime-auth derivation or telemetry
schema. The runtime tier therefore could not pass without either weakening
compatibility/security or changing the executable contract. Hiding a literal by
splitting it across source tokens would merely evade the gate and was not attempted.
Amendment 2 accepted and resolved this finding in commits `6e74ee21` and `ce3e0ee7` by
allowlisting identifier shapes rather than enumerated values.

### B-003 — Helm deployments override the migrated runtime with legacy brand defaults

After Amendment 2, the stated definition of done scans the application, `.env.example`,
and chart Markdown, but not deployable chart configuration or templates
(`scripts/check-brand.sh:134-161`). A default Helm installation therefore overrides the
migrated Python `app_name` with the old brand:

- `APP_NAME: ContextForge` is active in chart values
  (`charts/mcp-stack/values.yaml:220-224`) and every `mcpContextForge.config` entry is
  rendered into the gateway ConfigMap as an environment variable
  (`charts/mcp-stack/templates/configmap-gateway.yaml:20-23`). The deployed OpenAPI,
  Swagger, MCP `serverInfo.name`, and configuration UI will consequently remain
  `ContextForge`, even when all Task B gates pass.
- The active DCR override remains `ContextForge ({gateway_name})`
  (`charts/mcp-stack/values.yaml:895-903`) and is injected through the chart Secret
  (`charts/mcp-stack/templates/secret-gateway.yaml:20-24`). This defeats the DCR default
  and compatibility note required by Amendment 1.
- The chart's schema and generated README still declare the old application default
  (`charts/mcp-stack/values.schema.json:257-261`,
  `charts/mcp-stack/README.md:220`), so hand-editing Markdown would be regenerated back
  to the legacy value.
- Helm post-install output and Grafana provisioning visibly retain the old product name
  (`charts/mcp-stack/templates/NOTES.txt:70-71`,
  `charts/mcp-stack/templates/NOTES.txt:137-138`,
  `charts/mcp-stack/templates/configmap-monitoring.yaml:233-235`).

This reproduces B-001 at the deployment layer: the executable gate can pass while the
shipped Helm product contradicts the rebrand. Amendment 1 explicitly places only
`charts/*.md` in scope (`docs/contracts/CONTRACT-001-brand-migration.md:241-255`), so
changing values, schema, and templates would expand the contract. The Architect must
either add these Helm surfaces to Task B and its gate or explicitly retain their
upstream identity. No chart keys or values were changed pending that decision.
Amendment 4 accepted and resolved this finding in commit `49fea8dd` by adding the
deployment tier and placing brand-valued deployment configuration in scope.

### B-004 — The deployment gate classifies protected and stateful identifiers as brand text

Amendment 4 says the shape allowlist correctly exempts the Helm key
`mcpContextForge.config.APP_NAME` and reports zero chart false positives
(`docs/contracts/CONTRACT-001-brand-migration.md:421-440`). The implemented rule only
examines what follows the legacy substring
(`scripts/check-brand.sh:46-59`), so it does not recognize a legacy token that is part of
an identifier because of its *prefix*. Two current deploy-tier failures contain no
brand text at all:

- the protected schema key alone, `"mcpContextForge": {`
  (`charts/mcp-stack/values.schema.json:208`); and
- the same key alone in operator prose, `` `mcpContextForge` section ``
  (`charts/README.md:755`).

The new tier also finds bare lowercase identifiers whose position, not suffix, makes
them machine identity:

- `ocp_namespace: contextforge` is both the Kubernetes namespace and Helm release name
  (`ansible/ocp/vars/defaults.yml:5-6`), and is passed to `helm install`, resource
  selectors, and `helm uninstall` (`ansible/ocp/playbooks/deploy.yml:45-77`,
  `ansible/ocp/playbooks/uninstall.yml:52`); and
- `service.namespace=contextforge` and the Langfuse organization ID fallback
  `contextforge` are telemetry/resource identifiers
  (`docker-compose.with-langfuse.yml:100`,
  `docker-compose.with-langfuse.yml:162`).

Renaming the OpenShift namespace or Helm release would not be a cosmetic rebrand: it
would change resource identity and cause an existing installation to be addressed as a
different release/namespace. Renaming observability organization and namespace IDs is
likewise a data/telemetry migration decision. The contract explicitly prohibits
functional or schema changes, and its standing instruction says to stop when a match
looks like an identifier rather than prose. Hiding these values or adding an
implementation-local exception would evade the executable contract and was not
attempted.

The Architect must amend the gate so identifier-shape detection considers both sides of
the occurrence, and decide whether bare deployment IDs remain stable or require an
explicit compatibility migration. Task B and Task C remain stopped pending that
decision.

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
