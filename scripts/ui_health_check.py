"""UI health check for the Aivido Director's Booth.

Cross-checks that every element id referenced from aivido.js (via
getElementById / the REFS list / `$("...")` calls) actually exists in
aivido.html. Catches broken element references before they surface as
null-pointer errors at runtime.

Usage:
    python scripts/ui_health_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui" / "aivido.html").read_text(encoding="utf-8")
JS = (ROOT / "ui" / "aivido.js").read_text(encoding="utf-8")

# ids created at runtime inside JS template strings (modal fields etc.) —
# legitimately absent from the static HTML but resolvable after render.
DYNAMIC_IDS = {"wsName", "wsTpl"}

html_ids = set(re.findall(r'id="([^"]+)"', HTML))
html_ids |= DYNAMIC_IDS

# ids referenced from JS: getElementById("x"), $("x"), $(`x`), $("#x") (jQuery style not used here)
js_ids = set(re.findall(r'getElementById\("([^"]+)"\)', JS))
js_ids |= set(re.findall(r'\$\("([^"]+)"\)', JS))
# template-literal lookups like $("moreSheet") already covered; also bare `$(id)` uses a variable
# grab ids used via querySelector("#...") too
js_ids |= set(re.findall(r'querySelector\("#([^"\s]+)"\)', JS))

missing = sorted(js_ids - html_ids)
extra_html = sorted(html_ids - js_ids)

print(f"html ids: {len(html_ids)} | js-referenced ids: {len(js_ids)}")
if missing:
    print("MISSING IN HTML (referenced by JS but no id= present):")
    for m in missing:
        print("  -", m)
    sys.exit(1)

print("PASS — every JS element reference resolves to an id in aivido.html.")
if extra_html:
    print(f"(info: {len(extra_html)} html ids not referenced by JS — expected for static/event targets)")