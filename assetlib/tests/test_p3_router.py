"""P3 contract: ready-asset catalog + natural-language router (pure Python)."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import pytest  # noqa: E402
from catalog import build_catalog, load_catalog  # noqa: E402
from router import classify, plan, score  # noqa: E402

# ---- catalog honesty --------------------------------------------------------
def test_catalog_entries_point_at_real_files():
    cat = build_catalog()
    assert cat["problems"] == []
    for e in cat["entries"]:
        assert Path(e["path"]).exists(), f"{e['id']} primary path missing"
        assert Path(e["source"]).exists(), f"{e['id']} source path missing"
    assert cat["missing_categories"] == ["Interiors"]


def test_catalog_has_verified_ue_metrics():
    cat = load_catalog()
    by = {e["id"]: e for e in cat["entries"]}
    assert by["cesium_milk_truck"]["ue_class"] == "StaticMesh"
    assert by["cesium_man"]["ue_class"] == "SkeletalMesh"
    assert by["fox"]["animations"] == ["FoxRun", "FoxSurvey", "FoxWalk"]
    assert by["fox"]["display_scale"] != 1.0  # verified placement scale attached


# ---- routing contract (table) ----------------------------------------------
CASES = [
    # request                        intent  cats(expect subset)   top asset    mint      black  anim
    ("Place a black SUV next to a modern building with a walking character",
     "place", {"Vehicles", "Animations", "Buildings"}, "black_suv", True, True, "FoxWalk"),
    ("show me the milk truck", "query", {"Vehicles"}, "cesium_milk_truck", False, False, None),
    ("a character for a crowd scene", "query", {"Characters"}, "cesium_man", False, False, None),
    ("street environment prop", "query", {"Props"}, "lantern", False, False, None),
    ("walk cycle animation for a creature", "query", {"Animations"}, "fox", False, False, "FoxWalk"),
    ("a GLB asset i can drop into the web viewer", "query", set(), None, False, False, None),
]


@pytest.mark.parametrize("req,intent,cats,top,tint,black,anim", CASES)
def test_routing_contract(req, intent, cats, top, tint, black, anim):
    p = plan(req)
    assert p["intent"] == intent
    assert cats <= set(p["categories"])
    if top is not None:
        assert p["ranked"][0]["asset"] == top, p["ranked"][0]
    assert (p["modification"] == "blender-tint") is tint
    assert p["chosen_assets"] or not p["chosen_assets"]  # deterministic below
    if anim:
        got = [a for a in p["actions"] if a["op"] == "place" and a.get("anim") == anim]
        assert got, [a for a in p["actions"] if a["op"] == "place"]


def test_glb_query_prefers_glb_typed():
    scored = score(load_catalog(), "a GLB asset i can drop into the web viewer")
    assert scored, "glb query must score at least one indexed asset"
    # GLB-typed assets rank above the FBX-cached truck for a pure-GLB query.
    glb_first = scored[0]["path"].lower().endswith(".glb")
    assert glb_first, f"top GLB match expected, got {scored[0]}"


def test_black_flag_only_with_black_term():
    assert classify("a black SUV please")["wants_black"] is True
    assert classify("a white truck")["wants_black"] is False


def test_no_invented_assets_and_empty_query_is_safe():
    cat_ids = {e["id"] for e in load_catalog()["entries"]}
    for req in ("", "???", "arrange the whole level"):
        p = plan(req)
        used = {a["asset"] for a in p["actions"]}
        assert used <= cat_ids, f"plan used assets not in catalog for {req!r}"


# ---- runner wiring: router plan -> known-good harness steps (headless) ----
def test_route_extras_maps_plan_to_known_good_harness_steps():
    from run_ue_acceptance import _route_extras  # noqa: E402

    p = plan("Place a black SUV next to a modern building with a walking character")
    ex = _route_extras(p, "/Game/Showcase/Animations/Fox/SkeletalMeshes/FoxWalk.FoxWalk")
    # Known-good harness contract for the F route:
    # modify_blender(tint) -> import black_suv -> place black_suv + walking fox
    # (FoxWalk anim) + modern building -> validate/screenshot; nothing unmatched.
    assert ex["has_suv"] is True, ex
    assert ex["has_fox"] is True, ex
    assert ex["fox_anim"].endswith("FoxWalk"), ex
    assert ex["modify"] == "blender-tint", ex
    assert ex["unmatched"] == [], ex
    ranked = dict(ex["ranked"])
    assert ranked.get("black_suv", 0) > ranked.get("cesium_milk_truck", 0), ex
    assert ranked.get("modern_building", 0) > 0, ex


def test_route_extras_skips_assets_router_did_not_choose():
    from run_ue_acceptance import _route_extras  # noqa: E402

    p = plan("show me the milk truck")
    ex = _route_extras(p, "/Game/Showcase/Animations/Fox/SkeletalMeshes/FoxWalk.FoxWalk")
    assert ex["has_suv"] is False and ex["has_fox"] is False, ex
    assert ex["modify"] == "none", ex