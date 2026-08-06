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
ALLOW='x-contextforge-|mcpContextForge|contextforge:runtime:|contextforge_mcp_runtime|ContextForge Contributors|mcp-context-forge|ICA_ContextForgeICACF|CONTEXTFORGE_ENABLE_RUST_BUILD|github\.com/IBM|contextforge-mcp-rust\.sock|lf-contextforge|LANGFUSE_INIT_(ORG|PROJECT)'

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
         | ALLOW_RE="$ALLOW" LEGACY_RE="$LEGACY_RE" perl -ne '
             my $orig = $_;
             my $stripped = $_;
             $stripped =~ s/$ENV{ALLOW_RE}//gi;
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
