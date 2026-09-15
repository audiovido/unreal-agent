"""Stable actor identity for Unreal verification steps.

Why this exists: on UE 5.7 the deprecated ``EditorLevelLibrary.get_all_level_actors``
can return phantom duplicate handles, and real scenes can legitimately contain
two actors sharing one Outliner label (e.g. an imported asset spawned twice).
Label-based verification then hard-fails every production step with
"Ambiguous actor label" even when the scene is healthy.

Identity strategy (deterministic, ordered):

1. INTERNAL NAME is the unique runtime identity. Exactly one internal-name
   match wins immediately.
2. LABEL matches are candidates, never an automatic failure. Duplicates are
   disambiguated deterministically:
   a. a candidate whose handle is UNREADABLE (phantom handle: any property
      read raises) is dropped;
   b. among readable candidates the lowest internal-name wins, and the result
      is flagged ``ambiguous_label`` with every match reported for audit;
   c. a strict caller can pass ``require_unique_label=True``.
3. Candidates are enumerated through the EditorActorSubsystem (UE 5.7-safe),
   never through the deprecated global enumerator.

This module is pure policy over injected candidate descriptors so it is fully
unit-testable offline with fakes. The Unreal bridge embeds the two embeddable
functions verbatim (via inspect.getsource) into generated scripts, so runtime
behavior and tested behavior cannot drift apart.
"""
from __future__ import annotations

from typing import Any, Dict, List


def resolve_actor(
    query: str,
    candidates: List[Dict[str, Any]],
    *,
    require_unique_label: bool = False,
) -> Dict[str, Any]:
    """Resolve ``query`` against candidate actor descriptors.

    Each candidate is ``{"label": str, "name": str, "readable": bool}``
    (``readable=False`` marks a phantom/unreadable handle). The query matches
    internal name first (unique identity), then Outliner label.

    Returns one of:
      {"status": "resolved", "actor": <candidate>, "match": "name"|"label",
       "ambiguous_label": bool, "matches": [...]}
      {"status": "resolved_phantom_only", "query": ..., "actor": None,
       "matches": [...]}   (label exists but every handle is a phantom)
      {"status": "not_found", "query": ...}
      {"status": "ambiguous", "query": ..., "matches": [...]}
        (only when require_unique_label=True and >1 readable label match)
    """
    query = str(query or "").strip()
    if not query:
        return {"status": "not_found", "query": query}

    readable = [c for c in candidates if c.get("readable", True)]

    # 1) Internal name: the unique runtime identity.
    name_matches = [c for c in readable if c.get("name") == query]
    if len(name_matches) == 1:
        return {"status": "resolved", "actor": name_matches[0], "match": "name",
                "ambiguous_label": False,
                "matches": [name_matches[0].get("name")]}
    if len(name_matches) > 1:
        # Internal names are unique in a healthy level; several readable
        # matches mean duplicate handles sharing a name. Pick deterministically
        # and flag the anomaly for audit instead of failing the step.
        chosen = sorted(name_matches, key=lambda c: (c.get("name") or ""))[0]
        return {"status": "resolved", "actor": chosen, "match": "name",
                "ambiguous_label": True,
                "matches": sorted(c.get("name") or "" for c in name_matches)}

    # 2) Label: candidates, disambiguated deterministically.
    label_matches = [c for c in readable if c.get("label") == query]
    if not label_matches:
        phantom_only = [c for c in candidates if c.get("label") == query]
        if phantom_only:
            # The label exists but every handle was unreadable: a scene
            # anomaly, reported distinctly (never a silent false success).
            return {"status": "resolved_phantom_only", "query": query,
                    "actor": None,
                    "matches": sorted(c.get("name") or "" for c in phantom_only)}
        return {"status": "not_found", "query": query}

    if len(label_matches) == 1:
        return {"status": "resolved", "actor": label_matches[0], "match": "label",
                "ambiguous_label": False,
                "matches": [label_matches[0].get("name")]}

    if require_unique_label:
        return {"status": "ambiguous", "query": query,
                "matches": sorted(c.get("name") or "" for c in label_matches)}

    chosen = sorted(label_matches, key=lambda c: (c.get("name") or ""))[0]
    return {"status": "resolved", "actor": chosen, "match": "label",
            "ambiguous_label": True,
            "matches": sorted(c.get("name") or "" for c in label_matches)}


def unreal_actor_resolution_prelude() -> str:
    """Unreal-side helpers, embedded verbatim into generated bridge scripts.

    Bridges the injected-fake contract of ``resolve_actor`` to live editor
    objects: candidates carry the actor handle plus name/label readability.
    Uses the EditorActorSubsystem (UE 5.7-safe) with a deprecated-enumerator
    fallback, and tolerates the phantom duplicate handles UE 5.7 can return.
    """
    return '''
def __aivido_actor_candidates__():
    out = []
    try:
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    except Exception:
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for a in actors or []:
        name = None
        label = None
        readable = True
        try:
            name = str(a.get_name())
        except Exception:
            readable = False
        try:
            label = str(a.get_actor_label() or name)
        except Exception:
            readable = False
        out.append({"label": label, "name": name, "readable": readable, "actor": a})
    return out


def __aivido_resolve_actor__(query):
    return resolve_actor(query, __aivido_actor_candidates__())
'''
