"""cinematic_assets.py — Aivido V2 asset decision layer.

Decides, for an asset a cinematic requires, which of three paths to take:

1. REUSE          — a catalogued asset already satisfies the need
                    (validation_status valid/verified + ranking threshold)
                    -> fast path, no Blender.
2. FIX_VIA_BLENDER — the closest asset exists but needs bounded repair/
                    cleanup (scale normalization, origin, transforms,
                    format conversion, tint) before Unreal import.
3. CREATE_VIA_BLENDER — the required asset genuinely does not exist and is a
                    bounded procedural geometry the Blender chain can build.
                    Anything outside that set is BLOCKED with a real source
                    requirement — never fabricated.

The decision is deterministic and hermetic (catalog entries + scores are
injected). Live missions feed the catalog/router through the existing
assetlib tools; this module only turns their output into an honest decision.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Bounded procedural shapes the existing Blender chain can genuinely build
# (matches blender_tools.blender_create_asset presets).
BOUNDED_CREATE_SHAPES = {
    "cube", "box", "plane", "cylinder", "sphere", "cone", "torus", "monkey",
    "table", "chair", "crate", "plinth", "pedestal", "column", "pillar",
}

REUSE_VALIDATION_MIN = {"valid", "verified"}
DEFAULT_REUSE_SCORE = 0.10


def decide_asset_strategy(
    need: str,
    catalog_entries: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    scores: Optional[Dict[str, float]] = None,
    reuse_threshold: float = DEFAULT_REUSE_SCORE,
    min_validation: Sequence[str] = ("valid", "verified"),
) -> Dict[str, Any]:
    """Ranked decision for ``need`` across the reuse/fix/create spectrum.

    ``catalog_entries``: catalog rows (must carry ``id`` and
    ``validation_status``). ``scores``: {asset_id: relevance_score} from the
    assetlib router when available (already-ranked top candidate otherwise).
    """
    entries = [dict(e) for e in (catalog_entries or [])]
    if not entries:
        return _decide_no_catalog(need)

    scored: List[Dict[str, Any]] = []
    for e in entries:
        sid = str(e.get("id") or "")
        score = float((scores or {}).get(sid) or 0.0)
        scored.append({**e, "_score": score})
    scored.sort(key=lambda e: e["_score"], reverse=True)

    top = scored[0]
    top_validation = str(top.get("validation_status") or "")
    top_score = float(top.get("_score"))
    reuse_ok = (top_score >= reuse_threshold
                and top_validation in min_validation)
    if reuse_ok:
        return {
            "decision": "reuse",
            "blender_used": False,
            "asset_id": top.get("id"),
            "asset_path": top.get("path"),
            "ue_path": top.get("ue_path"),
            "score": round(top_score, 3),
            "validation_status": top_validation,
            "reason": (f"catalogued asset {top.get('id')} is valid "
                       f"(validation={top_validation}, score={top_score:.3f}) "
                       "and satisfies the need; Blender not required"),
            "fast_path": True,
        }

    # closest candidate exists but is not yet Unreal-ready
    source = top.get("path") or top.get("source")
    if source:
        return {
            "decision": "fix_via_blender",
            "blender_used": True,
            "asset_id": top.get("id"),
            "source": source,
            "blender_operation": "prepare_asset",
            "blender_params": {
                "source": source,
                "name": str(top.get("name") or top.get("id")),
                "export_format": "fbx",
                "cleanup": True,
                "uv_unwrap": True,
            },
            "reason": (f"closest asset {top.get('id')} exists "
                       f"(validation={top_validation}, score={top_score:.3f}) "
                       "but is below the reuse bar; bounded Blender prepare "
                       "(transforms/origin/scale/UV) before Unreal import"),
            "fast_path": False,
        }

    # no usable candidate: bounded creation only when the need is procedural
    low = str(need).lower()
    shape = next((w for w in BOUNDED_CREATE_SHAPES if w in low), None)
    if shape is not None:
        return {
            "decision": "create_via_blender",
            "blender_used": True,
            "blender_operation": "create_asset",
            "blender_params": {"name": shape, "shape": shape,
                               "export_format": "fbx"},
            "reason": (f"no catalogued asset matches '{need}'; bounded "
                       f"procedural '{shape}' creation routed to Blender"),
            "fast_path": False,
        }

    return {
        "decision": "blocked",
        "blender_used": False,
        "reason": (f"no usable asset for '{need}' and it is outside the "
                   "bounded procedural set; a real external source asset is "
                   "required (no fake creation)"),
        "blocked": "ASSET_SOURCE_REQUIRED",
        "fast_path": False,
    }


def _decide_no_catalog(need: str) -> Dict[str, Any]:
    low = str(need).lower()
    shape = next((w for w in BOUNDED_CREATE_SHAPES if w in low), None)
    if shape is not None:
        return {
            "decision": "create_via_blender",
            "blender_used": True,
            "blender_operation": "create_asset",
            "blender_params": {"name": shape, "shape": shape,
                               "export_format": "fbx"},
            "reason": (f"no catalogued asset matches '{need}'; bounded "
                       f"procedural '{shape}' creation routed to Blender"),
            "fast_path": False,
        }
    return {
        "decision": "blocked",
        "blender_used": False,
        "reason": ("no catalogued assets and the need is outside the bounded "
                   "procedural set; external source required"),
        "blocked": "ASSET_SOURCE_REQUIRED",
        "fast_path": False,
    }


def catalog_reuse_shortlist(
    catalog_entries: Sequence[Dict[str, Any]],
    scores: Optional[Dict[str, float]] = None,
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    """Deterministic shortlist used by the mission plan (asset reuse
    candidates), mirroring the planner's catalog step."""
    scored = []
    for e in catalog_entries:
        sid = str(e.get("id") or "")
        scored.append({**e, "_score": float((scores or {}).get(sid) or 0.0)})
    scored.sort(key=lambda e: e["_score"], reverse=True)
    return [{k: v for k, v in e.items() if k != "_score"}
            for e in scored[:top_n]]
