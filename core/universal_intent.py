"""unreal_coder intent.py — Universal Intent Router + Requirement Expander.

Deterministic, dependency-free interpretation of an arbitrary natural-language
Unreal task into a structured intent + expanded requirements.

Layer 1 (Intent Router): classifies the task into domains, deliverables,
quality mode, and validation needs. Never asks the user to pick a specialist.

Layer 2 (Requirement Expander): translates the intent into an actionable
requirement specification with safe defaults. Only genuinely destructive /
credential / licensing ambiguity justifies asking the user; reversible work
prefers execution over interrogation.

This module is engine-agnostic and deterministic: it performs zero I/O and
makes no network calls, so tests can validate routing without a live editor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# --------------------------------------------------------------------------
# Domain vocabulary: internal specialist routing
# --------------------------------------------------------------------------

# domain -> trigger phrases (substring, lowercase). Ordered by specificity:
# the first matching phrase wins, so put distinctive phrases before generic.
DOMAIN_TRIGGERS: List[tuple] = [
    ("cinematics", ("sequencer", "cinematic", "level sequence", "camera cut",
                    "film", "trailer", "shot", "camera animation",
                    "cutscene", "in-game movie", "intro", "camera flythrough",
                    "flythrough", "camera path", "camera intro")),
    ("ui", ("main menu", "umg", "widget", "hud", "settings menu", "pause menu",
            "character picker", "character selection", "login", "dashboard",
            "inventory screen", "ui", "user interface", "menu", "button",
            "touch ui", "controller ui", "common ui")),
    ("gameplay", ("game mode", "player controller", "gameplay", "shooter",
                  "racing game", "puzzle game", "platformer", "interaction "
                  "system", "combat", "respawn", "score system", "health "
                  "system", "multiplayer", "lobby", "networking", "replication")),
    ("level_design", ("level design", "blockout", "greybox", "graybox",
                      "arena", "game map", "combat arena", "level layout")),
    ("world_building", ("world building", "landscape", "terrain", "city map",
                        "open world", "world partition", "roads", "foliage "
                        "placement", "forest", "procedural placement",
                        "large world", "gis")),
    ("environment_art", ("environment", "room", "apartment", "interior",
                         "scene", "museum", "walkthrough", "props", "set "
                         "dressing", "make me a cool room", "environment art")),
    ("materials", ("material", "shader", "pbr", "texture set", "master "
                   "material", "material instance", "tiling", "surface "
                   "type", "looks bad", "materials look")),
    ("lighting", ("lighting", "fix my light", "lights", "lumen", "global "
                  "illumination", "illumination", "shadows", "light study",
                  "brighter", "brighten", "brighten up", "darker", "darken",
                  "mood lighting")),
    ("archviz", ("archviz", "architectural", "architecture", "interior "
                 "visualization", "exterior visualization", "floor plan",
                 "apartment tour", "real estate")),
    ("characters", ("character", "skeletal mesh", "animation blueprint",
                    "locomotion", "retarget", "ik", "metahuman")),
    ("vfx", ("niagara", "vfx", "particles", "smoke", "fire", "dust",
             "weather effect", "explosion", "energy effect")),
    ("audio", ("audio", "sound", "music", "sfx", "ambient sound", "mix",
               "sound cue", "spatial audio")),
    ("media", ("media", "video playback", "media player", "media texture",
               "in-world screen", "streaming video")),
    ("optimization", ("optimize", "optimization", "performance", "fps",
                      "draw calls", "shader cost", "texture memory",
                      "bottleneck", "too slow", "lag", "profiling")),
    ("asset_pipeline", ("import", "fbx", "obj", "gltf", "glb", "asset "
                        "pipeline", "asset intake", "prepare asset",
                        "clean up mesh", "asset looks", "fix this asset",
                        "delete the unused", "delete unused assets",
                        "asset cleanup", "unused test assets",
                        "unused assets", "delete the asset", "delete assets")),
    ("packaging", ("package", "ship build", "shipping build", "cook",
                   "deployment")),
]

# Deliberately last: generic visuals apply on top of other domains.
FALLBACK_DOMAIN = "general_unreal"

QUALITY_TRIGGERS: List[tuple] = [
    ("photoreal", ("photoreal", "photorealistic", "photo real", "next-gen",
                   "next gen", "ultra realistic", "hyperrealistic")),
    ("cinematic", ("cinematic", "film", "movie", "trailer", "hollywood")),
    ("production", ("production", "production-quality", "production quality",
                    "polished", "ship it", "release quality")),
    ("high", ("high quality", "high-quality", "high fidelity",
              "high-fidelity", "beautiful", "gorgeous", "stunning", "pretty",
              "make it prettier", "look like a movie")),
    ("standard", ("standard", "good quality", "normal quality")),
    ("prototype", ("prototype", "blockout", "greybox", "graybox", "block out",
                   "rough", "placeholder", "draft", "quick", "fast")),
    ("performance", ("mobile-optimized", "performance-first", "mobile",
                     "low-end", "optimized for performance", "60 fps",
                     "performance budget")),
]

PLATFORM_TRIGGERS: List[tuple] = [
    ("windows", ("windows", "pc", "desktop")),
    ("mobile", ("mobile", "ios", "android", "tablet", "touch")),
    ("console", ("console", "playstation", "xbox", "ps5")),
    ("vr", ("vr", "virtual reality", "oculus", "quest")),
]

# Vague prompts: no clear deliverable noun, but a visual goal.
VAGUE_VISUAL_MARKERS = (
    "make it prettier", "make it better", "improve it", "make it look",
    "looks bad", "fix it", "more realistic", "next-gen", "next gen",
    "looks like a movie", "cinematic feel", "polish it", "prettier",
)

READ_ONLY_MARKERS = (
    "inspect", "inspection", "tell me", "what is", "what's", "list the",
    "list actors", "report", "describe", "summarize", "status of",
    "how many", "check the current", "check if", "is the bridge",
)

# Negation markers: when a domain trigger word appears only after one of
# these, the user EXCLUDED that scope ("don't touch gameplay").
NEGATION_MARKERS = (
    "don't touch", "dont touch", "without touching", "don't modify",
    "dont modify", "no gameplay", "no blender", "no multiplayer",
    "without any gameplay", "don't build", "dont build",
)

EXECUTE_MARKERS = (
    "create", "make", "build", "generate", "add", "import", "fix", "improve",
    "optimize", "repair", "design", "construct", "convert", "prepare",
    "render", "record", "set up", "setup", "polish", "turn this", "turn my",
    "block out", "blockout", "greybox", "graybox", "delete", "remove",
    "clean up", "cleanup", "replace", "wire", "stage",
    "i want", "i need", "give me",        # implicit action phrasing
    "brighten", "tweak", "adjust", "fix up", "touch up",
)

DESTRUCTIVE_MARKERS = (
    "delete all", "wipe", "reset project", "remove everything",
    "overwrite the original", "delete the project", "mass delete",
    "delete every asset", "reformat",
    # Scoped deletion of named assets is still destructive: a backup
    # checkpoint + provenance is required before it runs.
    "delete the unused", "delete unused", "unused assets", "delete assets",
    "delete the asset", "asset cleanup", "clean up assets",
)


# --------------------------------------------------------------------------
# Layer 1 — Intent
# --------------------------------------------------------------------------

@dataclass
class UniversalIntent:
    """Structured interpretation of one natural-language request."""

    prompt: str
    mode: str = "execute"                 # chat | plan | execute
    domains: List[str] = field(default_factory=list)
    primary_domain: str = FALLBACK_DOMAIN
    deliverables: List[str] = field(default_factory=list)
    quality: str = "standard"
    quality_source: str = "default"       # explicit | inferred | default
    platforms: List[str] = field(default_factory=lambda: ["windows"])
    needs_visual_validation: bool = False
    needs_blender: bool = False
    needs_assets: bool = False
    needs_sequencer: bool = False
    needs_ui: bool = False
    needs_gameplay: bool = False
    needs_networking: bool = False
    needs_render: bool = False
    vague: bool = False
    destructive: bool = False
    read_only: bool = False
    mixed: bool = False                   # e.g. UI + cinematic + materials
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "domains": list(self.domains),
            "primary_domain": self.primary_domain,
            "deliverables": list(self.deliverables),
            "quality": self.quality,
            "quality_source": self.quality_source,
            "platforms": list(self.platforms),
            "needs_visual_validation": self.needs_visual_validation,
            "needs_blender": self.needs_blender,
            "needs_assets": self.needs_assets,
            "needs_sequencer": self.needs_sequencer,
            "needs_ui": self.needs_ui,
            "needs_gameplay": self.needs_gameplay,
            "needs_networking": self.needs_networking,
            "needs_render": self.needs_render,
            "vague": self.vague,
            "destructive": self.destructive,
            "read_only": self.read_only,
            "mixed": self.mixed,
            "warnings": list(self.warnings),
        }


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def detect_domains(text: str) -> List[str]:
    lowered = text.lower()
    found: List[str] = []
    for domain, triggers in DOMAIN_TRIGGERS:
        if any(t in lowered for t in triggers):
            found.append(domain)
    if not found:
        # Pure visual polish ("make it prettier") still routes somewhere.
        if _has(lowered, *VAGUE_VISUAL_MARKERS) or _has(
            lowered, *QUALITY_TRIGGERS[3][1]
        ):
            found.append("environment_art")
            found.append("lighting")
            found.append("materials")
        else:
            found.append(FALLBACK_DOMAIN)
    return found


def detect_quality(text: str, domains: List[str]) -> tuple:
    lowered = text.lower()
    for quality, triggers in QUALITY_TRIGGERS:
        if any(t in lowered for t in triggers):
            return quality, "explicit"
    # Inference: prototypes never get cinematic rendering; cinematics do.
    if "cinematics" in domains or "archviz" in domains:
        return "cinematic", "inferred"
    if "level_design" in domains and not _has(lowered, "lighting", "material"):
        return "prototype", "inferred"
    if "optimization" in domains:
        return "performance", "inferred"
    return "standard", "default"


def detect_platforms(text: str) -> List[str]:
    lowered = text.lower()
    platforms = []
    for platform, triggers in PLATFORM_TRIGGERS:
        if any(t in lowered for t in triggers):
            platforms.append(platform)
    return platforms or ["windows"]


def _extract_deliverables(text: str, domains: List[str]) -> List[str]:
    lowered = text.lower()
    deliverables: List[str] = []
    table = [
        ("menu", ("menu", "hud", "ui screen", "login")),
        ("cinematic", ("cinematic", "trailer", "film", "cutscene", "shot")),
        ("game_loop", ("game", "shooter", "racing", "puzzle", "platformer")),
        ("environment", ("environment", "room", "apartment", "scene",
                         "museum", "forest", "city", "arena", "interior",
                         "world")),
        ("asset", ("asset", "mesh", "model", "fbx", "obj", "gltf", "glb")),
        ("material", ("material", "texture", "shader", "pbr")),
        ("lighting", ("lighting", "light", "illumination")),
        ("camera", ("camera", "shot", "walkthrough", "camera path")),
        ("optimization_report", ("optimize", "performance", "fps")),
        ("vfx", ("niagara", "vfx", "particles", "smoke", "fire")),
        ("audio", ("audio", "sound", "music", "sfx")),
        ("media", ("video", "media", "playback")),
    ]
    for name, triggers in table:
        if any(t in lowered for t in triggers) and name not in deliverables:
            deliverables.append(name)
    # Derive from domains as a guarantee of minimum coverage.
    domain_deliverable = {
        "ui": "menu", "cinematics": "cinematic", "gameplay": "game_loop",
        "environment_art": "environment", "world_building": "environment",
        "materials": "material", "lighting": "lighting",
        "archviz": "environment", "vfx": "vfx", "audio": "audio",
        "media": "media", "optimization": "optimization_report",
        "asset_pipeline": "asset",
    }
    for domain in domains:
        d = domain_deliverable.get(domain)
        if d and d not in deliverables:
            deliverables.append(d)
    return deliverables or ["scene"]


def _domain_negated(lowered: str, domain: str, triggers) -> bool:
    """True when the ONLY mentions of a domain's triggers occur inside a
    negation clause ("don't touch gameplay")."""
    mentioned = any(t in lowered for t in triggers)
    if not mentioned:
        return False
    for marker in NEGATION_MARKERS:
        idx = lowered.find(marker)
        if idx < 0:
            continue
        tail = lowered[idx + len(marker):]
        if any(t in tail for t in triggers):
            # Only negated when the trigger never appears BEFORE the marker.
            head = lowered[:idx]
            if not any(t in head for t in triggers):
                return True
    return False


def interpret_intent(prompt: str) -> UniversalIntent:
    """Layer 1: classify one prompt into a structured UniversalIntent."""
    text = str(prompt or "").strip()
    lowered = text.lower()
    intent = UniversalIntent(prompt=text)

    # ---- mode -----------------------------------------------------------
    if _has(lowered, *READ_ONLY_MARKERS) and not _has(
        lowered, *EXECUTE_MARKERS
    ):
        intent.mode = "chat"
        intent.read_only = True
    elif _has(lowered, "plan only", "don't execute", "do not execute",
              "roadmap", "just plan"):
        intent.mode = "plan"
    elif _has(lowered, *EXECUTE_MARKERS):
        intent.mode = "execute"
    else:
        # Conversational phrasing -> chat.
        intent.mode = "chat"
        intent.read_only = True

    # ---- domains --------------------------------------------------------
    intent.domains = detect_domains(lowered)
    # Anti-overreach: drop domains the user explicitly excluded
    # ("tweak the lighting, don't touch gameplay").
    excluded_domains = [
        domain for domain, markers in DOMAIN_TRIGGERS
        for _ in [0] if _domain_negated(lowered, domain, markers)
    ]
    if excluded_domains and intent.domains:
        remaining = [d for d in intent.domains if d not in excluded_domains]
        if remaining:  # never drop the LAST domain (request must stay valid)
            intent.domains = remaining
            for domain in excluded_domains:
                intent.warnings.append(
                    f"Domain '{domain}' excluded by user request.")
    intent.primary_domain = intent.domains[0]
    intent.mixed = len(intent.domains) > 1

    # ---- quality / platform --------------------------------------------
    intent.quality, intent.quality_source = detect_quality(
        lowered, intent.domains
    )
    intent.platforms = detect_platforms(lowered)
    if "mobile" in intent.platforms and intent.quality in {
        "cinematic", "photoreal",
    }:
        intent.warnings.append(
            "Cinematic/photoreal quality on a mobile target was downgraded "
            "to 'high' to keep the configuration deliverable."
        )
        intent.quality = "high"

    # ---- needs ----------------------------------------------------------
    intent.needs_visual_validation = intent.mode == "execute" and (
        intent.domains != [FALLBACK_DOMAIN]
        or intent.quality in {"high", "production", "cinematic", "photoreal"}
        or _has(lowered, *VAGUE_VISUAL_MARKERS)
    )
    intent.needs_blender = _has(
        lowered, "blender", "clean up mesh", "mesh cleanup", "retopolog",
        "uv unwrap", "fix this asset", "asset looks bad", "decimate",
        "prepare asset", "repair mesh",
    ) or "asset_pipeline" in intent.domains and _has(
        lowered, "broken", "bad", "fix", "repair", "wrong", "ugly", "clean",
    )
    intent.needs_assets = _has(
        lowered, "import", "fbx", "obj", "gltf", "glb", "asset",
        "texture", "mesh",
    )
    intent.needs_sequencer = "cinematics" in intent.domains
    intent.needs_ui = "ui" in intent.domains
    intent.needs_gameplay = "gameplay" in intent.domains or _has(
        lowered, "playable", "player", "walk", "shoot", "drive"
    )
    intent.needs_networking = _has(
        lowered, "multiplayer", "networking", "replication", "session",
        "join", "lobby", "rpc",
    )
    intent.needs_render = intent.quality in {
        "cinematic", "photoreal", "production",
    } or _has(lowered, "render", "record", "movie", "trailer", "frames")

    intent.vague = (
        len(text.split()) <= 6 and not _has(lowered, *EXECUTE_MARKERS)
    ) or _has(lowered, *VAGUE_VISUAL_MARKERS)
    intent.destructive = _has(lowered, *DESTRUCTIVE_MARKERS)
    if intent.destructive:
        intent.warnings.append(
            "Request contains destructive markers; the planner will require "
            "explicit backup/checkpoint steps before any deletion."
        )
    if intent.mode == "execute" and intent.read_only:
        intent.mode = "execute"
        intent.read_only = False
    return intent


# --------------------------------------------------------------------------
# Layer 2 — Requirement expansion
# --------------------------------------------------------------------------

@dataclass
class RequirementSpec:
    """Expanded, actionable internal specification for one intent."""

    objective: str
    quality: str
    platforms: List[str]
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    defaults_applied: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "quality": self.quality,
            "platforms": list(self.platforms),
            "requirements": [dict(r) for r in self.requirements],
            "defaults_applied": list(self.defaults_applied),
            "open_questions": list(self.open_questions),
            "excluded": list(self.excluded),
        }


# domain -> (requirement dicts). `ops` are planner hints.
DOMAIN_REQUIREMENTS: Dict[str, List[Dict[str, Any]]] = {
    "ui": [
        {"id": "ui_create", "kind": "ui", "desc": "Create the requested UMG "
         "widget with layout hierarchy and styling", "ops": ["umg"]},
        {"id": "ui_bind", "kind": "ui", "desc": "Wire interactions (buttons, "
         "input, focus) and visible state", "ops": ["umg", "binding"]},
        {"id": "ui_validate", "kind": "validation", "desc": "Verify layout, "
         "readability and interaction at target resolution",
         "ops": ["widget_text", "runtime_ui", "capture"]},
    ],
    "cinematics": [
        {"id": "seq_create", "kind": "sequencer", "desc": "Create a Level "
         "Sequence with camera cuts and framing", "ops": ["sequencer"]},
        {"id": "seq_polish", "kind": "sequencer", "desc": "Refine camera "
         "framing, timing and transitions", "ops": ["camera_framing"]},
        {"id": "seq_validate", "kind": "validation", "desc": "Capture "
         "representative frames and verify composition", "ops": ["capture"]},
    ],
    "environment_art": [
        {"id": "env_stage", "kind": "environment", "desc": "Stage/extend the "
         "environment with actors, scale and composition", "ops": ["spawn"]},
        {"id": "env_materials", "kind": "materials", "desc": "Assign "
         "coherent materials and surface variation", "ops": ["materials"]},
        {"id": "env_lighting", "kind": "lighting", "desc": "Establish "
         "motivated lighting and exposure", "ops": ["lights"]},
        {"id": "env_validate", "kind": "validation", "desc": "Visual check "
         "of the composed scene", "ops": ["capture"]},
    ],
    "materials": [
        {"id": "mat_audit", "kind": "materials", "desc": "Audit existing "
         "materials for plausibility (no blanket gloss/emissive)",
         "ops": ["materials"]},
        {"id": "mat_apply", "kind": "materials", "desc": "Apply/improve "
         "material assignments and instances", "ops": ["materials"]},
        {"id": "mat_validate", "kind": "validation", "desc": "Visual check "
         "of surface response", "ops": ["capture"]},
    ],
    "lighting": [
        {"id": "light_audit", "kind": "lighting", "desc": "Audit current "
         "lights, exposure and shadow behavior", "ops": ["lights"]},
        {"id": "light_fix", "kind": "lighting", "desc": "Repair or re-balance "
         "lighting per the requested mood", "ops": ["lights"]},
        {"id": "light_validate", "kind": "validation", "desc": "Visual check "
         "of exposure and readability", "ops": ["capture"]},
    ],
    "gameplay": [
        {"id": "gm_mode", "kind": "gameplay", "desc": "Set up GameMode, "
         "PlayerController and pawn/character", "ops": ["blueprint"]},
        {"id": "gm_input", "kind": "gameplay", "desc": "Wire input and "
         "camera behavior", "ops": ["blueprint", "binding"]},
        {"id": "gm_validate", "kind": "validation", "desc": "Execute a "
         "runtime validation (PIE smoke) of the loop", "ops": ["pie"]},
    ],
    "level_design": [
        {"id": "ld_blockout", "kind": "level", "desc": "Create the blockout "
         "layout with correct scale", "ops": ["spawn"]},
        {"id": "ld_validate", "kind": "validation", "desc": "Visual + actor "
         "validation of the layout", "ops": ["capture"]},
    ],
    "world_building": [
        {"id": "wb_terrain", "kind": "world", "desc": "Terrain/landscape "
         "setup at correct real-world scale", "ops": ["terrain"]},
        {"id": "wb_content", "kind": "world", "desc": "Distribute content "
         "(foliage/props/roads) with performance in mind",
         "ops": ["world", "foliage"]},
        {"id": "wb_validate", "kind": "validation", "desc": "Visual + "
         "performance validation", "ops": ["capture"]},
    ],
    "archviz": [
        {"id": "av_scale", "kind": "environment", "desc": "Verify real-world "
         "scale and architectural readability", "ops": ["spawn", "inspect"]},
        {"id": "av_lighting", "kind": "lighting", "desc": "High-quality "
         "indirect lighting and exposure", "ops": ["lights"]},
        {"id": "av_materials", "kind": "materials", "desc": "Architectural "
         "material presentation (glass, floors, walls)", "ops": ["materials"]},
        {"id": "av_camera", "kind": "camera", "desc": "Walkthrough camera "
         "path and framing", "ops": ["camera_framing"]},
        {"id": "av_validate", "kind": "validation", "desc": "Visual check "
         "against architectural quality standards", "ops": ["capture"]},
    ],
    "characters": [
        {"id": "ch_stage", "kind": "characters", "desc": "Stage character, "
         "animation and materials", "ops": ["character"]},
        {"id": "ch_validate", "kind": "validation", "desc": "Verify visible "
         "character and framing", "ops": ["capture", "runtime"]},
    ],
    "vfx": [
        {"id": "vfx_create", "kind": "vfx", "desc": "Create Niagara effect "
         "within a restrained budget", "ops": ["niagara"]},
        {"id": "vfx_validate", "kind": "validation", "desc": "Visual check "
         "of the effect", "ops": ["capture"]},
    ],
    "audio": [
        {"id": "audio_stage", "kind": "audio", "desc": "Stage audio assets "
         "and triggers", "ops": ["audio"]},
        {"id": "audio_validate", "kind": "validation", "desc": "Verify "
         "playback state (non-visual)", "ops": ["audio_check"]},
    ],
    "media": [
        {"id": "media_stage", "kind": "media", "desc": "Set up media player "
         "and in-world surface", "ops": ["media"]},
        {"id": "media_validate", "kind": "validation", "desc": "Verify "
         "playback state", "ops": ["media_check"]},
    ],
    "optimization": [
        {"id": "opt_measure", "kind": "optimization", "desc": "Measure the "
         "baseline before changing anything", "ops": ["stats"]},
        {"id": "opt_fix", "kind": "optimization", "desc": "Apply the "
         "highest-value, quality-preserving fixes", "ops": ["stats", "lod"]},
        {"id": "opt_verify", "kind": "validation", "desc": "Re-measure and "
         "compare against baseline", "ops": ["stats", "capture"]},
    ],
    "asset_pipeline": [
        {"id": "asset_intake", "kind": "assets", "desc": "Inspect incoming "
         "assets before use (scale/orientation/UVs/materials)",
         "ops": ["asset_intake"]},
        {"id": "asset_import", "kind": "assets", "desc": "Import into the "
         "correct /Game folder with naming conventions", "ops": ["import"]},
        {"id": "asset_validate", "kind": "validation", "desc": "Verify "
         "imported asset state in Unreal", "ops": ["import_verify"]},
    ],
    "packaging": [
        {"id": "pkg_build", "kind": "packaging", "desc": "Configure and run "
         "the packaging/cook pipeline", "ops": ["package"]},
        {"id": "pkg_validate", "kind": "validation", "desc": "Verify the "
         "output artifact", "ops": ["package_check"]},
    ],
}

# Domains that must NOT appear unless explicitly requested (anti-overreach).
EXCLUDED_BY_DEFAULT = {
    "multiplayer": "Networking is not added unless the request names it.",
    "blender": "Blender/DCC repair only when asset intake reports it is needed.",
    "packaging": "Packaging only when the request asks to ship/cook.",
}


def expand_requirements(intent: UniversalIntent) -> RequirementSpec:
    """Layer 2: expand an intent into an actionable requirement spec.

    Vague prompts expand into the minimum sensible visual-improvement set;
    concrete prompts expand only the domains they name. Never invents product
    scope (no multiplayer/packaging/DCC unless justified).
    """
    spec = RequirementSpec(
        objective=intent.prompt.strip() or "Unspecified Unreal task",
        quality=intent.quality,
        platforms=list(intent.platforms),
    )

    if intent.mode in {"chat", "plan"}:
        # No environment mutation: the deliverable is the answer itself.
        spec.requirements.append({
            "id": "answer", "kind": "answer",
            "desc": "Produce a direct answer/plan for the request",
            "ops": ["answer"],
        })
        return spec

    seen = set()
    vague_visual_set = {"environment_art", "lighting", "materials"}
    if intent.vague and (intent.domains == [FALLBACK_DOMAIN]
                         or set(intent.domains) == vague_visual_set):
        # Genuinely vague ("make it prettier"): minimum visual uplift set.
        for domain in ("environment_art", "lighting", "materials"):
            for req in DOMAIN_REQUIREMENTS.get(domain, []):
                spec.requirements.append(dict(req))
                seen.add(req["id"])
        spec.defaults_applied.append(
            "Vague visual request expanded to environment+lighting+materials "
            "polish with visual validation (safe, reversible defaults)."
        )
    else:
        for domain in intent.domains:
            for req in DOMAIN_REQUIREMENTS.get(domain, []):
                if req["id"] not in seen:
                    spec.requirements.append(dict(req))
                    seen.add(req["id"])
        if not spec.requirements:
            for req in DOMAIN_REQUIREMENTS["environment_art"]:
                spec.requirements.append(dict(req))
            spec.defaults_applied.append(
                "No domain requirements matched; applied the general "
                "environment default with visual validation."
            )

    # Cross-domain expansion driven by intent flags.
    if intent.quality in {"production", "cinematic", "photoreal"}:
        spec.requirements.append({
            "id": "quality_gate", "kind": "validation",
            "desc": "High visual quality threshold enforced by the Visual "
            "Director before acceptance", "ops": ["visual_gate"],
        })
        # Photoreal/cinematic surfaces demand material + lighting craft even
        # when the user did not name them (a photoreal menu is still lit and
        # surfaced work). Seeded before requirement ordering below.
        seeded = {r["id"] for r in spec.requirements}
        for domain in ("materials", "lighting"):
            for req in DOMAIN_REQUIREMENTS.get(domain, []):
                if req["id"] not in seeded:
                    spec.requirements.append(dict(req))
                    seeded.add(req["id"])
    if intent.needs_networking:
        spec.requirements.append({
            "id": "net_review", "kind": "gameplay",
            "desc": "Review authority/replication/session architecture for "
            "the requested networking", "ops": ["networking"],
        })
    if intent.destructive:
        spec.requirements.insert(0, {
            "id": "backup", "kind": "safety",
            "desc": "Create a backup/checkpoint before any destructive "
            "operation", "ops": ["backup"],
        })
        spec.requirements.append({
            "id": "provenance", "kind": "safety",
            "desc": "Record provenance of anything replaced or removed",
            "ops": ["provenance"],
        })
        # Scoped asset deletion/cleanup capability with absence verification.
        if "asset_pipeline" in intent.domains:
            spec.requirements.append({
                "id": "cleanup", "kind": "cleanup",
                "desc": "Delete the scoped assets and verify their absence",
                "ops": ["delete_asset", "verify_absence"],
            })

    # Anti-overreach: record what was deliberately excluded.
    if not intent.needs_networking:
        spec.excluded.append(EXCLUDED_BY_DEFAULT["multiplayer"])
    if not intent.needs_blender:
        spec.excluded.append(EXCLUDED_BY_DEFAULT["blender"])
    if "packaging" not in intent.domains:
        spec.excluded.append(EXCLUDED_BY_DEFAULT["packaging"])

    # Genuine blockers the user must resolve (rare by design).
    if intent.destructive and not intent.domains:
        spec.open_questions.append(
            "Destructive request with no target scope; confirm what may be "
            "deleted or replaced."
        )
    return spec


def interpret_and_expand(prompt: str) -> tuple:
    """Convenience: one call returns (UniversalIntent, RequirementSpec)."""
    intent = interpret_intent(prompt)
    return intent, expand_requirements(intent)
