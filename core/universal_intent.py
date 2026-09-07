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

from core.mission_policy import has_strong_read_only_marker

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

# Status/health DIAGNOSTIC missions are NOT chat: they must run real
# read-only verification probes through the pipeline (backend health + Unreal
# bridge readiness) and emit evidence, never answer with a 0-step "PASS".
# These markers are specific to system/bridge/pipeline readiness checks so
# ordinary "what is X" questions stay chat.
DIAGNOSTIC_MARKERS = (
    "health check", "check health", "health of", "health probe",
    "backend health", "bridge health", "system health", "pipeline health",
    "service health", "is healthy", "are healthy",
    "diagnostic", "diagnose",
    "readiness", "ready check", "readiness check", "is ready",
    "report ready", "reports ready",
    "is the bridge", "is the backend", "is the pipeline",
    "backend ready", "bridge ready", "unreal bridge ready",
    "bridge status", "backend status", "status of the backend",
    "status of the bridge", "status of the pipeline",
    "check the backend", "check the bridge", "check backend",
    "check bridge", "verify the backend", "verify the bridge",
    "verify backend", "verify bridge", "check whether the backend",
    "check whether the bridge", "check if the backend",
    "check if the bridge", "probe the backend", "probe the bridge",
    "backend probe", "bridge probe", "run a health", "mcp status",
    "status only", "status-only",
)

# Explicit viewport capture / proof requests are NOT chat: they are
# read-only EXECUTE missions that must run a real capture_unreal_viewport
# evidence step (a 0-step "answer" plan can never return real evidence).
# Markers cover ordinary screenshot/capture phrasings ("capture a
# screenshot", "take a screenshot", "take a fresh viewport screenshot",
# ...) so the QA plain-capture phrasing routes to a real capture plan
# instead of an ANSWER/0-step plan. They are phrase-level so ordinary
# "what is X" questions stay chat; knowledge questions ("how do I take a
# screenshot in Unreal?") are guarded below.
CAPTURE_PROOF_MARKERS = (
    "capture the current", "capture current", "capture the viewport",
    "capture viewport", "capture a viewport", "capture the viewport screen",
    "screenshot of the current", "screenshot the current",
    "screenshot of current", "screenshot current",
    "screenshot the viewport", "screenshot of the viewport",
    "screenshot the editor", "screenshot of the editor",
    "viewport screenshot", "editor viewport screenshot",
    "visual proof of the current", "proof of the current",
    "viewport proof", "viewport as evidence", "viewport evidence",
    "capture proof", "return the captured viewport",
    "return visual proof", "return viewport evidence",
    "screenshot as evidence", "screenshot for evidence",
    # ordinary imperative capture/screenshot phrasings (defect
    # plain_capture_phrasing_routing): these used to fall through to chat
    # (ANSWER, 0 steps) because "capture"/"take" are not EXECUTE_MARKERS.
    "capture a screenshot", "capture screenshot", "capture the screenshot",
    "capture a fresh screenshot", "capture a viewport screenshot",
    "capture the viewport screenshot", "capture a screenshot of the viewport",
    "take a screenshot", "take screenshot", "take the screenshot",
    "take a fresh screenshot", "take a viewport screenshot",
    "take a fresh viewport screenshot", "take the viewport screenshot",
    "take a screenshot of the viewport", "take a screenshot of the current",
    "take a screenshot of the editor", "take a screenshot of the scene",
    "take a screenshot of the level", "take a picture of the viewport",
    "capture a picture of the viewport", "capture a snapshot",
    "take a snapshot", "capture visual evidence", "take visual evidence",
    "capture evidence", "take evidence",
)

# Knowledge-question guard: "how do I take a screenshot in Unreal?" is an
# instruction question and must stay chat, never spawn a capture mission.
CAPTURE_QUESTION_MARKERS = (
    "how do i", "how do you", "how to", "what is a", "what's a",
    "what are", "what is the", "explain", "what does", "teach me",
    "tutorial",
)

# Explicit scene-VERIFICATION requests ("run the exact strict read-only
# AividoHQ verification: map X, bridge healthy, exactly N ..., missing ...,
# fresh proof") are NOT chat and NOT generic execute: each explicit item is
# planned as its own REAL read-only verification step, and PASS is impossible
# until every item is planned, executed and evidenced (defect closure).
VERIFICATION_MARKERS = (
    "verification", "verify that", "verify the scene", "verify scene",
    "verify the level", "verify the map", "verify the current state",
    "verify the state of the scene", "strict verification",
    "read-only verification", "read only verification",
    "exact verification", "scene verification", "run a verification",
    "run verification", "verification:",
)

# Explicit-check vocabulary that makes a "verification" prompt concrete.
# A verification marker alone never forces execute mode; it must name real
# facts to verify (counts, missing references, bridge/map/proof) or carry a
# strong read-only marker.
EXPLICIT_CHECK_MARKERS = (
    "exactly ", "missing skeletal", "missing prop", "missing mesh",
    "missing material", "missing reference", "bridge healthy",
    "bridge ready", "bridge status", "movable light",
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
    "spawn",
    # ^ imperative Unreal verb (spawn an actor/cube/character): without it a
    # concrete actor task like "Spawn a StaticMeshActor at (200, 200, 50)"
    # fell through to chat instead of execute.
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
    diagnostic: bool = False              # status/health check: run REAL
                                          # read-only probes (never chat)
    capture_only: bool = False            # explicit viewport capture/proof:
                                          # run ONE read-only evidence step
                                          # (capture_unreal_viewport)
    verification: bool = False            # explicit scene verification: one
                                          # REAL read-only verification step
                                          # per explicit requirement; PASS is
                                          # impossible until every item is
                                          # planned, executed and evidenced
    explicit_checks: List[Dict[str, Any]] = field(default_factory=list)
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
            "diagnostic": self.diagnostic,
            "capture_only": self.capture_only,
            "verification": self.verification,
            "explicit_checks": [dict(c) for c in self.explicit_checks],
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


def parse_explicit_checks(prompt: str) -> List[Dict[str, Any]]:
    """Deterministically extract explicit verification items from a prompt.

    Supports the verified defect-closure vocabulary:
      - "map <name>"                       -> active map identity
      - "bridge healthy|ready|..."         -> bridge health
      - "exactly N human agents / W3I props / movable lights"
      - "missing skeletal meshes"          -> 0 missing skeletal meshes
      - "missing prop mesh/material references" -> 0 null prop refs
      - proof/capture/screenshot           -> fresh real viewport proof

    Any explicit "exactly N <unknown>" count that cannot be mapped to a
    deterministic target stays a truthful `generic` check: it will be
    reported UNVERIFIED, never silently skipped or false-PASSed.
    """
    text = str(prompt or "")
    lowered = text.lower()
    checks: List[Dict[str, Any]] = []
    seen = set()

    def add(check: Dict[str, Any]) -> None:
        cid = check.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            checks.append(check)

    # 1. bridge health
    if re.search(r"bridge\s+(healthy|ready|alive|connected|up|ok|status)",
                 lowered):
        add({"id": "bridge_ready", "kind": "bridge",
             "desc": "Unreal bridge is healthy/ready"})

    # 2. active map identity (original casing preserved for the expected
    # value so the evidence reads "map AividoHQ", not "map aividohq").
    m = re.search(r"\bmap\s+([A-Za-z0-9_/.]+)", text, re.IGNORECASE)
    if m:
        expected = m.group(1)
        add({"id": "active_map", "kind": "map",
             "desc": f"active map is {expected}", "expected": expected})

    # 3. exactly N <phrase>
    for m in re.finditer(
            r"exactly\s+(\d+)\s+([a-z0-9 _\-]+?)(?=,|\.|;|$|\n| and |\))",
            lowered):
        count = int(m.group(1))
        phrase = m.group(2).strip().rstrip("s")
        if not phrase:
            continue
        if any(w in phrase for w in ("human", "agent", "character")):
            add({"id": "human_count", "kind": "count",
                 "desc": f"exactly {count} human agents",
                 "expected": count, "target": "AVIDO_Human",
                 "label": phrase})
        elif any(w in phrase for w in ("w3i", "prop")):
            add({"id": "prop_count", "kind": "count",
                 "desc": f"exactly {count} props",
                 "expected": count, "target": "W3I_", "label": phrase})
        elif "light" in phrase:
            add({"id": "movable_lights", "kind": "movable_lights",
                 "desc": f"exactly {count} movable lights",
                 "expected": count})
        else:
            # Explicit count with no deterministic target: report as
            # UNVERIFIED unless a caller-supplied mapping exists.
            add({"id": f"count_{len(checks) + 1}", "kind": "count",
                 "desc": f"exactly {count} {phrase}", "expected": count,
                 "target": None, "label": phrase})

    # 4. missing references (prop/material/skeletal)
    for m in re.finditer(
            r"missing\s+([a-z0-9 _\-/]+?)(?=,|\.|;|$|\n| and |\))",
            lowered):
        phrase = m.group(1).strip()
        if not phrase:
            continue
        if any(w in phrase for w in ("prop", "material", "reference")):
            add({"id": "missing_prop_references",
                 "kind": "missing_prop_references",
                 "desc": "no missing prop mesh/material references",
                 "expected": 0, "target": "W3I_"})
        elif any(w in phrase for w in ("skeletal", "mesh")):
            add({"id": "missing_skeletal_meshes",
                 "kind": "missing_skeletal_meshes",
                 "desc": "no missing skeletal meshes",
                 "expected": 0, "target": "AVIDO_Human"})
        else:
            add({"id": "missing_generic", "kind": "generic",
                 "desc": f"no missing {phrase}", "expected": 0})

    # 5. fresh real viewport proof
    if re.search(r"\b(proof|capture|screenshot)\b", lowered) and any(
            w in lowered for w in ("fresh", "real", "current", "proof")):
        add({"id": "viewport_proof", "kind": "proof",
             "desc": "fresh real viewport proof capture"})

    return checks


def interpret_intent(prompt: str) -> UniversalIntent:
    """Layer 1: classify one prompt into a structured UniversalIntent."""
    text = str(prompt or "").strip()
    lowered = text.lower()
    intent = UniversalIntent(prompt=text)

    # ---- mode -----------------------------------------------------------
    # Explicit scene verification wins over the generic diagnostic/capture
    # vocabulary: a prompt like "... verification: map X, bridge healthy,
    # exactly 8 human agents ..." contains the substring "bridge health"
    # (a diagnostic marker) and "viewport proof" (a capture marker), but the
    # user asked for ONE strict verification mission with per-item checks.
    verification_trigger = (
        _has(lowered, *VERIFICATION_MARKERS)
        and (has_strong_read_only_marker(prompt)
             or _has(lowered, *EXPLICIT_CHECK_MARKERS))
    )
    if verification_trigger:
        # Explicit scene verification: one REAL read-only verification step
        # per explicit requirement, and PASS is impossible until every item
        # is planned, executed and evidenced. Each check is parsed
        # deterministically; unparseable items fail truthfully as
        # UNVERIFIED_REQUIREMENTS, never a false PASS.
        intent.mode = "execute"
        intent.read_only = True
        intent.verification = True
        intent.explicit_checks = parse_explicit_checks(text)
        intent.warnings.append(
            "Explicit verification request: one real read-only verification "
            "step per stated requirement; PASS requires every item planned, "
            "executed and evidenced (UNVERIFIED_REQUIREMENTS otherwise)."
        )
    elif _has(lowered, *DIAGNOSTIC_MARKERS):
        # Status/health diagnostics are READ-ONLY but must EXECUTE real
        # probes: planning/answering chat style previously produced
        # "complete/PASS with 0 executed steps and no evidence".
        intent.mode = "execute"
        intent.read_only = True
        intent.diagnostic = True
        intent.warnings.append(
            "Diagnostic request: planned as read-only health probes "
            "(backend + Unreal bridge) with real evidence, not chat."
        )
    elif _has(lowered, *CAPTURE_PROOF_MARKERS) and not _has(
        lowered, *CAPTURE_QUESTION_MARKERS
    ):
        # Explicit viewport capture/proof requests must EXECUTE a real
        # read-only evidence step (capture_unreal_viewport) — never a 0-step
        # chat answer that cannot return real evidence. The read-only intent
        # is preserved so the policy gate still blocks any mutating tool.
        intent.mode = "execute"
        intent.read_only = True
        intent.capture_only = True
        intent.warnings.append(
            "Explicit viewport capture/proof request: planned as a "
            "read-only capture_unreal_viewport evidence step; no mutation."
        )
    elif _has(lowered, *READ_ONLY_MARKERS) and not _has(
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
    if intent.verification:
        # Verification missions prove facts with real read-only probes + the
        # explicit proof capture; the generative visual-acceptance loop is
        # out of scope (it scores scene composition, not requirement truth).
        intent.needs_visual_validation = False
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
    if intent.mode == "execute" and intent.read_only\
            and not (intent.diagnostic or intent.capture_only
                     or intent.verification):
        # Diagnostics, capture/proof and verification missions intentionally
        # stay read_only while executing their real probe/evidence steps.
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

    if intent.diagnostic:
        # Diagnostic status/health checks are read-only by design: plan only
        # the real verification probes (backend + Unreal bridge). Never
        # expand into the generic environment-polish default, which would
        # mutate the scene.
        spec.requirements.append({
            "id": "diagnostic_probe", "kind": "diagnostic",
            "desc": "Run read-only backend health and Unreal bridge "
                    "readiness probes through the real pipeline and emit "
                    "evidence for each result",
            "ops": ["probe", "verify"],
        })
        spec.defaults_applied.append(
            "Diagnostic request expanded to read-only backend + bridge "
            "probes only (no scene mutation)."
        )
        return spec

    if intent.capture_only:
        # Explicit viewport capture/proof requests expand to exactly one
        # read-only evidence capture — never a 0-step answer plan and never
        # a mutating environment-polish default.
        spec.requirements.append({
            "id": "viewport_evidence", "kind": "capture_evidence",
            "desc": "Capture the CURRENT Unreal viewport with the real "
                    "capture_unreal_viewport tool and return the captured "
                    "file as evidence (read-only; no mutation)",
            "ops": ["capture", "evidence"],
        })
        spec.defaults_applied.append(
            "Capture/proof request expanded to a single read-only "
            "capture_unreal_viewport evidence step (no scene mutation)."
        )
        return spec

    if intent.verification:
        # Explicit scene verification: ONE requirement entry per explicit
        # check. Every entry is marked explicit=True so the mission verdict
        # gate can refuse PASS until each one is planned, executed AND
        # evidenced. An unparseable check is kept as a truthful generic
        # requirement -> reported UNVERIFIED, never silently skipped.
        checks = intent.explicit_checks or []
        if not checks:
            spec.requirements.append({
                "id": "verification_unparsed", "kind": "verification",
                "desc": ("explicit verification items could not be "
                          "deterministically parsed"),
                "ops": [], "explicit": True,
                "check": {
                    "id": "verification_unparsed", "kind": "generic",
                    "desc": ("explicit verification items could not be "
                              "deterministically parsed"),
                },
            })
        for index, check in enumerate(checks):
            spec.requirements.append({
                "id": f"verify_{index}", "kind": "verification",
                "desc": check.get("desc") or f"verify {check.get('id')}",
                "ops": ["verify"], "explicit": True,
                "check": dict(check),
            })
        spec.defaults_applied.append(
            "Verification request expanded to one real read-only "
            "verification step per explicit requirement; PASS requires "
            "every item planned, executed and evidenced."
        )
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
            lowered = intent.prompt.lower()
            precise_actor = (
                _has(lowered, "actor", "staticmeshactor", "cube", "prop")
                and (_has(lowered, "spawn", "place", "put", "create")
                     or re.search(r"-?\d+[\s,]+-?\d+[\s,]+-?\d+", lowered))
            )
            if precise_actor:
                # A concrete single-actor placement request (e.g. "Spawn a
                # StaticMeshActor using a basic cube mesh at location
                # (200, 200, 50), then verify that the actor actually exists
                # in the level actor list") is NOT a generic environment
                # polish task: expand it to exactly one spawn + one actor
                # read-back requirement.  The planner honors the requested
                # coordinates and adds an independent get_actor verify step,
                # so a PASS verdict is only produced after the actor exists.
                spec.requirements.append({
                    "id": "actor_place", "kind": "actor",
                    "desc": "Spawn the requested StaticMeshActor at the "
                            "given location and verify it exists in the "
                            "level actor list",
                    "ops": ["spawn", "verify"],
                })
                spec.defaults_applied.append(
                    "Precise actor placement request: single spawn + "
                    "read-back verification (no invented env polish)."
                )
            else:
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
