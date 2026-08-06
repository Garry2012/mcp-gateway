#!/usr/bin/env bash
#
# check-brand.sh - executable definition of "done" for the brand migration.
#
# Exits 0 when every in-scope surface is free of the legacy brand, non-zero
# otherwise, printing exactly which file and line failed.
#
# This exists so that "is the rebrand finished?" is a command, not an opinion.
#
# Usage:
#   scripts/check-brand.sh              # check all tiers
#   scripts/check-brand.sh ui           # check a single tier
#   BRAND_NEW="Acme Gateway" scripts/check-brand.sh
#
set -uo pipefail

LEGACY_BRAND="${BRAND_LEGACY:-ContextForge}"
NEW_BRAND="${BRAND_NEW:-MCP Gateway}"

# The scan pattern is DERIVED from LEGACY_BRAND so the documented override
# actually works. Previously the pattern was hardcoded and BRAND_LEGACY only
# affected the banner, which made the interface misleading. (REVIEW-001 M-002)
# Matching is case-insensitive at the grep/perl call sites.
LEGACY_RE="$LEGACY_BRAND"

cd "$(dirname "$0")/.." || exit 2

# ---------------------------------------------------------------------------
# ALLOWLIST - occurrences that MUST NOT be renamed.
#
# These are identifiers, not brand text. Renaming any of them breaks a running
# system. Do not add to this list without architect sign-off.
# ---------------------------------------------------------------------------
# Allowlisting is by IDENTIFIER SHAPE, not by enumeration.
#
# Two rounds of review proved enumeration unworkable: the first list was too
# narrow and missed live surfaces; the second was so broad it demanded renaming
# a shared authentication salt and stable telemetry keys. (REVIEW-001 B-001, B-002)
#
# The durable distinction is grammatical, not a list:
#
#   BRAND TEXT is the word standing alone   -> "ContextForge Support Bundle"
#   MACHINE IDENTIFIERS carry a separator   -> contextforge-internal-mcp-runtime-v1
#   or continue in CamelCase                -> ContextForgeMCPServer
#
# So: a legacy-brand occurrence immediately followed by [-_.:] or an uppercase
# letter is an identifier and is exempt. Anything else is prose and must change.
#
# This automatically protects, without needing to know they exist:
#   contextforge-internal-mcp-runtime-v1  SHA-256 auth salt shared with the Rust
#                                         crate; renaming Python alone breaks
#                                         cross-runtime authentication
#   contextforge.gateway_id/.runtime/     OpenTelemetry attribute keys; stable
#     .tool.id/.transport                 telemetry schema consumed by dashboards
#   x-contextforge-*                      wire protocol headers
#   contextforge:runtime:*                Redis coordination keys
#   contextforge_mcp_runtime              Cargo crate name
#   ContextForgeMCPServer                 Python class symbol
#   TRAILING context - an identifier continues after the brand:
#       contextforge-internal-...   contextforge.gateway_id   ContextForgeMCPServer
#   LEADING context - the brand is a segment of a compound identifier:
#       mcpContextForge   (Helm top-level key; may be followed by " ` or nothing,
#                          so a trailing-only rule misses it entirely)
ALLOW_SHAPE='[Cc]ontext[Ff]orge[-_.:]|ContextForge[A-Z]|CONTEXTFORGE_|[A-Za-z0-9_][Cc]ontext[Ff]orge'

# CASE-SENSITIVE exemptions, applied in a second pass.
#
# All-lowercase `contextforge` standing alone is never prose - it is a machine
# identifier: a Kubernetes namespace, a Helm release name, an OpenTelemetry
# service.namespace, a Langfuse organisation ID, a socket path, an image name.
# Several of these are STATEFUL: renaming a namespace orphans live cluster
# resources, and renaming an observability namespace splits historical data.
#
# This must NOT be folded into ALLOW_SHAPE, which is applied case-insensitively
# and would then also strip the CamelCase brand text we are trying to find.
# (REVIEW-001 B-004)
ALLOW_CASE_SENSITIVE='contextforge|CONTEXTFORGE'

# Literal exemptions that are prose but must NOT change: upstream attribution,
# upstream URLs and package names, and third-party project identifiers.
ALLOW_LITERAL='ContextForge Contributors|mcp-context-forge|ICA_ContextForgeICACF|github\.com/IBM|lf-contextforge|LANGFUSE_INIT_(ORG|PROJECT)'

ALLOW="$ALLOW_SHAPE|$ALLOW_LITERAL"

#   x-contextforge-*            wire protocol shared with the Rust runtime crate
#   mcpContextForge.*           Helm value keys; renaming breaks existing values.yaml
#   contextforge:runtime:*      Redis coordination keys; renaming splits a live cluster
#   contextforge_mcp_runtime    Cargo crate name
#   ContextForge Contributors   upstream copyright attribution
#   MCP-CONTEXT-FORGE           SPDX header line in every source file
#   mcp-context-forge           upstream repo / package name in URLs and deps
#   ICA_ContextForgeICACF       upstream security issue reference
#   CONTEXTFORGE_ENABLE_RUST_BUILD  documented env var consumed by build tooling
#   github.com/IBM              upstream repository links

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; NC=$'\033[0m'
FAILED=0
REQUESTED_TIER="${1:-all}"

# scan <tier-name> <description> <path...>
scan() {
  local tier="$1"; shift
  local desc="$1"; shift

  if [[ "$REQUESTED_TIER" != "all" && "$REQUESTED_TIER" != "$tier" ]]; then
    return 0
  fi

  local hits
  # Substring-aware allowlisting.
  #
  # A whole-line `grep -v` is wrong here: a line can contain BOTH a protected
  # identifier and visible legacy branding, e.g.
  #     ![ContextForge](https://ibm.github.io/mcp-context-forge/images/x.gif)
  # Dropping that line hides the alt text because the URL is allowlisted.
  #
  # Instead: strip allowlisted substrings from a copy of the line, then test
  # whether the legacy brand still survives. Print the ORIGINAL line so the
  # output stays actionable. (REVIEW-001 B-001)
  hits=$(git grep -nI -iE "$LEGACY_RE" -- "$@" 2>/dev/null \
         | ALLOW_RE="$ALLOW" ALLOW_CS="$ALLOW_CASE_SENSITIVE" LEGACY_RE="$LEGACY_RE" perl -ne '
             my $orig = $_;
             my $stripped = $_;
             # Pass 1: shape and literal exemptions, case-insensitive.
             $stripped =~ s/$ENV{ALLOW_RE}//gi;
             # Pass 2: bare lowercase/uppercase machine identifiers. Case-SENSITIVE,
             # so CamelCase brand text survives to be reported.
             $stripped =~ s/$ENV{ALLOW_CS}//g;
             print $orig if $stripped =~ /$ENV{LEGACY_RE}/i;
           ' || true)

  if [[ -n "$hits" ]]; then
    echo "${RED}FAIL${NC}  [$tier] $desc"
    echo "$hits" | sed 's/^/        /'
    echo
    FAILED=1
  else
    echo "${GRN}PASS${NC}  [$tier] $desc"
  fi
}

echo "Brand check: '${LEGACY_BRAND}' -> '${NEW_BRAND}'"
echo "==========================================================="
echo

# --- Tier 1: what a user sees in the product -------------------------------
scan ui "Admin UI templates" \
  'mcpgateway/templates/*.html'

scan ui "Admin UI JavaScript" \
  'mcpgateway/admin_ui/'

scan ui "Static assets referenced by name" \
  'mcpgateway/static/*.html'

# --- Tier 2: identity the product asserts at runtime ------------------------
#
# Scans the WHOLE application package rather than an enumerated file list.
# Enumeration proved unsafe: the previous five-file list missed CEF/LEEF SIEM
# identity, support-bundle output, OAuth error text returned to clients, CLI
# help, generated security.txt, and operator-visible config descriptions.
# (REVIEW-001 B-001)
#
# This necessarily also catches docstrings and comments. That is accepted:
# brand strings in prose are cheap to change and rarely collide with upstream
# edits, unlike the colour-class churn that drove earlier scoping decisions.
scan runtime "Application package (all emitted strings, descriptions, docstrings)" \
  'mcpgateway/'

scan runtime "Environment template" \
  '.env.example'

# --- Tier 3: documentation a user or operator reads -------------------------
scan docs "Top-level documentation" \
  'README.md'

scan docs "User-facing documentation tree" \
  'docs/docs/'

scan docs "Operator guides" \
  'DEVELOPING.md' \
  'charts/README.md' \
  'charts/*.md'

# --- Tier 5: deployment configuration -------------------------------------
#
# Config that OVERRIDES the application's own defaults. Scanning the app alone
# is not enough: charts/mcp-stack/values.yaml sets APP_NAME: ContextForge as an
# explicit env var, which beats the Python default in every Helm install, and
# docker-compose.yml and run.sh do the same for other settings.
#
# A gate that ignores these can go green while every actual deployment still
# ships the old brand. (REVIEW-001 B-003)
#
# Helm KEYS (mcpContextForge.*) are identifiers and stay protected by the shape
# allowlist. Helm VALUES (APP_NAME: ContextForge) are brand text and must change.
scan deploy "Helm chart configuration, schema and templates" \
  'charts/' ':(exclude)charts/**/CHANGELOG.md'

scan deploy "Container and process configuration" \
  'docker-compose*.yml' \
  'Containerfile' \
  'docker-entrypoint.sh' \
  'run.sh' \
  'run-gunicorn.sh'

scan deploy "Infrastructure and provisioning" \
  'ansible/' \
  'infra/'

# NOTE: CHANGELOG.md is deliberately NOT scanned. It is a historical record of
# releases made under the upstream name; rewriting it would falsify history.

# --- Tier 4: logo and icon assets ------------------------------------------
if [[ "$REQUESTED_TIER" == "all" || "$REQUESTED_TIER" == "assets" ]]; then
  asset_refs=$(git grep -nI -E "contextforge-(logo|icon)" -- \
                 'mcpgateway/templates/' 'mcpgateway/admin_ui/' 2>/dev/null || true)
  if [[ -n "$asset_refs" ]]; then
    echo "${RED}FAIL${NC}  [assets] Logo/icon image references"
    echo "$asset_refs" | sed 's/^/        /'
    echo
    FAILED=1
  else
    echo "${GRN}PASS${NC}  [assets] Logo/icon image references"
  fi
fi

# --- Guard: allowlisted identifiers must still be intact --------------------
# A careless find-and-replace would silently break these. Assert they survive.
echo
echo "Protected identifiers (must still be present):"
guard() {
  local label="$1" pattern="$2" min="$3"
  local n
  n=$(git grep -cI -E "$pattern" -- . 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')
  if (( n < min )); then
    echo "  ${RED}FAIL${NC}  $label: found $n, expected >= $min - a rename likely broke this"
    FAILED=1
  else
    echo "  ${GRN}OK${NC}    $label ($n)"
  fi
}
guard "x-contextforge-* headers"  'x-contextforge-'          100
guard "mcpContextForge Helm keys" 'mcpContextForge'          100
guard "contextforge:runtime keys" 'contextforge:runtime:'      3
guard "Rust crate name"           'contextforge_mcp_runtime'   5

echo
if (( FAILED )); then
  echo "${RED}BRAND CHECK FAILED${NC}"
  echo "Fix the FAIL lines above, or route a scope change back to the architect."
  exit 1
fi
echo "${GRN}BRAND CHECK PASSED${NC}"
exit 0
