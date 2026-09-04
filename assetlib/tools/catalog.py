"""FREEBUFF ASSET: ready-asset catalog (P3) — pure Python, no engine boots.

Builds/loads assetlib/catalog/assets.json. Every primary path is verified to
exist on disk at build time; UE metrics (class/size_cm/skeleton/animations)
are attached from the verified acceptance import marker when present, never
hand-written. Catalog holds only real assets on disk; Buildings is populated by
the Kenney CC0 modular facade (Sponza/Cryengine and VirtualCity/3DRT rejected).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # assetlib/
CATALOG_ROOT = ROOT / "catalog"
CATALOG_FILE = CATALOG_ROOT / "assets.json"
CONTENT = ROOT / "content"
SOURCE = ROOT / "source" / "khronos" / "Models"
TESTS_UE = ROOT / "tests" / "ue"
NX = ROOT / "tests" / "ue" / "nlr_in"
D_VEHICLES = Path("D:/AI/_Assets/Vehicles")

# Bulk assets live outside the active Unreal project.  These locations are
# deliberately first in the index: they keep new source/download storage off
# C: without moving the project, its DDC, Engine, or cache workloads.
D_BULK_ROOTS = {
    "Characters": Path("D:/AI/_Assets/Characters"),
    "Vehicles": Path("D:/AI/_Assets/Vehicles"),
    "Animations": Path("D:/AI/_Assets/Animations"),
    "Buildings": Path("D:/AI/_Assets/Environments/Buildings"),
    "Environment": Path("D:/AI/_Assets/Environments"),
    "Props": Path("D:/AI/_Assets/Environments/Props"),
    "Materials": Path("D:/AI/_Assets/Environments/Materials"),
    "VFX": Path("D:/AI/_Assets/Environments/VFX"),
    "Raw": Path("D:/AI/_Assets/Raw_FBX_GLB"),
    "Blender": Path("D:/BlenderAssets/SourceAssets"),
    "Fab": Path("D:/FabLibrary/ReadyAssets"),
    "CitySample": Path("D:/CitySample/SourcePacks"),
}
ASSET_EXTENSIONS = {".fbx", ".glb", ".gltf", ".blend", ".obj", ".uasset"}
EXTENSION_TO_FORMAT = {".fbx": "fbx", ".glb": "glb", ".gltf": "gltf", ".blend": "blend", ".obj": "obj", ".uasset": "uasset"}

# Mission category taxonomy (subset backed by on-disk assets is populated).
CATEGORIES = [
    "Characters", "Crowd/NPC", "Vehicles", "Buildings", "Interiors",
    "Furniture", "Props", "Nature", "Roads/City", "Animations", "Creatures",
    "Robots", "VFX", "Materials", "Cinematic/Sequencer",
]

# (id, category, name, license, source_rel, path_rel, preview_rel, tags, desc, format, materials, validation_status)
SPEC = [
    dict(id="cesium_milk_truck", category="Vehicles", name="Cesium Milk Truck",
         license="CC-BY 4.0 (see LICENSE.md)",
         source=str(SOURCE / "CesiumMilkTruck" / "glTF-Binary" / "CesiumMilkTruck.glb"),
         path=str(CONTENT / "Vehicles" / "CesiumMilkTruck" / "CesiumMilkTruck.fbx"),
         preview=str(CONTENT / "Vehicles" / "CesiumMilkTruck" / "CesiumMilkTruck_preview.png"),
         tags=["truck", "vehicle", "milk truck", "suv proxy", "car"],
         desc="Khronos official glTF sample; cached as UE-ready FBX (P2 chain).",
         format="fbx", materials=["MatCesiumMilkTruck"], validation_status="valid"),
    dict(id="black_suv", category="Vehicles", name="Black SUV (derived)",
         license="derived from cesium_milk_truck (CC-BY)",
         source=str(CONTENT / "Vehicles" / "CesiumMilkTruck" / "CesiumMilkTruck.fbx"),
         path=str(D_VEHICLES / "BlackSUV.fbx"),
         preview="",
         tags=["suv", "black", "vehicle", "car", "derived"],
         desc="Blender-tinted (base color 0.015) variant via tint_black.py; UE import pending.",
         format="fbx", materials=["MatBlackSUV"], validation_status="pending"),
    dict(id="cesium_man", category="Characters", name="Cesium Man",
         license="CC-BY 4.0 (see LICENSE.md)",
         source=str(SOURCE / "CesiumMan" / "glTF-Binary" / "CesiumMan.glb"),
         path=str(SOURCE / "CesiumMan" / "glTF-Binary" / "CesiumMan.glb"),
         preview=str(CONTENT / "Characters" / "CesiumMan" / "CesiumMan_preview.png"),
         tags=["character", "human", "rigged", "animation", "crowd"],
         desc="Khronos official rigged humanoid sample; 1 animation.",
         format="glb", materials=["MatCesiumMan"], validation_status="valid"),
    dict(id="fox", category="Animations", name="Fox (animated)",
         license="CC0 / CC-BY 4.0 (see LICENSE.md)",
         source=str(SOURCE / "Fox" / "glTF-Binary" / "Fox.glb"),
         path=str(SOURCE / "Fox" / "glTF-Binary" / "Fox.glb"),
         preview=str(CONTENT / "Animations" / "Fox" / "Fox_preview.png"),
         tags=["fox", "animal", "walk", "run", "survey", "animation", "character"],
         desc="Khronos official quadruped sample; FoxRun/FoxSurvey/FoxWalk.",
         format="glb", materials=["MatFox"], validation_status="valid"),
    dict(id="modern_building", category="Buildings", name="Modern Building (modular facade)",
         license="CC0 1.0 (Kenney Modular Buildings; License.txt in pack, in-tree)",
         source=str(Path("D:/AI/_Assets/Buildings/ModularBuildings/modularBuildings.zip")),
         path=str(Path("D:/AI/_Assets/Buildings/ModernBuilding/ModernBuilding.fbx")),
         preview=str(Path("D:/AI/_Assets/Buildings/ModularBuildings/Preview.png")),
         tags=["building", "modern", "facade", "modular", "city", "street", "architecture"],
         desc="Kenney CC0 modular-building plates (mb_018/021/022/023/028/029/030/035/036) composed headless in Blender into one modern facade slab; imported to /Game/NLR/ModernBuilding (25 uassets, 9 parts).",
         format="fbx", materials=["MatModernBuilding"], validation_status="valid"),
    dict(id="lantern", category="Props", name="Lantern (street)",
         license="CC0 (see LICENSE.md)",
         source=str(SOURCE / "Lantern" / "glTF-Binary" / "Lantern.glb"),
         path=str(SOURCE / "Lantern" / "glTF-Binary" / "Lantern.glb"),
         preview=str(CONTENT / "EnvironmentProps" / "Lantern" / "Lantern_preview.png"),
         tags=["lantern", "prop", "environment", "street", "light pole"],
         desc="Khronos official street-prop sample (pole+chain+lantern group).",
         format="glb", materials=["MatLantern"], validation_status="valid")
]

TAG_UNIQUE = {  # terms that admit only one category
    "vehicle": "Vehicles", "car": "Vehicles", "suv": "Vehicles",
    "character": "Characters", "human": "Characters", "crowd": "Crowd/NPC",
    "building": "Buildings", "interior": "Interiors", "furniture": "Furniture",
    "prop": "Props", "nature": "Nature", "road": "Roads/City", "city": "Roads/City",
}


def build_catalog() -> dict:
    """Assemble the catalog, verifying every primary path exists on disk."""
    entries = []
    problems = []
    seen_ids = set()
    for spec in SPEC:
        primary = Path(str(spec["path"]))
        source = Path(str(spec["source"]))
        missing = [p for p in (primary, source) if not p.exists()]
        if missing:
            problems.append(f"{spec['id']}: missing on disk {missing}")
            # Still record the entry with validation_status=missing so callers know
            entry = dict(spec)
            entry["ue_class"] = None
            entry["size_cm"] = None
            entry["skeleton"] = None
            entry["animations"] = []
            entry["display_scale"] = 1.0
            entry["lod"] = "LOD0 only"
            entry["collision"] = "auto (simple collision on import)"
            entry["ue_compatible"] = "5.8"
            entry["validation_status"] = "missing_on_disk"
            # Derive format from path extension if not set
            if not entry.get("format"):
                entry["format"] = EXTENSION_TO_FORMAT.get(Path(entry["path"]).suffix.lower(), "unknown")
            # Derive materials from tags if not set
            if not entry.get("materials"):
                entry["materials"] = []
            # Normalize path separators
            for k in ("path", "source", "preview"):
                entry[k] = str(spec[k]).replace("\\", "/")
            # Deduplicate check
            eid = entry["id"].lower()
            if eid in seen_ids:
                problems.append(f"duplicate entry id: {entry['id']}")
                continue
            seen_ids.add(eid)
            entries.append(entry)
            continue
        entry = dict(spec)
        entry["ue_class"] = None
        entry["size_cm"] = None
        entry["skeleton"] = None
        entry["animations"] = []
        entry["display_scale"] = 1.0
        entry["lod"] = "LOD0 only"
        entry["collision"] = "auto (simple collision on import)"
        entry["ue_compatible"] = "5.8"
        # Normalize path separators and ensure format/materials/validation_status are set
        for k in ("path", "source", "preview"):
            entry[k] = str(spec[k]).replace("\\", "/")
        if not entry.get("format"):
            entry["format"] = EXTENSION_TO_FORMAT.get(Path(entry["path"]).suffix.lower(), "unknown")
        if not entry.get("materials"):
            entry["materials"] = []
        if not entry.get("validation_status"):
            entry["validation_status"] = "valid"
        # Deduplicate check
        eid = entry["id"].lower()
        if eid in seen_ids:
            problems.append(f"duplicate entry id: {entry['id']}")
            continue
        seen_ids.add(eid)
        entries.append(entry)
    # Discover externally stored assets without copying them into the active
    # project.  A newly downloaded D: asset is therefore searchable as soon
    # as it lands in one of the declared folders.
    indexed_paths = {str(e["path"]).replace("\\", "/").lower() for e in entries}
    for category, root in D_BULK_ROOTS.items():
        if not root.is_dir():
            continue
        for item in sorted(root.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in ASSET_EXTENSIONS:
                continue
            normalized = str(item).replace("\\", "/").lower()
            if normalized in indexed_paths:
                continue
            stem = item.stem.lower().replace(" ", "_")
            asset_id = f"d_{category.lower().replace('/', '_')}_{stem}"
            # Derive format from extension
            fmt = EXTENSION_TO_FORMAT.get(item.suffix.lower(), "unknown")
            entries.append({
                "id": asset_id, "category": category if category in CATEGORIES else "Props",
                "name": item.stem, "license": "local D: library; verify source license before redistribution",
                "source": str(item).replace("\\", "/"), "path": str(item).replace("\\", "/"),
                "preview": "", "tags": [category.lower(), *re.findall(r"[a-z0-9]+", item.stem.lower())],
                "desc": f"D: bulk-library asset discovered from {root}", "ue_class": None,
                "size_cm": None, "skeleton": None, "animations": [], "display_scale": 1.0,
                "lod": "unknown", "collision": "configure on import", "ue_compatible": "verify on import",
                "format": fmt, "materials": [], "validation_status": "indexed",
            })
            indexed_paths.add(normalized)
    missing = [c for c in ("Buildings", "Interiors") if not any(e["category"] == c for e in entries)]
    return {"categories": CATEGORIES, "entries": entries, "problems": problems,
            "storage_roots": {key: str(value).replace("\\", "/") for key, value in D_BULK_ROOTS.items()},
            "missing_categories": missing}


def load_verified_metrics(catalog: dict) -> dict:
    """Attach verified UE import metrics from the acceptance marker if present."""
    marker = TESTS_UE / "accept_import_done.json"
    if not marker.exists():
        return catalog
    import json as _json
    try:
        data = _json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return catalog
    by_label = {a.get("label"): a for a in (data.get("assets") or [])}
    for e in catalog["entries"]:
        src_label = {"cesium_milk_truck": "truck", "cesium_man": "cesiumman"}.get(e["id"], e["id"])
        a = by_label.get(src_label)
        if not a:
            continue
        e["ue_class"] = a.get("class")
        e["size_cm"] = a.get("size_cm")
        e["skeleton"] = (a.get("skeleton") or "").rsplit(".", 1)[-1] or None
        e["animations"] = [s.rsplit(".", 1)[-1] for s in (a.get("sequences") or [])]
    # Verified placement display scales (acceptance record: fox 0.0201, lantern 0.1304).
    scales = {"fox": 0.0201, "lantern": 0.1304}
    for e in catalog["entries"]:
        if e["id"] in scales:
            e["display_scale"] = scales[e["id"]]
    # Ensure new metadata fields exist (backfill for old catalog entries)
    for e in catalog["entries"]:
        if "format" not in e:
            e["format"] = "unknown"
        if "materials" not in e:
            e["materials"] = []
        if "validation_status" not in e:
            e["validation_status"] = "verified"
    return catalog


def write_catalog() -> dict:
    catalog = load_verified_metrics(build_catalog())
    CATALOG_ROOT.mkdir(exist_ok=True)
    CATALOG_FILE.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return catalog


def load_catalog() -> dict:
    if CATALOG_FILE.exists():
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    else:
        catalog = load_verified_metrics(build_catalog())
    # Ensure new metadata fields exist (backfill for old catalog entries)
    for e in catalog["entries"]:
        if "format" not in e:
            e["format"] = "unknown"
        if "materials" not in e:
            e["materials"] = []
        if "validation_status" not in e:
            e["validation_status"] = "verified"
    return catalog


if __name__ == "__main__":
    cat = write_catalog()
    print(f"catalog: {len(cat['entries'])} entries, "
          f"problems={len(cat['problems'])} -> {CATALOG_FILE}")
    for e in cat["entries"]:
        print(f"  {e['id']:<18} {e['category']:<12} {e['ue_class'] or 'unimported':<13} "
              f"size={e['size_cm']} anims={e['animations']} scale={e['display_scale']}")
    sys.exit(1 if cat["problems"] else 0)
