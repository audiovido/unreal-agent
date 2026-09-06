"""creative_director.py — the Creative Director (Phase D).

The Creative Director sits ABOVE the Visual Director. Before any execution
starts it turns a vague natural-language request ("make this look like a
premium sci-fi AAA lobby") into a concrete, structured production brief:

  - intended mood and its measurable traits
  - visual language / art direction (with the prompt evidence that drove it)
  - reference direction (only evidence-backed; never invented availability)
  - composition strategy
  - lighting philosophy
  - camera language
  - palette direction
  - ordered environmental-storytelling priorities
  - explicit consistency rules the rest of the pipeline must honor

It is deliberately engine-agnostic and deterministic: it performs zero
Unreal/Blender/network I/O, so every choice is auditable, cacheable and
regression-testable offline. Optional vision/reference providers may enrich
reference direction, but the director NEVER fabricates asset existence,
file availability or reference content — anything not proven is recorded as
absent (``None`` / empty), exactly like the asset intelligence contract.

Consistency: ``consistency_report`` compares a new direction against prior
briefs for the same mission and returns structured conflicts/warnings so
the supervisor can block random art-direction drift without a human in the
loop.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.universal_intent import detect_domains  # dependency-free vocabulary

# ---------------------------------------------------------------------------
# Vocabulary: mood profiles -> measurable traits (mirrors the Visual Director
# vocabulary so the brief can be consumed without translation).
# ---------------------------------------------------------------------------

MOOD_PROFILES: Dict[str, Dict[str, Any]] = {
    "cinematic": {
        "brightness": "balanced", "contrast": "medium", "palette_hint": "neutral",
        "lighting_style": "motivated", "camera": "intentional_framing",
        "storytelling": "scene reads as a deliberate frame",
    },
    "premium": {
        "brightness": "balanced", "contrast": "medium", "palette_hint": "neutral",
        "lighting_style": "controlled", "camera": "precise",
        "storytelling": "high production value, no visible shortcuts",
    },
    "dark": {
        "brightness": "dark", "contrast": "high", "palette_hint": "cool",
        "lighting_style": "moody", "camera": "dramatic_framing",
        "storytelling": "shadows hide depth; light is narrative",
    },
    "cozy": {
        "brightness": "medium", "contrast": "soft", "palette_hint": "warm",
        "lighting_style": "soft_warm", "camera": "intimate_framing",
        "storytelling": "warm inhabited spaces with human scale",
    },
    "energetic": {
        "brightness": "bright", "contrast": "high", "palette_hint": "saturated",
        "lighting_style": "dynamic", "camera": "dynamic_movement",
        "storytelling": "visual energy and motion dominate",
    },
    "calm": {
        "brightness": "medium", "contrast": "low", "palette_hint": "desaturated",
        "lighting_style": "soft", "camera": "slow_steady",
        "storytelling": "negative space and restraint",
    },
    "futuristic": {
        "brightness": "balanced", "contrast": "medium", "palette_hint": "cool_cyan",
        "lighting_style": "neon_accent", "camera": "sweeping",
        "storytelling": "technology is a visible character",
    },
    "vintage": {
        "brightness": "warm", "contrast": "soft", "palette_hint": "aged",
        "lighting_style": "practical", "camera": "static",
        "storytelling": "patina and history in every surface",
    },
    "playful": {
        "brightness": "bright", "contrast": "medium", "palette_hint": "colorful",
        "lighting_style": "flat_friendly", "camera": "expressive",
        "storytelling": "approachable, readable, fun",
    },
    "minimal": {
        "brightness": "bright", "contrast": "medium", "palette_hint": "monochrome",
        "lighting_style": "even", "camera": "clean_centered",
        "storytelling": "every element must earn its place",
    },
}

# ---------------------------------------------------------------------------
# Vocabulary: visual languages (art direction) with their trigger evidence.
# Ordered by specificity; the first matching language wins.
# ---------------------------------------------------------------------------

VISUAL_LANGUAGES: List[Tuple[str, Tuple[str, ...], Dict[str, str]]] = [
    ("neo_noir", (
        "neo-noir", "neon noir", "film noir", "rainy night", "noir",
    ), {"palette": "cool shadows + one accent", "lighting": "high contrast practical", "camera": "canted angles, deep shadows"}),
    ("cyberpunk", (
        "cyberpunk", "blade runner", "tech-noir", "dystopian neon",
    ), {"palette": "magenta/cyan on near-black", "lighting": "neon signs as key light", "camera": "sweeping city scale"}),
    ("sci_fi", (
        "sci-fi", "sci fi", "science fiction", "space station", "starship",
        "futuristic", "future", "hologram", "holographic", "spacecraft",
    ), {"palette": "cool neutral + cyan/teal accent", "lighting": "clean key with practical strips", "camera": "symmetric or dolly"}),
    ("brutalist", (
        "brutalist", "concrete", "raw concrete", "industrial",
    ), {"palette": "gray concrete + rust", "lighting": "hard directional sun", "camera": "monumental wide"}),
    ("art_deco", (
        "art deco", "art-deco", "gatsby", "1920s", "gold and black",
    ), {"palette": "black + gold + cream", "lighting": "glowing fixtures", "camera": "symmetrical grand"}),
    ("corporate_clean", (
        "corporate", "clean corporate", "enterprise", "executive",
    ), {"palette": "neutral gray + one blue accent", "lighting": "even ceiling light", "camera": "straight-on, balanced"}),
    ("warm_editorial", (
        "editorial", "magazine", "lifestyle", "warm minimal",
    ), {"palette": "warm neutrals + terracotta", "lighting": "soft window light", "camera": "eye-level"}),
    ("fantasy", (
        "fantasy", "medieval", "elven", "magical", "enchanted", "castle",
    ), {"palette": "rich earth + jewel accents", "lighting": "candle/fire + god rays", "camera": "heroic low angle"}),
    ("photoreal_studio", (
        "photoreal", "photorealistic", "studio", "product shot",
        "hyperrealistic", "product showcase",
    ), {"palette": "true-to-life neutral", "lighting": "softbox studio", "camera": "product hero"}),
    ("minimal_abstract", (
        "minimal", "abstract", "clean room", "white space",
    ), {"palette": "monochrome + single accent", "lighting": "even ambient", "camera": "centered, symmetrical"}),
    ("retro_urban", (
        "retro", "vintage urban", "80s", "synthwave", "arcade",
    ), {"palette": "sunset gradient + neon", "lighting": "practical storefront glow", "camera": "street-level"}),
]

# Generic quality/art-direction trigger words that strengthen the chosen
# language without selecting a specific one.
_QUALITY_ART_TERMS = (
    "premium", "high-end", "high end", "aaa", "triple-a", "triple a",
    "production", "polished", "cinematic", "stunning", "gorgeous",
    "beautiful", "clean", "professional",
)

LIGHTING_PHILOSOPHIES: Dict[str, str] = {
    "motivated": "key/fill/rim motivated by visible practical sources; subject separation first",
    "studio": "softbox key, controlled fill, optional rim; maximum control over subject readability",
    "moody": "single strong source, deep falloff, shadows as narrative; exposure kept in check",
    "dynamic": "high-contrast directionality with color accents; motion readable through light",
    "soft_warm": "large soft sources, warm temperature, gentle falloff; comfortable human scale",
    "neon_accent": "practical neon/strip sources carry color; neutral base exposure underneath",
    "even": "flat even illumination; content readability over drama",
}

CAMERA_LANGUAGES: Dict[str, str] = {
    "static_precise": "tripod, intentional framing, no gratuitous motion; cuts only on beats",
    "dolly": "slow dolly in/out to change emphasis; maintains spatial coherence",
    "sweeping": "wide establishing moves that reveal scale before intimacy",
    "handheld": "subtle handheld energy for immediacy; amplitude bounded for readability",
    "orbit": "controlled orbit around the hero to showcase material and silhouette",
    "intimate": "close, eye-level framing; shallow depth for human connection",
}

COMPOSITION_STRATEGIES: Dict[str, str] = {
    "rule_of_thirds": "hero on a third; negative space balanced opposite; horizon on a third",
    "centered_hero": "symmetric centered hero with mirrored context; strongest for product/showcase",
    "layered_depth": "foreground/midground/background layers; depth cues without clutter",
    "diagonal": "strong diagonal read through subject and light; dynamic tension",
    "framing": "architectural frames (doors, arches, panels) contain the subject",
}

STORYTELLING_PRIORITY_ORDER: Dict[str, Tuple[str, ...]] = {
    "unreal_ui": ("primary action first", "state feedback", "readable hierarchy", "recovery path"),
    "application_ui": ("primary action first", "state feedback", "readable hierarchy", "recovery path"),
    "environment": ("space reads believable", "focal anchor", "scale and materials coherent", "lived-in detail"),
    "cinematic": ("story intent per shot", "camera motivates the mood", "continuity across cuts", "focal clarity"),
    "characters": ("hero silhouette readable", "motion intent clear", "skin/cloth material quality", "performance focus"),
    "vfx": ("effect reads from context", "emission vs lit separation", "performance budget", "no visual noise"),
    "general": ("focal hierarchy", "coherent palette", "material quality at focal points", "clean negative space"),
}


@dataclass
class CreativeDirection:
    """Structured creative intent produced BEFORE execution begins."""

    request: str
    task_type: str = "general"
    domains: List[str] = field(default_factory=list)
    mood: str = "cinematic"
    mood_traits: Dict[str, Any] = field(default_factory=dict)
    visual_language: str = "neutral_clean"
    visual_language_evidence: List[str] = field(default_factory=list)
    reference_direction: Optional[str] = None
    reference_proven: bool = False
    composition_strategy: str = ""
    composition_detail: str = ""
    lighting_philosophy: str = ""
    camera_language: str = ""
    palette_direction: str = ""
    storytelling_priorities: List[str] = field(default_factory=list)
    consistency_rules: List[str] = field(default_factory=list)
    rationale: Dict[str, List[str]] = field(default_factory=dict)

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "task_type": self.task_type,
            "domains": list(self.domains),
            "mood": self.mood,
            "mood_traits": dict(self.mood_traits),
            "visual_language": self.visual_language,
            "visual_language_evidence": list(self.visual_language_evidence),
            "reference_direction": self.reference_direction,
            "reference_proven": bool(self.reference_proven),
            "composition_strategy": self.composition_strategy,
            "composition_detail": self.composition_detail,
            "lighting_philosophy": self.lighting_philosophy,
            "camera_language": self.camera_language,
            "palette_direction": self.palette_direction,
            "storytelling_priorities": list(self.storytelling_priorities),
            "consistency_rules": list(self.consistency_rules),
            "rationale": {k: list(v) for k, v in self.rationale.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CreativeDirection":
        return cls(
            request=str(data.get("request") or ""),
            task_type=str(data.get("task_type") or "general"),
            domains=list(data.get("domains") or []),
            mood=str(data.get("mood") or "cinematic"),
            mood_traits=dict(data.get("mood_traits") or {}),
            visual_language=str(data.get("visual_language") or "neutral_clean"),
            visual_language_evidence=list(data.get("visual_language_evidence") or []),
            reference_direction=data.get("reference_direction"),
            reference_proven=bool(data.get("reference_proven")),
            composition_strategy=str(data.get("composition_strategy") or ""),
            composition_detail=str(data.get("composition_detail") or ""),
            lighting_philosophy=str(data.get("lighting_philosophy") or ""),
            camera_language=str(data.get("camera_language") or ""),
            palette_direction=str(data.get("palette_direction") or ""),
            storytelling_priorities=list(data.get("storytelling_priorities") or []),
            consistency_rules=list(data.get("consistency_rules") or []),
            rationale={str(k): list(v) for k, v in (data.get("rationale") or {}).items()},
        )

    def brief_hash(self) -> str:
        """Stable content hash: identical creative intent -> identical hash.

        Used to detect drift between iterations and to cache downstream work.
        """
        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Deterministic inference helpers
# ---------------------------------------------------------------------------


def _has(text: str, *terms: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _classify_task_type(request: str) -> str:
    text = str(request or "").lower()
    if _has(text, "website", "landing page", "dashboard", "application", "app", "interface", "widget", "hud", "umg", "menu"):
        return "application_ui" if _has(text, "website", "landing page", "dashboard", "application", "app") else "unreal_ui"
    if _has(text, "character", "metahuman", "actor", "skeletal"):
        return "characters"
    if _has(text, "vfx", "niagara", "particle", "effect"):
        return "vfx"
    if _has(text, "cinematic", "sequence", "shot", "camera", "trailer", "film"):
        return "cinematic"
    if _has(text, "room", "interior", "environment", "level", "world", "scene", "lobby", "arena", "city"):
        return "environment"
    return "general"


def _detect_mood(request: str) -> str:
    text = str(request or "").lower()
    # Explicit mood words first (most specific).
    for word, mood in (
        ("neo-noir", "dark"), ("noir", "dark"), ("dark", "dark"), ("night", "dark"),
        ("cozy", "cozy"), ("warm and cozy", "cozy"), ("homey", "cozy"),
        ("calm", "calm"), ("serene", "calm"), ("quiet", "calm"), ("peaceful", "calm"),
        ("energetic", "energetic"), ("exciting", "energetic"), ("dynamic", "energetic"),
        ("playful", "playful"), ("fun", "playful"), ("colorful", "playful"),
        ("premium", "premium"), ("luxury", "premium"), ("high-end", "premium"),
        ("futuristic", "futuristic"), ("sci-fi", "futuristic"), ("future", "futuristic"),
        ("vintage", "vintage"), ("retro", "vintage"), ("old school", "vintage"),
        ("minimal", "minimal"), ("clean", "minimal"), ("sparse", "minimal"),
        ("cinematic", "cinematic"), ("movie", "cinematic"), ("film", "cinematic"),
        ("dramatic", "dark"), ("gloomy", "dark"), ("moody", "dark"),
    ):
        if word in text:
            return mood
    return "cinematic"


def _detect_visual_language(request: str) -> Tuple[str, List[str]]:
    text = str(request or "").lower()
    for language, triggers, _traits in VISUAL_LANGUAGES:
        evidence = [t for t in triggers if t in text]
        if evidence:
            return language, evidence
    return "neutral_clean", []


def _detect_reference(request: str) -> Tuple[Optional[str], bool]:
    """Reference direction is EVIDENCE-ONLY: a literal path in the request.

    Never invents availability: if the file does not exist the reference is
    recorded as absent (``None``) with ``reference_proven=False``.
    """
    match = re.search(r"(?P<path>(?:[A-Za-z]:[\\/]|/)[^\s\"']+\.(?:png|jpe?g|webp))", str(request), re.IGNORECASE)
    if not match:
        return None, False
    path = match.group("path").rstrip(".,)")
    try:
        return (str(Path(path).resolve()) if Path(path).is_file() else None), Path(path).is_file()
    except OSError:
        return None, False


def _pick_composition(request: str, task_type: str) -> Tuple[str, str]:
    text = str(request or "").lower()
    if _has(text, "symmetr", "centered", "center", "mirror"):
        return "centered_hero", COMPOSITION_STRATEGIES["centered_hero"]
    if _has(text, "rule of thirds", "thirds"):
        return "rule_of_thirds", COMPOSITION_STRATEGIES["rule_of_thirds"]
    if _has(text, "diagonal", "angle", "dynamic framing"):
        return "diagonal", COMPOSITION_STRATEGIES["diagonal"]
    if _has(text, "depth", "layers", "foreground", "multi-layered"):
        return "layered_depth", COMPOSITION_STRATEGIES["layered_depth"]
    if _has(text, "frame", "framed", "window", "doorway", "arch"):
        return "framing", COMPOSITION_STRATEGIES["framing"]
    if task_type in ("unreal_ui", "application_ui"):
        return "rule_of_thirds", COMPOSITION_STRATEGIES["rule_of_thirds"] + "; UI grid and alignment override photography rules"
    return "layered_depth", COMPOSITION_STRATEGIES["layered_depth"]


def _pick_lighting(request: str, mood: str) -> Tuple[str, str]:
    text = str(request or "").lower()
    if _has(text, "neon", "led strip", "hologram"):
        return "neon_accent", LIGHTING_PHILOSOPHIES["neon_accent"]
    if _has(text, "studio", "softbox", "product shot"):
        return "studio", LIGHTING_PHILOSOPHIES["studio"]
    if _has(text, "candle", "fire", "practical"):
        return "motivated", LIGHTING_PHILOSOPHIES["motivated"]
    traits = MOOD_PROFILES.get(mood, MOOD_PROFILES["cinematic"])
    style = traits.get("lighting_style", "motivated")
    if style in LIGHTING_PHILOSOPHIES:
        return style, LIGHTING_PHILOSOPHIES[style]
    return "motivated", LIGHTING_PHILOSOPHIES["motivated"]


def _pick_camera(request: str, mood: str) -> str:
    text = str(request or "").lower()
    if _has(text, "orbit", "rotate around", "360"):
        return CAMERA_LANGUAGES["orbit"]
    if _has(text, "dolly", "push in", "slow push"):
        return CAMERA_LANGUAGES["dolly"]
    if _has(text, "handheld", "camera shake", "intimate"):
        return CAMERA_LANGUAGES["handheld"]
    if _has(text, "sweep", "reveal", "wide establishing", "aerial"):
        return CAMERA_LANGUAGES["sweeping"]
    traits = MOOD_PROFILES.get(mood, MOOD_PROFILES["cinematic"])
    camera = traits.get("camera", "intentional_framing")
    if camera == "dynamic_movement":
        return CAMERA_LANGUAGES["sweeping"]
    if camera == "dramatic_framing":
        return CAMERA_LANGUAGES["static_precise"]
    if camera == "intimate_framing":
        return CAMERA_LANGUAGES["intimate"]
    if camera == "precise":
        return CAMERA_LANGUAGES["static_precise"]
    return CAMERA_LANGUAGES["static_precise"]


def _pick_palette(request: str, mood: str, language: str) -> str:
    text = str(request or "").lower()
    # Palette from the selected language traits first (strongest signal).
    for lang, _triggers, traits in VISUAL_LANGUAGES:
        if lang == language and traits.get("palette"):
            return traits["palette"]
    if _has(text, "warm", "golden", "amber", "terracotta"):
        return "warm neutrals with a warm accent"
    if _has(text, "cool", "cyan", "teal", "blue"):
        return "cool neutrals with a cyan/teal accent"
    if _has(text, "monochrome", "black and white", "grayscale"):
        return "monochrome with a single accent"
    traits = MOOD_PROFILES.get(mood, MOOD_PROFILES["cinematic"])
    hint = traits.get("palette_hint", "neutral")
    return {
        "neutral": "controlled neutral base with one accent",
        "cool": "cool neutral base",
        "cool_cyan": "cool neutral base with cyan accents",
        "warm": "warm neutral base",
        "aged": "aged warm palette with desaturated color",
        "saturated": "saturated palette with high chroma accents",
        "colorful": "colorful but coordinated palette",
        "desaturated": "desaturated palette; restraint over color",
        "monochrome": "monochrome with one accent",
    }.get(hint, "controlled neutral base with one accent")


def _storytelling_priorities(task_type: str) -> List[str]:
    return list(STORYTELLING_PRIORITY_ORDER.get(task_type, STORYTELLING_PRIORITY_ORDER["general"]))


def _build_consistency_rules(
    request: str, task_type: str, mood: str, language: str, palette: str
) -> List[str]:
    rules = [
        f"maintain '{mood}' mood throughout the mission (no random mood drift between iterations)",
        f"keep the '{language}' visual language consistent across all assets placed for this goal",
        f"palette discipline: {palette}",
    ]
    if task_type in ("unreal_ui", "application_ui"):
        rules.append("shared spacing scale and type scale across all screens/widgets")
    elif task_type in ("environment", "cinematic"):
        rules.append("no random asset placement; every placed asset must serve the composition or storytelling priorities")
    if _has(request, "premium", "aaa", "production", "cinematic", "polished"):
        rules.append("visible shortcuts (placeholder geometry, default materials, floating props) are defects, not acceptable")
    return rules


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def direct_scene(
    request: str,
    *,
    context: Optional[Mapping[str, Any]] = None,
    reference: Optional[str] = None,
) -> CreativeDirection:
    """Turn a natural-language request into a structured CreativeDirection.

    ``reference`` may carry an externally validated reference path (e.g. from
    an adapter that already proved the file exists); it is recorded as proven.
    ``context`` may carry mission/domain hints (e.g. ``{"domains": [...]}``);
    they are merged, never trusted to override explicit request evidence.
    """
    text = str(request or "")
    task_type = _classify_task_type(text)
    domains = [str(d) for d in (context or {}).get("domains") or []] or detect_domains(text)
    mood = _detect_mood(text)
    language, evidence = _detect_visual_language(text)

    if reference and Path(reference).is_file():
        ref_path, ref_proven = str(Path(reference).resolve()), True
    else:
        ref_path, ref_proven = _detect_reference(text)

    composition, composition_detail = _pick_composition(text, task_type)
    lighting, lighting_detail = _pick_lighting(text, mood)
    camera = _pick_camera(text, mood)
    palette = _pick_palette(text, mood, language)
    priorities = _storytelling_priorities(task_type)
    rules = _build_consistency_rules(text, task_type, mood, language, palette)

    rationale: Dict[str, List[str]] = {
        "mood": [f"mood words in request matched '{mood}'"],
        "visual_language": evidence or ["no specific art-direction trigger; neutral clean baseline"],
        "composition": [composition_detail],
        "lighting": [lighting_detail],
        "camera": [camera],
        "palette": [palette],
    }

    return CreativeDirection(
        request=text,
        task_type=task_type,
        domains=domains,
        mood=mood,
        mood_traits=dict(MOOD_PROFILES.get(mood, MOOD_PROFILES["cinematic"])),
        visual_language=language,
        visual_language_evidence=evidence,
        reference_direction=ref_path,
        reference_proven=ref_proven,
        composition_strategy=composition,
        composition_detail=composition_detail,
        lighting_philosophy=lighting_detail,
        camera_language=camera,
        palette_direction=palette,
        storytelling_priorities=priorities,
        consistency_rules=rules,
        rationale=rationale,
    )


def consistency_report(
    direction: CreativeDirection,
    prior_briefs: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compare a direction against prior mission briefs for creative drift.

    Returns structured conflicts/warnings the supervisor can act on without a
    human: mood drift, visual-language drift, palette conflicts, or repeated
    identical briefs (duplicate creative work). Never raises.
    """
    prior = [CreativeDirection.from_dict(p) if isinstance(p, dict) else p for p in prior_briefs]
    conflicts: List[Dict[str, Any]] = []
    for index, old in enumerate(prior):
        if old.visual_language != direction.visual_language and old.visual_language != "neutral_clean":
            conflicts.append({
                "kind": "visual_language_drift",
                "prior": old.visual_language,
                "current": direction.visual_language,
                "prior_index": index,
                "severity": "medium",
                "evidence": "mission already committed to a different visual language",
            })
        if old.mood != direction.mood:
            conflicts.append({
                "kind": "mood_drift",
                "prior": old.mood,
                "current": direction.mood,
                "prior_index": index,
                "severity": "medium",
                "evidence": "mood changed between mission briefs",
            })
        if (old.palette_direction != direction.palette_direction
                and old.palette_direction and direction.palette_direction):
            conflicts.append({
                "kind": "palette_conflict",
                "prior": old.palette_direction,
                "current": direction.palette_direction,
                "prior_index": index,
                "severity": "low",
                "evidence": "palette direction diverged from the established brief",
            })
    hashes = [old.brief_hash() for old in prior]
    duplicate = hashes.count(direction.brief_hash())
    return {
        "conflicts": conflicts,
        "warnings": (
            [{"kind": "duplicate_brief", "count": duplicate, "severity": "low",
              "evidence": "identical creative brief already produced for this mission"}]
            if duplicate else []
        ),
        "consistent": not conflicts,
    }