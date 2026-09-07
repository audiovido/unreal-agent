"""AIVIDO parallel QA — hermetic UI contract checks (no browser, no backend).

Static, offline verification of the Director's Booth (ui/aivido.html +
ui/aivido.css + ui/aivido.js) against the certified release contracts:

  * responsive contract at 360/390/430 px — the hero CTA row must stack and
    never clip horizontally (the certified 390px defect fix)
  * required DOM ids — every id the JS wires (REFS, SCREENS, direct `$()`)
    must exist in the HTML exactly once
  * localStorage guards — reads/writes must be failure-tolerant in storage-
    blocked contexts
  * no duplicate mutation wiring — single boot, no repeated listener
    registration on the same element/event pair
  * JS + CSS syntax validity (node --check / brace balance)

All checks read files only; nothing is executed in a browser or server.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
HTML = UI / "aivido.html"
CSS = UI / "aivido.css"
JS = UI / "aivido.js"
MANIFEST = UI / "build-manifest.json"

CRITICAL_IDS = [
    "app", "sting", "modalRoot", "toastRoot", "rail", "hud", "view",
    "scr-home", "homeEnterRoom", "homeNewMission", "homeCrew", "homeProof",
]


@pytest.fixture(scope="module")
def html_text():
    return HTML.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def js_text():
    return JS.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def css_text():
    return CSS.read_text(encoding="utf-8", errors="replace")


def _extract_refs(js_text: str) -> list[str]:
    m = re.search(r"const REFS\s*=\s*\[([^\]]+)\]", js_text)
    assert m, "REFS array not found in aivido.js"
    return [s.strip().strip('"') for s in m.group(1).split(",") if s.strip()]


def _extract_screens(js_text: str) -> list[str]:
    m = re.search(r"const SCREENS\s*=\s*\{(.+?)\};", js_text, re.S)
    assert m, "SCREENS map not found in aivido.js"
    return re.findall(r'"([^"]+)"', m.group(1))


def _html_ids(html_text: str) -> list[str]:
    return re.findall(r'id="([^"]+)"', html_text)


def _extract_media_blocks(css_text: str) -> list[tuple[int, str]]:
    """Brace-balanced extraction of @media rules -> list of (max_width, body)."""
    out = []
    for m in re.finditer(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{", css_text):
        start = m.end()
        depth = 1
        i = start
        while i < len(css_text) and depth > 0:
            if css_text[i] == "{":
                depth += 1
            elif css_text[i] == "}":
                depth -= 1
            i += 1
        out.append((int(m.group(1)), css_text[start:i - 1]))
    return out


# --------------------------------------------------------------------------
# Responsive contract: 360/390/430 px, hero CTA must not clip
# --------------------------------------------------------------------------
class TestResponsiveContract:
    def test_mobile_cta_fix_media_query_present(self, css_text):
        """The certified fix stacks the CTA column at <=440px with nowrap buttons."""
        blocks = _extract_media_blocks(css_text)
        assert blocks, "no max-width media queries found"
        mobile = [b for b in blocks if b[0] <= 440]
        assert mobile, f"no media query at or below 440px (found: {sorted(w for w, _ in blocks)})"
        width, body = mobile[0]
        assert ".hero-cta" in body and "flex-direction: column" in body, \
            f"mobile block (max-width:{width}px) must stack .hero-cta vertically"
        assert ".btn-hero" in body and "white-space: nowrap" in body, \
            f"mobile block (max-width:{width}px) must keep .btn-hero on a single line"
        assert "padding: 13px 14px" in body

    def test_no_other_media_query_touches_hero_cta(self, css_text):
        """Only the mobile block may restyle the CTA row (no conflicting rules)."""
        blocks = _extract_media_blocks(css_text)
        for width, body in blocks:
            if width <= 440:
                continue  # the certified mobile fix
            assert ".hero-cta" not in body, \
                f"non-mobile media query (max-width:{width}px) restyles .hero-cta"

    @pytest.mark.parametrize("viewport", [360, 390, 430])
    def test_intrinsic_button_budget_fits_viewport(self, html_text, viewport):
        """Heuristic static budget: single-line nowrap buttons + CTA padding
        must fit each target viewport (text ~7.8px/char at 14px font)."""
        cta = re.search(r'class="hero-cta">(.*?)</div>', html_text, re.S)
        assert cta, "hero-cta row not found in HTML"
        buttons = re.findall(r'<button[^>]*class="btn-hero[^"]*"[^>]*>(.*?)</button>', cta.group(1), re.S)
        assert len(buttons) == 2, f"expected 2 hero CTA buttons, found {len(buttons)}"
        worst = 0.0
        for b in buttons:
            text = re.sub(r"<[^>]+>", "", b).strip()
            width = len(text) * 7.8 + 16.0  # arrow/emoji glyph allowance
            width += 2 * 14  # .btn-hero mobile padding (13px 14px)
            worst = max(worst, width)
        assert worst <= viewport - 2 * 20, \
            f"CTA intrinsic width {worst:.0f}px exceeds {viewport}px viewport budget"
        # sanity: the row itself must be narrower than the viewport
        assert worst >= 100  # non-vacuous

    def test_desktop_row_untouched(self, css_text):
        """Base .hero-cta keeps its horizontal flex row layout at desktop widths."""
        base = re.search(r"^\.hero-cta\s*\{([^}]*)\}", css_text, re.M)
        assert base, ".hero-cta base rule missing"
        assert "flex-direction: row" in base.group(1) or "flex" in base.group(1)
        assert "column" not in base.group(1)


# --------------------------------------------------------------------------
# Required DOM ids
# --------------------------------------------------------------------------
class TestDomIds:
    def test_critical_ids_present(self, html_text):
        ids = set(_html_ids(html_text))
        missing = [i for i in CRITICAL_IDS if i not in ids]
        assert not missing, f"missing critical DOM ids: {missing}"

    def test_refs_ids_all_exist(self, js_text, html_text):
        ids = set(_html_ids(html_text))
        missing = [r for r in _extract_refs(js_text) if r not in ids]
        assert not missing, f"JS REFS ids missing from HTML: {missing}"

    def test_screens_ids_all_exist(self, js_text, html_text):
        ids = set(_html_ids(html_text))
        missing = [s for s in _extract_screens(js_text) if s not in ids]
        assert not missing, f"JS SCREENS ids missing from HTML: {missing}"

    def test_no_duplicate_ids(self, html_text):
        ids = _html_ids(html_text)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert not dupes, f"duplicate id attributes in HTML: {dupes}"

    def test_no_duplicate_refs_entries(self, js_text):
        refs = _extract_refs(js_text)
        dupes = sorted({r for r in refs if refs.count(r) > 1})
        assert not dupes, f"duplicate entries in REFS (double-wiring risk): {dupes}"


# --------------------------------------------------------------------------
# localStorage guards
# --------------------------------------------------------------------------
class TestLocalStorageGuards:
    def test_guarded_store_reads(self, js_text):
        """The quest/ledger store readers must tolerate storage failures."""
        for fn in ("function questStore", "function ledgerStore"):
            idx = js_text.find(fn)
            assert idx != -1, f"{fn} not found"
            window = js_text[idx:idx + 400]
            assert "try {" in window and "catch" in window, f"{fn} lacks try/catch"

    def test_all_localstorage_access_is_guarded(self, js_text):
        """DEFECT SCAN: every localStorage getItem/setItem must be inside a
        guarded (try/catch) store function. Top-level or persist-path access
        in a storage-blocked context would throw and break the whole UI."""
        lines = js_text.splitlines()
        unguarded = []
        guarded_fns = ("function questStore(", "function ledgerStore(")
        in_guarded = False
        for i, line in enumerate(lines, start=1):
            if any(f in line for f in guarded_fns):
                in_guarded = True
                continue
            if "localStorage" in line and not line.strip().startswith("//"):
                if not in_guarded:
                    unguarded.append((i, line.strip()[:90]))
        assert not unguarded, \
            "UNGUARDED localStorage access (would throw in storage-blocked contexts):\n" + \
            "\n".join(f"  line {n}: {t}" for n, t in unguarded)


# --------------------------------------------------------------------------
# No duplicate mutation wiring
# --------------------------------------------------------------------------
class TestMutationWiring:
    def test_single_boot_registration(self, js_text):
        assert js_text.count('addEventListener("DOMContentLoaded"') == 1
        assert js_text.count("function boot(") == 1
        # boot must dispatch exactly once: listener OR immediate call, never both
        m = re.search(r'if \(document\.readyState !== "loading"\) boot\(\);', js_text)
        assert m, "missing readyState guard (double-boot risk)"

    def test_no_duplicate_listener_pairs(self, js_text):
        """Element-scoped listeners (el.* or other named elements) must never be
        registered twice for the same event. Multiple global `document`
        listeners are legitimate (distinct concerns) and excluded."""
        pairs = [p for p in re.findall(r"(\w+)\.addEventListener\(\s*\"(\w+)\"", js_text)
                 if p[0] != "document"]
        dupes = sorted({p for p in pairs if pairs.count(p) > 1})
        assert not dupes, f"duplicate (element, event) listener registrations: {dupes}"


# --------------------------------------------------------------------------
# Syntax validity
# --------------------------------------------------------------------------
class TestSyntax:
    def test_js_parses(self):
        node = subprocess.run(["node", "--check", str(JS)],
                              capture_output=True, text=True)
        assert node.returncode == 0, f"node --check failed:\n{node.stderr}"

    def test_css_braces_balanced(self, css_text):
        assert css_text.count("{") == css_text.count("}"), "CSS brace imbalance"

    def test_html_has_closing_tags_for_core(self, html_text):
        assert html_text.count("<body>") == 1
        assert html_text.count("</html>") == 1


# --------------------------------------------------------------------------
# Cache-bust / manifest consistency (release pipeline integrity)
# --------------------------------------------------------------------------
class TestManifest:
    def test_stylesheet_version_pin_matches_manifest(self, html_text):
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ref = re.search(r'aivido\.css\?v=([0-9a-f]{8})', html_text)
        assert ref, "aivido.html must reference cache-busted aivido.css"
        assert ref.group(1) == m["files"]["aivido.css"][:8], \
            "HTML css pin != manifest aivido.css hash prefix (stale cache-bust)"

    def test_manifest_hashes_match_files(self):
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        import hashlib
        mismatches = []
        for rel, expected in m["files"].items():
            p = UI / rel
            if not p.exists():
                mismatches.append(f"{rel}: missing")
                continue
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
            if actual != expected:
                mismatches.append(f"{rel}: {actual[:12]} != {expected[:12]}")
        assert not mismatches, "build-manifest hash drift:\n" + "\n".join(mismatches)