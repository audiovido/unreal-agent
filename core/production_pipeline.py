"""Production preflight for visual Unreal Agent work.

This module is deliberately engine-agnostic: it creates the production brief
and reuse decision before the existing planner runs, while adapters remain in
``app.api``/the Unreal bridge.  It is deterministic when no optional provider
is available, cheap for trivial tasks, and safe to persist as execution audit
metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from core.visual_director import parse_intent

ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "memory" / "production_discovery.json"
CACHE_TTL_SECONDS = int(os.getenv("UNREAL_AGENT_DISCOVERY_TTL", "300"))

VISUAL_TERMS = (
    "ui", "ux", "widget", "hud", "menu", "interface", "website", "dashboard",
    "app", "application", "scene", "cinematic", "environment", "room", "interior",
    "landing page", "3d", "camera", "lighting", "material", "visual", "beautiful",
    "composition", "motion", "animation", "reference", "screenshot", "image",
)

_MODE_TERMS = {
    "custom": ("from scratch", "unique", "hero asset", "custom production", "bespoke"),
    "fast": ("quick", "fast", "prototype", "reuse", "template", "existing"),
}

_REUSE_KINDS = ("asset", "template", "component", "widget", "material", "blueprint", "prefab", "animation")


@dataclass
class VisualDesignBrief:
    """Internal collaboration contract for the visual specialist roles."""

    request: str
    task_type: str = "general"
    audience: str = "end users"
    mood: str = "cinematic"
    visual_hierarchy: list[str] = field(default_factory=lambda: ["primary subject", "supporting context"])
    composition: str = "balanced, readable focal point with intentional negative space"
    spacing: str = "consistent spacing scale and clear grouping"
    typography: str = "legible hierarchy with restrained type scale"
    palette: str = "controlled neutral base with one accent"
    materials: str = "coherent material language; reuse project materials first"
    lighting: str = "motivated key/fill/rim with subject separation"
    camera: str = "intentional lens/framing; preserve headroom and focal coverage"
    motion: str = "purposeful, restrained motion with readable states"
    storytelling: str = "environment supports the user goal without visual noise"
    ux_flow: str = "clear primary action, feedback, and recovery path"
    polish: list[str] = field(default_factory=lambda: [
        "alignment", "contrast", "readability", "edge quality", "state feedback",
    ])
    reference_analysis: dict[str, Any] = field(default_factory=dict)
    collaborators: tuple[str, ...] = (
        "Creative Director", "Senior Art Director", "Senior UI/UX Designer",
        "Cinematic Director", "Environment Artist", "Lighting Artist",
        "Motion Designer", "Technical Artist", "Unreal Developer",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "task_type": self.task_type,
            "audience": self.audience,
            "mood": self.mood,
            "visual_hierarchy": list(self.visual_hierarchy),
            "composition": self.composition,
            "spacing": self.spacing,
            "typography": self.typography,
            "palette": self.palette,
            "materials": self.materials,
            "lighting": self.lighting,
            "camera": self.camera,
            "motion": self.motion,
            "storytelling": self.storytelling,
            "ux_flow": self.ux_flow,
            "polish": list(self.polish),
            "reference_analysis": dict(self.reference_analysis),
            "collaborators": list(self.collaborators),
        }


@dataclass
class ReuseDecision:
    strategy: str
    mode: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    discovery_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "mode": self.mode,
            "candidates": list(self.candidates),
            "reason": self.reason,
            "discovery_ms": round(self.discovery_ms, 2),
        }


def is_visual_task(request: str) -> bool:
    text = str(request or "").lower()
    return any(term in text for term in VISUAL_TERMS)


def classify_task(request: str) -> str:
    text = str(request or "").lower()
    if any(x in text for x in ("website", "landing page", "dashboard", "application", "app")):
        return "application_ui"
    if any(x in text for x in ("room", "interior", "environment", "level", "world")):
        return "environment"
    if any(x in text for x in ("cinematic", "sequence", "shot", "camera")):
        return "cinematic"
    if any(x in text for x in ("room", "interior", "environment", "level", "world")) and not any(x in text for x in ("website", "landing page", "dashboard", "application", "app")):
        return "environment"
    if any(x in text for x in ("widget", "menu", "hud", "interface", "ui", "ux")):
        return "unreal_ui"
    return "general"


def _mood_from_target(target: Mapping[str, Any]) -> str:
    return str(target.get("mood") or (target.get("art_direction") or {}).get("lighting_mood") or "cinematic")


def _find_reference(request: str) -> str | None:
    # Paths are treated as evidence only; no filesystem traversal beyond the
    # explicitly named file.
    match = re.search(r"(?P<path>(?:[A-Za-z]:[\\/]|/)[^\s\"']+\.(?:png|jpe?g|webp))", str(request), re.I)
    if match:
        path = match.group("path").rstrip(".,)")
        return path if Path(path).is_file() else None
    return None


def build_visual_brief(request: str, *, vision: Callable[[str], Any] | None = None) -> VisualDesignBrief:
    target = parse_intent(request, ref_image=_find_reference(request), vision=vision)
    task_type = classify_task(request)
    subject = target.get("subject") or {}
    ui = target.get("ui") or {}
    art = target.get("art_direction") or {}
    hierarchy = [str(subject.get("type") or "primary subject")]
    if ui.get("present"):
        hierarchy.append(f"{ui.get('placement', 'right')} interface")
    hierarchy.append("environmental context")
    reference = target.get("reference") or {}
    return VisualDesignBrief(
        request=str(request),
        task_type=task_type,
        mood=_mood_from_target(target),
        visual_hierarchy=hierarchy,
        composition="balanced focal hierarchy; subject and controls remain distinct",
        palette=str(art.get("palette") or "controlled neutral base with one accent"),
        materials="preserve useful project materials; upgrade only visible weak links",
        lighting=str(art.get("lighting_mood") or "motivated key/fill/rim with subject separation"),
        camera="intentional framing based on requested shot and target coverage",
        motion="state-driven motion; no decorative animation that competes with the focal point",
        ux_flow="primary action first, immediate feedback, obvious recovery",
        reference_analysis=reference,
    )


def _read_cache() -> dict[str, Any]:
    try:
        if time.time() - CACHE_FILE.stat().st_mtime <= CACHE_TTL_SECONDS:
            value = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except Exception:
        pass
    return {}


def _write_cache(value: dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except Exception:
        # Discovery must never block a build because a cache directory is
        # unavailable or read-only.
        pass


def _request_key(request: str, context: Mapping[str, Any] | None) -> str:
    raw = json.dumps({"request": str(request), "context": dict(context or {})}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def discover_reuse_candidates(
    request: str,
    *,
    context: Mapping[str, Any] | None = None,
    providers: Mapping[str, Callable[[str, Mapping[str, Any]], Iterable[Mapping[str, Any]]]] | None = None,
) -> list[dict[str, Any]]:
    """Query independent local/project providers concurrently and cache results."""
    key = _request_key(request, context)
    cache = _read_cache()
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("candidates"), list):
        return list(cached["candidates"])
    providers = providers or {}
    if not providers:
        # The planner still gets an explicit reuse-first record even when no
        # adapter is registered in this process.
        return []
    started = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(providers)))) as pool:
        futures = {
            pool.submit(provider, request, context or {}): name
            for name, provider in providers.items()
        }
        completed = {}
        for future in as_completed(futures):
            source = futures[future]
            completed[source] = future
        for source in providers:
            future = completed[source]
            try:
                for candidate in future.result() or []:
                    item = dict(candidate)
                    item.setdefault("source", source)
                    item.setdefault("kind", "asset")
                    candidates.append(item)
            except Exception as exc:
                candidates.append({"source": source, "error": f"{type(exc).__name__}: {exc}"})
    candidates.sort(key=lambda item: (-float(item.get("score", 0) or 0), str(item.get("name", ""))))
    cache[key] = {"created_at": time.time(), "duration_ms": (time.perf_counter() - started) * 1000, "candidates": candidates}
    _write_cache(cache)
    return candidates


def select_reuse_strategy(request: str, candidates: Iterable[Mapping[str, Any]] = (), *, force_mode: str | None = None) -> ReuseDecision:
    text = str(request or "").lower()
    items = [dict(x) for x in candidates if not x.get("error")]
    explicit = (force_mode or "").lower().replace("/", "_")
    if explicit in {"fast", "balanced", "custom", "hero"}:
        mode = "custom" if explicit in {"custom", "hero"} else explicit
    elif any(term in text for term in _MODE_TERMS["custom"]):
        mode = "custom"
    elif any(term in text for term in _MODE_TERMS["fast"]):
        mode = "fast"
    else:
        mode = "balanced"
    if items:
        best = items[0]
        kind = str(best.get("kind", "asset")).lower()
        if kind in _REUSE_KINDS and mode != "custom":
            strategy = "reuse" if mode == "fast" else "modify"
            reason = f"selected existing {kind} candidate before generation"
        else:
            strategy = "combine" if len(items) > 1 else "modify"
            reason = "combine compatible candidates, then customize visible differences"
    else:
        strategy = "generate" if mode != "custom" else "build_from_zero"
        reason = "no reusable candidate was discovered; generation is the next permitted fallback"
    return ReuseDecision(strategy=strategy, mode=mode, candidates=items[:12], reason=reason)


def production_preflight(
    request: str,
    *,
    context: Mapping[str, Any] | None = None,
    providers: Mapping[str, Callable[[str, Mapping[str, Any]], Iterable[Mapping[str, Any]]]] | None = None,
    force_mode: str | None = None,
    vision: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Build the durable pre-execution contract used by all execution paths."""
    started = time.perf_counter()
    visual = is_visual_task(request)
    brief = build_visual_brief(request, vision=vision) if visual else VisualDesignBrief(request=str(request), task_type=classify_task(request), mood="n/a")
    candidates = discover_reuse_candidates(request, context=context, providers=providers) if visual else []
    decision = select_reuse_strategy(request, candidates, force_mode=force_mode)
    return {
        "visual_task": visual,
        "brief": brief.to_dict(),
        "asset_template_route": decision.to_dict(),
        "execution_mode": decision.mode,
        "preflight_ms": round((time.perf_counter() - started) * 1000, 2),
        "pipeline": ["intent_reference_analysis", "creative_direction", "reuse_discovery", "strategy_selection", "execution", "visual_review", "technical_validation"] if visual else ["intent", "execution", "technical_validation"],
    }


def visual_scorecard(score: Any, *, vision_review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize existing visual scores to the requested 0-10 art gate."""
    data = score.to_dict() if hasattr(score, "to_dict") else dict(score or {})
    aliases = {
        "composition": "composition", "visual_hierarchy": "composition", "spacing": "readability",
        "typography": "readability", "materials": "environment", "lighting": "lighting",
        "camera": "subject_framing", "motion": "target_match", "usability": "readability",
        "uniqueness": "target_match", "premium_feel": "overall",
    }
    out = {}
    for name, source in aliases.items():
        out[name] = round(float(data.get(source, data.get("overall", 0)) or 0), 2)
    out["overall"] = round(float(data.get("overall", 0) or 0), 2)
    out["target"] = 9.0
    out["accepted"] = out["overall"] >= 9.0 and all(out[k] >= 7.0 for k in aliases if k != "premium_feel")
    if vision_review:
        out["vision_review"] = dict(vision_review)
    return out
