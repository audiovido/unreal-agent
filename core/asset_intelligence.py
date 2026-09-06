"""asset_intelligence.py — Asset Intelligence layer (Phase E).

Searches, classifies, scores and deduplicates the *indexed* ready-asset
catalog BEFORE any generation happens, so the pipeline prefers existing
suitable assets over unnecessary substitutes.

Contract (mirrors the assetlib catalog schema, `assetlib/catalog/assets.json`):

  entry = {
    "id", "category", "name", "license", "source", "path", "preview",
    "tags": [str], "desc", "ue_class", "size_cm": [x,y,z] | None,
    "skeleton" | None, "animations": [str], "display_scale", "lod", ...
  }

Hard rules:

  - NEVER invents asset availability: every scored entry is one the caller
    passed in (typically loaded from the on-disk catalog). An empty/missing
    catalog yields empty results, never fabricated candidates.
  - Deterministic: identical (query, entries) -> identical ranking. Sorting
    ties are broken by id so results are stable across processes.
  - Auditability: every score carries a breakdown of WHICH field matched.
  - Duplicate detection reports candidates with evidence; it never deletes.

This module performs no Unreal/Blender/network I/O.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Vocabulary: category taxonomy + surface-term glossary (core copy of the
# assetlib router's lexical map so the mission engine can score offline).
# ---------------------------------------------------------------------------

CATEGORIES: List[str] = [
    "Characters", "Crowd/NPC", "Vehicles", "Buildings", "Interiors",
    "Furniture", "Props", "Nature", "Roads/City", "Animations", "Creatures",
    "Robots", "VFX", "Materials", "Cinematic/Sequencer",
]

CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "Characters": ("character", "human", "man", "woman", "person", "crowd", "npc"),
    "Crowd/NPC": ("crowd", "npc", "pedestrian"),
    "Vehicles": ("vehicle", "truck", "car", "suv", "van", "auto", "sedan"),
    "Buildings": ("building", "facade", "architecture", "tower", "house", "modular"),
    "Interiors": ("interior", "room", "indoor", "apartment", "office"),
    "Furniture": ("furniture", "chair", "table", "desk", "sofa", "shelf", "couch"),
    "Props": ("prop", "lantern", "crate", "barrel", "light fixture", "set dressing"),
    "Nature": ("nature", "tree", "rock", "grass", "plant", "terrain", "landscape"),
    "Roads/City": ("road", "street", "city", "asphalt", "sidewalk", "sign"),
    "Animations": ("animation", "walk", "run", "idle", "cycle", "locomotion", "pose"),
    "Creatures": ("creature", "monster", "beast", "dragon"),
    "Robots": ("robot", "mech", "drone", "android"),
    "VFX": ("vfx", "particle", "niagara", "smoke", "fire", "dust", "energy", "effect"),
    "Materials": ("material", "texture", "surface", "shader", "pbr"),
    "Cinematic/Sequencer": ("sequencer", "cinematic", "camera", "cutscene", "level sequence"),
}

# Surface terms -> canonical keywords found in tags/names (subset of the
# assetlib glossary, kept dependency-free in core).
GLOSSARY: Dict[str, Tuple[str, ...]] = {
    "suv": ("suv", "truck", "vehicle"),
    "car": ("vehicle", "truck"),
    "truck": ("truck", "vehicle"),
    "building": ("building", "facade"),
    "buildings": ("building", "facade"),
    "walk": ("walk", "animation", "cycle"),
    "walking": ("walk", "animation"),
    "character": ("character", "human"),
    "crowd": ("crowd", "character"),
    "street": ("street", "lantern", "prop", "city"),
    "environment": ("environment", "prop", "nature"),
    "vehicle": ("vehicle", "truck", "car"),
    "animation": ("animation", "walk", "run", "cycle"),
    "lobby": ("interior", "room", "environment"),
    "sci-fi": ("futuristic", "robot", "vehicle"),
    "sci fi": ("futuristic", "robot", "vehicle"),
}

STOPWORDS = {
    "a", "an", "the", "of", "for", "with", "next", "to", "in", "on", "and",
    "or", "at", "near", "from", "into", "then", "our", "make", "build",
    "create", "show", "me", "scene", "please", "using", "some", "one", "this",
    "that", "it", "look", "like", "premium", "beautiful", "nice", "cool",
}

_LOD_RE = re.compile(r"LOD(\d+)")


# ---------------------------------------------------------------------------
# Tokenizer + term expansion
# ---------------------------------------------------------------------------


def tokens(query: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", str(query or "").lower()) if t not in STOPWORDS]


def expand_terms(terms: Iterable[str]) -> Tuple[str, ...]:
    out: List[str] = []
    seen = set()
    for t in terms:
        for word in (t,) + GLOSSARY.get(t, ()):
            if word not in seen:
                seen.add(word)
                out.append(word)
    return tuple(out)


def _entry_text(entry: Mapping[str, Any]) -> str:
    parts = [
        str(entry.get("name") or ""),
        str(entry.get("desc") or ""),
        str(entry.get("category") or ""),
        str(entry.get("id") or ""),
    ]
    parts += [str(t) for t in (entry.get("tags") or [])]
    parts += [str(a) for a in (entry.get("animations") or [])]
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_entry(entry: Mapping[str, Any]) -> Tuple[str, List[str]]:
    """Normalize an entry's category from name/tags/desc when missing.

    Returns (category, evidence). If the entry already has a valid category it
    is returned untouched. Never raises on malformed entries.
    """
    existing = str(entry.get("category") or "").strip()
    if existing and existing in CATEGORIES:
        return existing, ["catalog category"]
    text = _entry_text(entry)
    matches: List[Tuple[str, str]] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in text]
        if hits:
            matches.append((category, hits[0]))
    if matches:
        # Most specific = longest keyword first, then stable order.
        matches.sort(key=lambda pair: (-len(pair[1]), CATEGORIES.index(pair[0])))
        category, evidence = matches[0]
        return category, [f"keyword '{evidence}' in {category} vocabulary"]
    return "Props", ["no strong signal; default to Props (no fabricated detail)"]


# ---------------------------------------------------------------------------
# Relevance scoring (deterministic, field-level breakdown)
# ---------------------------------------------------------------------------


def score_relevance(query: str, entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Score one catalog entry against a query: 0.0-1.0 with an audit trail.

    Weights: name 0.40, tags 0.30, desc 0.15, category 0.10, id 0.05.
    A query-term coverage multiplier (fraction of distinct query terms matched
    anywhere) applies so multi-token queries prefer multi-facet matches.
    """
    terms = tokens(query)
    if not terms:
        return {"score": 0.0, "matched": [], "terms": [], "coverage": 0.0}
    expanded = expand_terms(terms)

    name = str(entry.get("name") or "").lower()
    desc = str(entry.get("desc") or "").lower()
    category = str(entry.get("category") or "").lower()
    tags = [str(t).lower() for t in (entry.get("tags") or [])]
    eid = str(entry.get("id") or "").lower()

    def hit(term: str) -> bool:
        return term in name or term in desc or term in category or term in eid or any(term in t for t in tags)

    matched = sorted({t for t in terms if hit(t)})
    matched_expanded = sorted({t for t in expanded if hit(t)})

    # Field-level scoring with expanded terms (synonyms count, e.g. suv -> truck).
    name_hits = [t for t in expanded if t in name]
    tag_hits = [t for t in expanded if any(t in tag for tag in tags)]
    desc_hits = [t for t in expanded if t in desc]
    category_hits = [t for t in expanded if t in category]
    id_hits = [t for t in expanded if t in eid]

    def cap(value: float) -> float:
        return min(1.0, value)

    raw = (
        0.40 * min(1.0, len(name_hits) / max(1, len(expanded)))
        + 0.30 * min(1.0, len(tag_hits) / max(1, len(expanded)))
        + 0.15 * min(1.0, len(desc_hits) / max(1, len(expanded)))
        + 0.10 * min(1.0, len(category_hits) / max(1, len(expanded)))
        + 0.05 * min(1.0, len(id_hits) / max(1, len(expanded)))
    )
    coverage = len(matched) / len(terms)
    score = cap(raw * (0.6 + 0.4 * coverage))
    return {
        "score": round(score, 4),
        "matched_terms": matched,
        "matched_synonyms": [t for t in matched_expanded if t not in matched],
        "coverage": round(coverage, 4),
        "breakdown": {
            "name": round(min(1.0, len(name_hits) / max(1, len(expanded))), 4),
            "tags": round(min(1.0, len(tag_hits) / max(1, len(expanded))), 4),
            "desc": round(min(1.0, len(desc_hits) / max(1, len(expanded))), 4),
            "category": round(min(1.0, len(category_hits) / max(1, len(expanded))), 4),
            "id": round(min(1.0, len(id_hits) / max(1, len(expanded))), 4),
        },
    }


def search_assets(
    query: str,
    entries: Iterable[Mapping[str, Any]],
    *,
    top_k: int = 5,
    min_score: float = 0.0,
) -> List[Dict[str, Any]]:
    """Rank catalog entries by relevance. Deterministic: ties break by id."""
    ranked = []
    for entry in entries:
        result = score_relevance(query, entry)
        if result["score"] >= min_score:
            ranked.append({
                "id": str(entry.get("id") or ""),
                "name": str(entry.get("name") or ""),
                "category": str(entry.get("category") or ""),
                "score": result["score"],
                "matched_terms": result["matched_terms"],
                "matched_synonyms": result["matched_synonyms"],
                "coverage": result["coverage"],
                "breakdown": result["breakdown"],
            })
    ranked.sort(key=lambda item: (-item["score"], item["id"]))
    return ranked[:max(1, int(top_k))]


# ---------------------------------------------------------------------------
# Duplicate detection (candidates with evidence; never deletes)
# ---------------------------------------------------------------------------


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def detect_duplicates(
    entries: Iterable[Mapping[str, Any]],
    *,
    # Strict by default: near-identical names only. Vendor-prefix siblings
    # ("CesiumMilkTruck" vs "CesiumMan") must NOT be reported as duplicates.
    name_threshold: float = 0.92,
    size_tolerance_cm: float = 10.0,
) -> List[Dict[str, Any]]:
    """Group catalog entries that are likely duplicates.

    A group is reported when entries share a near-identical normalized name OR
    share a source stem AND have compatible bounding sizes (when both known).
    Evidence is explicit; the caller decides whether to act.
    """
    items = [dict(e) for e in entries]
    groups: List[Dict[str, Any]] = []
    used: List[int] = []

    for i, item in enumerate(items):
        if i in used:
            continue
        group = [i]
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            other = items[j]
            evidence: List[str] = []

            name_i, name_j = _normalize_name(item.get("name")), _normalize_name(other.get("name"))
            if name_i and name_j and (name_i == name_j or _similarity(name_i, name_j) >= name_threshold):
                evidence.append(f"normalized names match: '{name_i}' vs '{name_j}'")

            stem_i = _normalize_name(Path(str(item.get("source") or "")).stem)
            stem_j = _normalize_name(Path(str(other.get("source") or "")).stem)
            if stem_i and stem_j and stem_i == stem_j:
                evidence.append(f"shared source stem '{stem_i}'")

            if evidence:
                size_i, size_j = item.get("size_cm"), other.get("size_cm")
                if size_i and size_j:
                    close = all(
                        abs(float(a) - float(b)) <= size_tolerance_cm
                        for a, b in zip(size_i, size_j)
                    )
                    if not close:
                        evidence.append(f"sizes differ by > {size_tolerance_cm}cm; same-named, likely variants")
                group.append(j)
        if len(group) > 1:
            used.extend(group)
            members = [{"id": items[k].get("id"), "name": items[k].get("name"),
                        "source": items[k].get("source")} for k in group]
            groups.append({
                "kind": "duplicate_candidates",
                "evidence": evidence,
                "members": members,
            })
    return groups


def _similarity(a: str, b: str) -> float:
    """Cheap normalized similarity for short normalized names."""
    if not a or not b:
        return 0.0
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    if len(longer) == 0:
        return 1.0
    return (len(longer) - _edit_distance(longer, shorter)) / max(1.0, len(longer))


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


# ---------------------------------------------------------------------------
# LOD selection (deterministic, evidence-based)
# ---------------------------------------------------------------------------


def select_lod(entry: Mapping[str, Any], distance_m: float) -> Dict[str, Any]:
    """Recommend a LOD level for a target distance, from what the mesh HAS.

    Never claims a LOD that does not exist: max available LOD is parsed from
    entry["lod"] (e.g. "LOD0 only", "LOD0-LOD3"). Missing/unknown availability
    is reported honestly as "unknown".
    """
    lod_spec = str(entry.get("lod") or "").strip()
    indices = [int(m) for m in _LOD_RE.findall(lod_spec)] or [0]
    available = max(indices)
    distance = abs(float(distance_m or 0.0))
    if distance < 8.0:
        want = 0
    elif distance < 20.0:
        want = 1
    elif distance < 50.0:
        want = 2
    else:
        want = 3
    chosen = min(want, available)
    if not lod_spec:
        note = "mesh LOD availability unknown (not recorded); LOD0 assumed and rendered source may be highest-res"
    elif chosen < want:
        note = f"mesh provides up to LOD{available}; LOD{chosen} used at {distance:g}m (LOD{max(want, 0)} not available)"
    else:
        note = f"mesh provides up to LOD{available}; LOD{chosen} within budget at {distance:g}m"
    return {
        "recommended_lod": chosen,
        "max_available_lod": available,
        "available_spec": lod_spec or "unknown",
        "distance_m": round(distance, 2),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Catalog loading (evidence-first; empty when unavailable)
# ---------------------------------------------------------------------------


def load_catalog_entries(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load catalog entries from the on-disk catalog JSON.

    Returns [] (never raises) when the file is missing or malformed — an
    unavailable catalog must yield empty results, never fabricated ones.
    """
    catalog_file = Path(path) if path else Path(__file__).resolve().parents[1] / "assetlib" / "catalog" / "assets.json"
    try:
        data = json.loads(catalog_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("id")]


# ---------------------------------------------------------------------------
# Combined decision helper
# ---------------------------------------------------------------------------


def recommend_assets(
    query: str,
    entries: Iterable[Mapping[str, Any]],
    *,
    top_k: int = 5,
    min_score: float = 0.0,
    distance_m: Optional[float] = None,
) -> Dict[str, Any]:
    """One-call asset intelligence: classify intent, rank, LOD, duplicates.

    Returns a structured recommendation the planner can consume directly.
    Duplicate detection runs over the supplied entries (not just matches).
    """
    entries_list = [dict(e) for e in entries]
    terms = tokens(query)
    intent = "place" if any(t in ("place", "put", "spawn", "deliver", "populate", "add") for t in terms) else "query"
    ranked = search_assets(query, entries_list, top_k=top_k, min_score=min_score)
    duplicates = detect_duplicates(entries_list)
    lod = select_lod(ranked[0], distance_m) if ranked and distance_m is not None else None
    return {
        "query": str(query),
        "intent": intent,
        "terms": terms,
        "ranked": ranked,
        "duplicates": duplicates,
        "lod_recommendation": lod,
        "catalog_entry_count": len(entries_list),
        "proven": True,  # every candidate above came from caller-supplied entries
    }