# Fork Customizations

This repository (`Garry2012/mcp-gateway`) is a fork of
[`IBM/mcp-context-forge`](https://github.com/IBM/mcp-context-forge).

The fork tracks upstream as closely as possible. It carries only the divergences below.
Do not add UI, branding, or cosmetic changes to this fork. Submit fixes upstream instead.

Last updated: **2026-10-02**.

## Syncing with upstream

The `upstream` remote has pushing disabled, so `git push upstream` fails loudly.

```bash
git fetch upstream
git checkout -b sync/upstream-<date> origin/main
git merge upstream/main
```

Use merge, not rebase. Merge resolves each conflict once and records the resolution in history.

### Upstream reset: 2026-10-02

The fork was reset to upstream `16e76efba` (v1.0.11 + 12 commits). The merge commit
records `upstream/main` as a parent. Its tree equals upstream plus the divergences below.
All earlier fork work was dropped: the MCP Gateway rebrand, the CSP-safe Alpine
observability fixes, the observability UI tool timelines, backend tool-execution
observations, Tailwind and CSS build changes, and fork-local docs. Git history keeps that work.

Fixes still open upstream, which arrive on a later sync if merged:

- [#6126](https://github.com/IBM/mcp-context-forge/pull/6126) and
  [#6127](https://github.com/IBM/mcp-context-forge/pull/6127): blank observability dashboard
  under the CSP-safe Alpine build.
- [#6554](https://github.com/IBM/mcp-context-forge/pull/6554): team-scoped admins receive
  `403 Admin privileges required` on the bare `/admin` entry point.

## Divergences

### 1. Global `/mcp` team-token RBAC

`mcpgateway/transports/streamablehttp_transport.py::_check_any_team_for_streamable_rbac()`
enables team-role lookup for sessions and team-scoped API tokens on both global `/mcp` and
`/servers/<id>/mcp`. Upstream enables it only when a virtual-server ID is present. Upstream
therefore denies `tools.execute`, `servers.use`, and `admin.system_config` on global `/mcp`
to a team API token, even when the caller's team role grants the permission.

`PermissionService` still receives `token_teams`, so public-only API tokens (`teams: []`)
gain no team permissions. Visibility and token permission caps stay independent.

**Merge guidance:** do not restore a server-ID prerequisite. Keep
`test_check_any_team_for_streamable_rbac` and `test_global_tool_call_uses_token_scoped_roles`
in `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`, including the
public-only deny cases. Submit this fix upstream, then drop this divergence when it merges.

### 2. Azure deployment

`deploy/scripts/` and `deploy/README.md` build the image in Azure Container Registry and
deploy it with Key Vault secrets. These are new files, so they do not conflict with upstream.
`pyproject.toml` excludes `deploy/**` from the package manifest check.
Per-target overrides live in `deploy/scripts/profiles/*.env` (for example `healthcare-rg.env`,
which reuses that resource group's registry, environment, Key Vault and Postgres server).

ACR Tasks uses the classic Docker builder, which rejects `COPY --chmod`. The `Containerfile`
replaces both `COPY --chmod=0755` lines with `COPY` plus `RUN chmod 0755`.
`deploy/scripts/02-build-images.sh` fails fast if a `COPY --chmod` line returns.

**Merge guidance:** if upstream adds a new `COPY --chmod` line, convert it to the same form.
Check new required settings (for example `DEFAULT_USER_PASSWORD`) against
`deploy/scripts/03-deploy-gateway.sh` before rollout.
