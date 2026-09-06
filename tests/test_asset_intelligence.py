"""Hermetic regression tests for the Asset Intelligence layer (Phase E).

Pure Python, no engine, no network. Uses in-memory fixture entries shaped
exactly like the real assetlib catalog schema.
"""
from __future__ import annotations

from core.asset_intelligence import (
    classify_entry,
    detect_duplicates,
    load_catalog_entries,
    recommend_assets,
    score_relevance,
    search_assets,
    select_lod,
    tokens,
)
from core.production_pipeline import production_preflight

TRUCK = {
    "id": "cesium_milk_truck", "category": "Vehicles", "name": "Cesium Milk Truck",
    "license": "CC-BY 4.0", "source": "C:/x/Models/CesiumMilkTruck.glb",
    "path": "C:/x/content/Vehicles/CesiumMilkTruck/CesiumMilkTruck.fbx",
    "preview": "", "tags": ["truck", "vehicle", "milk truck", "suv proxy", "car"],
    "desc": "Khronos official glTF sample", "ue_class": "StaticMesh",
    "size_cm": [279.2, 486.89, 231.76], "skeleton": None, "animations": [],
    "display_scale": 1.0, "lod": "LOD0 only", "collision": "auto", "ue_compatible": "5.8",
}
SUV = {
    "id": "black_suv", "category": "Vehicles", "name": "Black SUV (derived)",
    "license": "derived from cesium_milk_truck (CC-BY)",
    "source": "C:/x/content/Vehicles/CesiumMilkTruck/CesiumMilkTruck.fbx",
    "path": "D:/AI/_Assets/Vehicles/BlackSUV.fbx", "preview": "",
    "tags": ["suv", "black", "vehicle", "car", "derived"],
    "desc": "Blender-tinted variant", "ue_class": None, "size_cm": None,
    "skeleton": None, "animations": [], "display_scale": 1.0, "lod": "LOD0 only",
    "collision": "auto", "ue_compatible": "5.8",
}
MAN = {
    "id": "cesium_man", "category": "Characters", "name": "Cesium Man",
    "license": "CC-BY 4.0", "source": "C:/x/Models/CesiumMan.glb",
    "path": "C:/x/content/Characters/CesiumMan/CesiumMan.glb", "preview": "",
    "tags": ["character", "human", "rigged", "animation", "crowd"],
    "desc": "Khronos official glTF sample, rigged", "ue_class": "SkeletalMesh",
    "size_cm": [111.0, 35.0, 160.0], "skeleton": "SKM_CesiumMan", "animations": [],
    "display_scale": 1.0, "lod": "LOD0-LOD3", "collision": "auto", "ue_compatible": "5.8",
}
ENTRIES = [TRUCK, SUV, MAN]


# ---------------------------------------------------------------------------
# Relevance scoring + ranking
# ---------------------------------------------------------------------------


def test_scoring_ranks_best_match_first_and_is_auditable():
    ranked = search_assets("black suv", ENTRIES, top_k=3)
    assert ranked[0]["id"] == "black_suv"
    assert ranked[0]["score"] >= ranked[1]["score"]
    assert ranked[0]["matched_terms"]
    assert "name" in ranked[0]["breakdown"]
    assert 0.0 <= ranked[0]["score"] <= 1.0


def test_synonym_expansion_scores_surface_terms():
    # "car" is not in any tag but the glossary maps it to truck/vehicle.
    result = score_relevance("car", TRUCK)
    assert result["score"] > 0.0
    assert "vehicle" in result["matched_synonyms"] or "truck" in result["matched_synonyms"]


def test_ranking_is_deterministic_with_stable_tiebreak():
    first = search_assets("truck vehicle", ENTRIES, top_k=3)
    second = search_assets("truck vehicle", ENTRIES, top_k=3)
    assert first == second


def test_min_score_filters_weak_matches():
    ranked = search_assets("quantum physics equations", ENTRIES, top_k=3, min_score=0.2)
    assert ranked == []


def test_tokenizer_removes_stopwords():
    assert "the" not in tokens("place the black suv in the scene")
    assert "suv" in tokens("place the black suv in the scene")


# ---------------------------------------------------------------------------
# Evidence-first: never invent availability
# ---------------------------------------------------------------------------


def test_empty_catalog_yields_empty_results():
    assert search_assets("black suv", []) == []
    decision = recommend_assets("black suv", [])
    assert decision["ranked"] == []
    assert decision["proven"] is True  # every candidate came from the entries arg


def test_load_catalog_entries_is_never_inventing(tmp_path):
    missing = load_catalog_entries(str(tmp_path / "nope.json"))
    assert missing == []
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json !!!", encoding="utf-8")
    assert load_catalog_entries(str(bad)) == []


def test_real_catalog_loads_if_present():
    entries = load_catalog_entries()
    if entries:  # catalog ships in-tree; absent only on exotic checkouts
        assert all(e.get("id") for e in entries)
        assert any(e["category"] == "Vehicles" for e in entries)


# ---------------------------------------------------------------------------
# Classification, duplicates, LOD
# ---------------------------------------------------------------------------


def test_classify_entry_derives_missing_category_from_evidence():
    entry = dict(TRUCK)
    entry["category"] = ""
    category, evidence = classify_entry(entry)
    assert category == "Vehicles"
    assert evidence  # which keyword drove it
    untouched = classify_entry(MAN)
    assert untouched[0] == "Characters"


def test_duplicate_detection_groups_shared_source_stem():
    groups = detect_duplicates([TRUCK, SUV])
    assert len(groups) == 1
    assert groups[0]["kind"] == "duplicate_candidates"
    assert {m["id"] for m in groups[0]["members"]} == {"cesium_milk_truck", "black_suv"}
    assert groups[0]["evidence"]


def test_duplicate_detection_leaves_distinct_assets_alone():
    assert detect_duplicates([TRUCK, MAN]) == []


def test_lod_selection_never_claims_unavailable_lods():
    only0 = select_lod(TRUCK, distance_m=60.0)
    assert only0["recommended_lod"] == 0
    assert "not available" in only0["note"]
    full = select_lod(MAN, distance_m=30.0)
    assert full["recommended_lod"] == 2
    assert full["max_available_lod"] == 3
    unknown = select_lod({"id": "x", "lod": ""}, distance_m=12.0)
    assert unknown["recommended_lod"] == 0
    assert "unknown" in unknown["note"]


def test_recommend_assets_full_flow():
    decision = recommend_assets("place a black suv near the street", ENTRIES, distance_m=14.0)
    assert decision["intent"] == "place"
    assert decision["ranked"][0]["id"] == "black_suv"
    assert decision["lod_recommendation"] is not None
    assert decision["duplicates"]  # truck/suv share the source stem
    assert decision["catalog_entry_count"] == 3


# ---------------------------------------------------------------------------
# Pipeline integration (backward compatible)
# ---------------------------------------------------------------------------


def test_preflight_attaches_asset_intelligence_only_when_assets_supplied():
    with_assets = production_preflight(
        "make a premium lobby with a black suv", assets=ENTRIES
    )
    assert with_assets["asset_intelligence"]["ranked"][0]["id"] == "black_suv"
    assert with_assets["asset_intelligence"]["proven"] is True
    without = production_preflight("make a premium lobby with a black suv")
    assert "asset_intelligence" not in without  # no catalog I/O by default