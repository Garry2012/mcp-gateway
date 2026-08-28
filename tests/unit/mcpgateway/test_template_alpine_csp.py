# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_template_alpine_csp.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Guard admin templates against CSP-incompatible Alpine ``x-data`` declarations.
The admin UI bundles the CSP-safe Alpine build (``@alpinejs/csp``, imported in
``mcpgateway/admin_ui/alpine-setup.js``). Its expression parser accepts object
literals made of plain data only. A single function - method shorthand
``foo() {}`` or an arrow property ``foo: () => {}`` - makes the *entire*
``x-data`` object fail to parse.

The failure is silent: Alpine raises nothing, initialises the component as
``{}``, and every field then evaluates as "Undefined variable". The affected
panel renders empty and issues no network requests, which reads as a backend or
data problem rather than a template one.

That is exactly how the observability dashboard broke - it declared a ~420 line
inline object with ~30 methods, so the panel stayed blank while the traces API
returned data correctly. The fix was to register it through ``Alpine.data()``
instead, which keeps the functions out of the attribute parser.

These tests fail fast if a template reintroduces the pattern, including via an
upstream merge.
"""

# Future
from __future__ import annotations

# Standard
from pathlib import Path
import re
import subprocess
from typing import List, Tuple

# Third-Party
import pytest

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "mcpgateway" / "templates"
ALPINE_SETUP = Path(__file__).resolve().parents[3] / "mcpgateway" / "admin_ui" / "alpine-setup.js"

# Method shorthand (``name(args) {``) or an arrow function anywhere in the object.
_METHOD_SHORTHAND = re.compile(r"\b[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{")
_ARROW_FN = re.compile(r"=>")


def _extract_inline_x_data(text: str) -> List[Tuple[int, str]]:
    """Return ``(line_number, object_source)`` for each inline ``x-data="{...}"``.

    Brace matching is used rather than a regex so that nested objects are
    captured in full instead of stopping at the first ``}``.

    Args:
        text: Full template source.

    Returns:
        One entry per inline object literal found.
    """
    found: List[Tuple[int, str]] = []
    for match in re.finditer(r'x-data\s*=\s*"\s*\{', text):
        start = text.index("{", match.start())
        depth = 0
        end = None
        for idx in range(start, len(text)):
            char = text[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
            elif char == '"':
                # The attribute is double-quoted, so an unescaped quote ends it.
                break
        if end is None:
            continue
        found.append((text.count("\n", 0, start) + 1, text[start:end]))
    return found


def _templates() -> List[Path]:
    """Return every admin HTML template.

    Returns:
        Sorted list of template paths.
    """
    return sorted(TEMPLATES_DIR.glob("*.html"))


def test_templates_directory_is_present():
    """The guard is meaningless if it silently scans nothing."""
    assert TEMPLATES_DIR.is_dir(), f"templates directory missing: {TEMPLATES_DIR}"
    assert _templates(), "no templates found to scan"


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_inline_x_data_contains_no_functions(template: Path):
    """Inline ``x-data`` objects must hold plain data only.

    Args:
        template: Template file under test.
    """
    text = template.read_text(encoding="utf-8", errors="replace")
    offenders = []
    for line_no, obj in _extract_inline_x_data(text):
        if _METHOD_SHORTHAND.search(obj) or _ARROW_FN.search(obj):
            offenders.append(line_no)

    assert not offenders, (
        f"{template.name}: inline x-data at line(s) {offenders} contains a function. "
        "The CSP-safe Alpine build cannot parse this and will initialise the component "
        "as an empty object without raising, leaving the panel blank. Register the "
        "component with Alpine.data() in mcpgateway/admin_ui/components/ instead."
    )


def test_observability_dashboard_is_registered():
    """The observability panel must resolve to a registered component."""
    partial = TEMPLATES_DIR / "observability_partial.html"
    text = partial.read_text(encoding="utf-8")

    assert 'x-data="observabilityDashboard"' in text, "observability_partial.html should reference the registered component by name"

    setup = ALPINE_SETUP.read_text(encoding="utf-8")
    assert "Alpine.data('observabilityDashboard'" in setup, "observabilityDashboard is referenced by the template but never registered in alpine-setup.js"


_DIRECTIVE = r'(?:x-[a-z:.-]+|@[a-z:.-]+|:[a-z-]+)\s*=\s*"([^"]*)"'


def _directive_values(text: str):
    """Yield ``(line_number, directive_source)`` for Alpine directives outside ``<script>``.

    Args:
        text: Template source.

    Yields:
        Tuples of line number and the directive's expression text.
    """
    stripped = re.sub(r"<script\b.*?</script>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for match in re.finditer(_DIRECTIVE, stripped):
        yield stripped.count("\n", 0, match.start()) + 1, match.group(1)


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_directives_avoid_unsupported_syntax(template: Path):
    """Directives must avoid syntax the CSP expression parser cannot compile.

    Optional chaining raises ``Unexpected token: PUNCTUATION "."`` because the
    parser reads ``?`` and then meets ``.``. Template literals raise
    ``Unexpected token: OPERATOR "`"``. Both abort the directive silently from
    the user's point of view - the bound element simply never updates.

    Property access, method calls, ternaries, comparisons, string concatenation
    and indexing are all supported, so these rewrite cleanly:
    ``a?.b || 'x'`` becomes ``a && a.b ? a.b : 'x'``, and ```${a} ${b}``` becomes
    ``a + ' ' + b``.

    Args:
        template: Template file under test.
    """
    offenders = []
    for line_no, expr in _directive_values(template.read_text(encoding="utf-8", errors="replace")):
        if "?." in expr:
            offenders.append(f"line {line_no}: optional chaining in {expr[:70]!r}")
        elif "`" in expr:
            offenders.append(f"line {line_no}: template literal in {expr[:70]!r}")

    assert not offenders, f"{template.name}: " + "; ".join(offenders)


def _registered_components() -> set:
    """Return component names registered through ``Alpine.data()``.

    Returns:
        Set of registered component names.
    """
    names = set()
    for js in ALPINE_SETUP.parent.rglob("*.js"):
        names |= set(re.findall(r"Alpine\.data\(\s*['\"]([A-Za-z_$][\w$]*)['\"]", js.read_text(encoding="utf-8", errors="replace")))
    return names


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_x_data_names_resolve_to_registered_components(template: Path):
    """A named ``x-data`` must resolve to a component registered with ``Alpine.data()``.

    The CSP build looks the name up in Alpine's component registry; it does not
    evaluate arbitrary global expressions. The call form is fine - both
    ``x-data="overflowMenu"`` and ``x-data="overflowMenu('table')"`` work,
    including with arguments - but only when the name is registered.

    The four observability sub-views used ``x-data="createToolsController()"``
    with the factory merely assigned to ``window``. That failed as
    ``Undefined variable: createToolsController``, initialised the component
    empty, and left each view blank with no error surfaced to the user.

    Args:
        template: Template file under test.
    """
    text = template.read_text(encoding="utf-8", errors="replace")
    registered = _registered_components()
    offenders = []
    for match in re.finditer(r'x-data\s*=\s*"([^"]*)"', text):
        value = match.group(1).strip()
        if value.startswith("{"):
            continue  # plain object literals are covered by the inline-function test
        name = re.match(r"^([A-Za-z_$][\w$]*)", value)
        if not name:
            continue
        if name.group(1) not in registered:
            offenders.append(f"line {text.count(chr(10), 0, match.start()) + 1}: {name.group(1)!r}")

    assert not offenders, f"{template.name}: x-data names not registered via Alpine.data(): " + "; ".join(offenders)


def test_chart_registry_is_not_read_from_window_root():
    """The chart registry lives on ``Admin``, not on ``window`` directly.

    ``app.js`` defines ``Admin.chartRegistry`` inside an IIFE closed over
    ``window.Admin``. Reading ``window.chartRegistry`` yields ``undefined``, and
    calling a method on it throws a ``TypeError``.

    In ``tabs.js`` that throw propagated out of the tab-switch handler, so
    leaving the observability tab failed with "Failed to switch to <name> tab"
    and the panel never changed. The block is gated on the observability panel
    being visible, so it only became reachable once observability was enabled.
    """
    admin_ui = Path(__file__).resolve().parents[3] / "mcpgateway" / "admin_ui"
    offenders = []
    for js in sorted(admin_ui.rglob("*.js")):
        for line_no, line in enumerate(js.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.lstrip()
            # Comments may legitimately name the broken reference when explaining it.
            if stripped.startswith(("//", "*", "/*")):
                continue
            if re.search(r"\bwindow\.chartRegistry\b", line):
                offenders.append(f"{js.relative_to(admin_ui)}:{line_no}")

    assert not offenders, "window.chartRegistry is always undefined; use window.Admin.chartRegistry instead: " + ", ".join(offenders)


def test_referenced_local_stylesheets_exist():
    """Templates must not link stylesheets that are neither shipped nor built.

    A genuinely missing file is served as a JSON 404, which browsers reject with
    a MIME type error on every page load - that is how the orphaned
    ``auth-animations.css`` link went unnoticed after the file was deleted in
    ``9dfdcf545``.

    Build outputs are excluded. ``tailwind.min.css`` is generated by
    ``make build-ui`` and is gitignored, so it is absent from a clean checkout;
    treating that as a failure would make this test fail on any fresh clone and
    in CI before the UI build step, which is worse than not having the test.
    A path is therefore only reported when it is missing *and* not ignored by
    git - i.e. it is neither committed nor produced by the build.
    """
    root = Path(__file__).resolve().parents[3]
    static_dir = root / "mcpgateway" / "static"

    candidates = []
    for template in _templates():
        text = template.read_text(encoding="utf-8", errors="replace")
        for href in re.findall(r'<link[^>]+href="\{\{ root_path \}\}/static/([^"]+\.css)"', text):
            if not (static_dir / href).exists():
                candidates.append((template.name, href))

    if not candidates:
        return

    # `git check-ignore` exits 0 for paths git ignores, i.e. build artifacts.
    def _is_build_artifact(href: str) -> bool:
        """Return True when git ignores this path, marking it a build output.

        Args:
            href: Path relative to the static directory.

        Returns:
            True if git ignores the path.
        """
        rel = f"mcpgateway/static/{href}"
        try:
            return subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel], check=False).returncode == 0
        except OSError:  # git unavailable - fall back to reporting it
            return False

    missing = [f"{name} -> static/{href}" for name, href in candidates if not _is_build_artifact(href)]

    assert not missing, "templates link stylesheets that are neither committed nor built: " + "; ".join(missing)
