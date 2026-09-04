"""FREEBUFF ASSET: natural-language ready-asset router (P3) — pure Python.

Contract: request -> classify(intent+categories) -> query/score indexed assets
-> modification decision (reuse tint_black hook for the black SUV) -> ordered
UE import/place/validate/screenshot actions for the acceptance runner.
`--plan` mode is headless: never boots UE/Blender. Never invents assets:
every emitted asset id exists in the on-disk catalog; unmatched categories are
reported honestly (Buildings/Interiors are empty - Sponza rejected, Cryengine
license, not CC).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import load_catalog  # noqa: E402

STOPWORDS = {"a", "an", "the", "of", "for", "with", "next", "to", "in", "on",
             "show", "me", "and", "scene", "please", "using",
             "some", "one", "at", "near", "from", "into", "then", "our"}

GLOSSARY = {  # surface terms -> canonical keywords in catalog tags
    "suv": ["suv", "truck", "vehicle"], "car": ["vehicle", "truck"],
    "modern": [], "building": ["building"], "buildings": ["building"],
    "walking": ["walk", "animation"], "walk": ["walk"], "walkcycle": ["walk"],
    "character": ["character"], "crowd": ["crowd", "character"],
    "black": ["black"], "white": [], "street": ["street", "lantern", "prop"],
    "environment": ["environment", "prop"], "prop": ["prop"],
    "glb": ["glb"], "vehicle": ["vehicle"], "truck": ["truck"],
}

CAT_KEYWORDS = {
    "Vehicles": ["vehicle", "truck", "car", "suv"],
    "Characters": ["character", "human", "man", "crowd"],
    "Animations": ["animation", "walk", "run", "walking", "cycle", "anim"],
    "Props": ["prop", "lantern", "light", "environment"],
    "Buildings": ["building", "modern", "architecture"],
    "Interiors": ["interior", "room", "indoor"],
}


def tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in STOPWORDS]


def _expand(terms: list[str]) -> set[str]:
    out = set(terms)
    for t in terms:
        out.update(GLOSSARY.get(t, []))
    return out


def classify(query: str) -> dict:
    terms = tokens(query)
    intent = "place" if any(t in ("place", "put", "deliver", "spawn", "build", "create", "make")
                            for t in terms) or not terms else "query"
    cats = set()
    for cat, kws in CAT_KEYWORDS.items():
        if any(kw in terms or kw in _expand(terms) for kw in kws):
            cats.add(cat)
    return {"intent": intent, "terms": terms,
            "categories": sorted(cats),
            "wants_black": "black" in terms}


def _filter_by_validation(catalog: dict, min_status: str = "valid") -> dict:
    """Return a catalog copy filtered by minimum validation status.

    Status order: indexed < pending < valid < verified
   Entries below min_status are removed."""
    status_order = ["indexed", "pending", "valid", "verified"]
    if min_status not in status_order:
        return catalog
    min_idx = status_order.index(min_status)
    filtered_entries = [e for e in catalog["entries"]
                        if status_order.index(e.get("validation_status", "indexed")) >= min_idx]
    return {**catalog, "entries": filtered_entries}


def _filter_by_compatibility(catalog: dict, engine_version: str = "5.8") -> dict:
    """Return a catalog filtered by UE engine compatibility.

    Only entries with ue_compatible matching (or exceeding) the given version are kept."""
    # Simple version string comparison: "5.8" matches "5.8" exactly;
    # entries without ue_compatible are kept (assumed compatible)
    filtered_entries = []
    for e in catalog["entries"]:
        compat = e.get("ue_compatible")
        if not compat or compat == engine_version:
            filtered_entries.append(e)
        elif compat >= engine_version:
            # Allow newer engine versions to pass through
            filtered_entries.append(e)
    return {**catalog, "entries": filtered_entries}


def score(catalog: dict, query: str, *, min_validation: str = "indexed",
          engine_compat: str | None = None) -> list[dict]:
    """Return all catalog entries scored for query, highest first.

    Optional filters:
      min_validation: minimum validation status to include (default: "indexed")
      engine_compat: only include entries compatible with this UE version (default: none)
    """
    # Apply validation filter first
    filtered_cat = _filter_by_validation(catalog, min_validation)
    # Then apply compatibility filter
    if engine_compat:
        filtered_cat = _filter_by_compatibility(filtered_cat, engine_compat)

    terms = tokens(query)
    expanded = _expand(terms)
    results = []
    for e in filtered_cat["entries"]:
        pts = 0
        blob = " ".join([e["id"], e["name"], e["category"].lower()]
                        + list(e.get("tags") or []))
        blob_l = blob.lower()
        hits = []
        for t in expanded:
            if t and t != "glb" and re.search(r"\b" + re.escape(t) + r"\b", blob_l):
                pts += 2
                hits.append(t)
        for t in terms:
            if t == "glb":  # GLB query prefers GLB-typed entries
                if str(e["path"]).lower().endswith(".glb"):
                    pts += 1
                continue
            if re.search(r"\b" + re.escape(t) + r"\b", e["id"].lower()):
                pts += 3
        if any(t in e["id"] for t in expanded if t):  # id-substring nudge
            pts += 2
        if e["id"] == "black_suv" and "black" in expanded:  # black query -> derived black SUV
            pts += 3
        if pts > 0:
            results.append({
                "asset": e["id"], "score": pts, "category": e["category"],
                "matched_terms": sorted(set(hits)), "name": e["name"],
                "ue_class": e["ue_class"], "animations": e["animations"],
                "path": e["path"], "license": e["license"],
                "format": e.get("format", "unknown"),
                "materials": e.get("materials", []),
                "validation_status": e.get("validation_status", "indexed"),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def plan(query: str) -> dict:
    cat = load_catalog()
    scored = score(cat, query)
    cls = classify(query)
    want_black = cls["wants_black"]
    chosen = [r["asset"] for r in scored if r["score"] > 0]

    actions: list[dict] = []
    notes: list[str] = []
    # 1) Black-SUV route: requires the derived BlackSUV (Blender tint hook).
    if want_black and any(a == "black_suv" for a in chosen):
        actions.append({
            "op": "modify_blender", "tool": "assetlib/tools/tint_black.py",
            "inputs": {"fbx_in": "assetlib/content/Vehicles/CesiumMilkTruck/CesiumMilkTruck.fbx"},
            "outputs": {"fbx_out": "assetlib/tests/ue/nlr_in/BlackSUV.fbx"},
            "note": "reuse proven tint hook only if black_suv FBX missing on disk",
        })
    # 2) Import specs for entries not yet UE-verified (unimported on disk set).
    for a in chosen:
        e = next(x for x in cat["entries"] if x["id"] == a)
        if not e.get("ue_class"):
            actions.append({
                "op": "import", "spec": {
                    "id": a, "category": e["category"],
                    "file": e["path"], "dest": f"/Game/NLR/{e['id']}",
                    "expect_class": "StaticMesh" if e["category"] == "Vehicles" else "StaticMesh",
                }})
    # 3) Place + validate + screenshot for every chosen asset.
    for a in chosen:
        e = next(x for x in cat["entries"] if x["id"] == a)
        act = {"op": "place", "asset": a, "display_scale": e.get("display_scale", 1.0)}
        if e.get("animations") and any(t in {"walk", "animation", "walking", "cycle"}
                                       for t in cls["terms"]):
            act["anim"] = f"{e['animations'][0]}" if len(e["animations"]) == 1 \
                else next((n for n in e["animations"] if "walk" in n.lower()), e["animations"][0])
            notes.append(f"animation '{act['anim']}' selected for {a}")
        actions.append(act)
        actions.append({"op": "validate", "asset": a,
                        "checks": ["class", "size_cm", "materials", "collision"]})
        actions.append({"op": "screenshot", "asset": a})

    unmatched = [c for c in cls["categories"]
                 if c in ("Buildings", "Interiors") and not any(
                     x for x in cat["entries"] if x["category"] == c)]
    if unmatched:
        notes.append(f"unmatched category(ies): {unmatched} - no indexed asset "
                     f"(Sponza rejected: Cryengine license, not CC); scene falls "
                     f"back to available environment/prop only")
    return {"query": query, "intent": cls["intent"],
            "categories": cls["categories"], "ranked": scored,
            "chosen_assets": chosen,
            "modification": "blender-tint" if want_black and "black_suv" in chosen else "none",
            "actions": actions, "notes": notes, "unmatched": unmatched,
            "headless": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=None, help="natural-language request (headless plan mode)")
    args = ap.parse_args()
    if not args.plan:
        print("usage: python router.py --plan \"<request>\"", file=sys.stderr)
        return 2
    p = plan(args.plan)
    print(json.dumps(p, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())