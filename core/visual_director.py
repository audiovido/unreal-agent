"""visual_director.py — the Autonomous Visual Director.

The director translates a normal-user's natural-language visual request into a
structured, measurable VisualTarget; decides art direction (hierarchy,
placement, camera mood, palette, tool routing); maps measured defects onto
bounded actions (changed-strategy, never random value shuffles); logs every
iteration as problem/hypothesis/change/before/after/result; and runs a
self-critique gate against actual captured evidence before delivery.

It deliberately contains NO Unreal, AvaLive or Blender specifics — the runtime
adapters that execute actions live outside this module.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# --------------------------------------------------------------------------
# Intent vocabulary -> measurable goals
# --------------------------------------------------------------------------

MOODS = {
    "cinematic":      {"brightness": "dark", "contrast": "high", "depth": "high",
                      "style": "cinematic", "vignette": True},
    "premium":        {"brightness": "dark", "contrast": "medium", "depth": "high",
                      "style": "premium", "lighting_style": "cinematic"},
    "cinematic premium": {"brightness": "dark", "contrast": "high", "depth": "high",
                          "style": "premium cinematic", "lighting_style": "cinematic"},
    "luxury":         {"brightness": "medium_dark", "contrast": "medium", "depth": "high",
                      "palette_hint": "warm_accents"},
    "realistic":      {"brightness": "balanced", "contrast": "natural", "depth": "medium"},
    "realistic human": {"brightness": "balanced", "contrast": "natural", "depth": "medium",
                       "subject": "realistic_human"},
    "futuristic":     {"brightness": "medium_dark", "accent": "cyan", "style": "futuristic",
                      "lighting_style": "neon_accents"},
    "cozy":           {"brightness": "medium", "contrast": "soft", "palette_hint": "warm"},
    "minimal":        {"complexity": "low", "brightness": "balanced", "depth": "medium"},
    "clean":          {"complexity": "low", "brightness": "balanced"},
    "immersive":      {"depth": "high", "complexity": "moderate"},
    "dramatic":       {"contrast": "high", "brightness": "dark", "lighting_style": "moody"},
    "aaa":            {"quality": "max", "complexity": "high", "brightness": "balanced"},
    "a a a":          {"quality": "max", "complexity": "high", "brightness": "balanced"},
    "dark":           {"brightness": "dark"},
    "bright":         {"brightness": "bright"},
}
SHOTS = {
    "hero shot":   {"camera": "hero", "subject_screen_coverage": [0.30, 0.55],
                    "upper_body": True, "head_fully_visible": True},
    "hero":        {"camera": "hero", "subject_screen_coverage": [0.30, 0.55],
                    "upper_body": True, "head_fully_visible": True},
    "close-up":    {"camera": "close", "subject_screen_coverage": [0.40, 0.70],
                    "head_fully_visible": True},
    "wide shot":   {"camera": "wide", "subject_screen_coverage": [0.12, 0.35],
                    "environment_importance": "high"},
    "portrait":    {"camera": "portrait", "subject_screen_coverage": [0.28, 0.48],
                    "upper_body": True, "head_fully_visible": True},
    "three-quarter": {"camera": "three_quarter", "subject_screen_coverage": [0.26, 0.46],
                      "upper_body": True, "head_fully_visible": True},
}
PLACEMENTS = {
    "left":        {"screen_position": "left", "x_center_frac": [0.24, 0.42]},
    "left_center": {"screen_position": "left_center", "x_center_frac": [0.26, 0.46]},
    "center":      {"screen_position": "center", "x_center_frac": [0.42, 0.58]},
    "right":       {"screen_position": "right", "x_center_frac": [0.56, 0.76]},
}
UI_STYLES = {
    "glass":      "premium dark glass",
    "glassmorphism": "premium dark glass",
    "dark glass": "premium dark glass",
    "premium":    "premium dark glass",
    "clean":      "clean minimal light",
    "minimal":    "clean minimal light",
}


@dataclass
class ArtDirection:
    hierarchy: str = "hero_subject_and_ui"
    subject_style_hint: str = ""
    lighting_mood: str = "cinematic"
    palette: str = "cool_cyan_accents"
    environment_density: str = "moderate"
    ui_placement: str = "right"
    needs_blender: bool = False
    tool_routes: List[str] = field(default_factory=lambda: [
        "vision_evaluator", "unreal_runtime"])
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hierarchy": self.hierarchy,
            "subject_style_hint": self.subject_style_hint,
            "lighting_mood": self.lighting_mood,
            "palette": self.palette,
            "environment_density": self.environment_density,
            "ui_placement": self.ui_placement,
            "needs_blender": self.needs_blender,
            "tool_routes": list(self.tool_routes),
            "notes": list(self.notes),
        }


def _has(text: str, *words: str) -> bool:
    t = " " + text.lower().strip() + " "
    return any((" " + w + " ") in t or w in text.lower() for w in words)


def parse_intent(
    prompt: str,
    ref_image: Optional[str] = None,
    vision: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Natural-language visual request -> measurable VisualTarget dict.

    The returned target never contains raw technical parameters (no cameras,
    intensities, sizes). It only contains goals that adapters can translate.
    """
    p = (prompt or "").lower()
    target: Dict[str, Any] = {
        "subject": {
            "type": "hero_character" if not _has(p, "scene", "room", "product",
                                                 "menu", "interface", "cinematic environment")
                    else "scene",
            "importance": "hero",
            "screen_position": "left_center",
            "target_screen_coverage": [0.22, 0.50],
            "head_fully_visible": True,
            "upper_body_visible": True,
            "max_head_top_frac": 0.07,
        },
        "environment": {
            "style": "premium cinematic futuristic interior",
            "depth": "medium",
            "brightness": "medium_dark",
            "complexity": "moderate",
        },
        "lighting": {
            "style": "cinematic",
            "subject_separation": True,
            "highlight_clipping_max": 0.08,
            "shadow_crush_max": 0.12,
        },
        "ui": {
            "placement": "right",
            "screen_coverage": [0.20, 0.45],
            "readable": True,
            "style": "premium dark glass",
            "required_elements": ["title", "status", "history", "input", "send"],
        },
        "composition": {
            "balanced": True,
            "hero_subject": True,
            "visual_hierarchy": True,
        },
        "intent": {"raw_prompt": prompt},
    }

    # --- mood/style traits
    for mood_words, mood_name in ((("cinematic",), "cinematic"),
                                  (("premium",), "premium"),
                                  (("futuristic",), "futuristic"),
                                  (("luxury", "luxurious"), "luxury"),
                                  (("realistic",), "realistic"),
                                  (("cozy", "cosy"), "cozy"),
                                  (("minimal",), "minimal"),
                                  (("clean",), "clean"),
                                  (("immersive",), "immersive"),
                                  (("dramatic",), "dramatic"),
                                  (("aaa", "a a a"), "aaa"),
                                  (("dark",), "dark"),
                                  (("bright",), "bright")):
        if any(w in p for w in mood_words):
            target["mood"] = mood_name
            break
    mood = target.get("mood", "cinematic")
    if _has(p, "cinematic", "premium") and _has(p, "futuristic"):
        mood = "cinematic premium"
    traits = MOODS.get(mood, MOODS["cinematic"])
    for k, v in traits.items():
        target["environment"].setdefault(k, v)
        target["lighting"].setdefault(k if k != "brightness" else "mood_brightness", v)
    target["mood_traits"] = traits

    # premium/cinematic moods get a tighter clipping budget (softer highlights)
    clip_budgets = {
        "cinematic": (0.05, 0.10), "premium": (0.05, 0.10),
        "cinematic premium": (0.05, 0.10), "futuristic": (0.06, 0.10),
        "luxury": (0.06, 0.10), "dramatic": (0.05, 0.10),
        "cozy": (0.07, 0.12), "realistic": (0.07, 0.12),
    }
    hm, sm = clip_budgets.get(mood, (0.08, 0.12))
    target["lighting"]["highlight_clipping_max"] = hm
    target["lighting"]["shadow_crush_max"] = sm

    # --- shot / framing
    for shot_words, shot_name in (("hero shot", "hero shot"), ("hero", "hero"),
                                  ("close-up", "close-up"), ("close up", "close-up"),
                                  ("wide shot", "wide shot"), ("wide", "wide shot"),
                                  ("portrait", "portrait"),
                                  ("three-quarter", "three-quarter"),
                                  ("three quarter", "three-quarter")):
        if shot_words in p:
            target["shot"] = shot_name
            for k, v in SHOTS[shot_name].items():
                if k == "subject_screen_coverage":
                    target["subject"]["target_screen_coverage"] = v
                else:
                    target["subject"].setdefault(k, v)
            break
    if _has(p, "on camera", "look good on camera", "on-screen", "on screen"):
        target["subject"]["importance"] = "hero"
        target["subject"]["head_fully_visible"] = True

    # --- females / humans
    for kw in ("female", "woman", "girl", "her", "she", "ai assistant",
               "ai avatar", "presenter", "human"):
        if kw.lower() in p:
            if any(w in p for w in ("female", "woman", "girl", "her", "she")):
                target["subject"]["type"] = "female_ai_avatar" if (
                    "ai" in p or "avatar" in p or "assistant" in p) else "female_character"
            elif "ai assistant" in p or "ai avatar" in p or "assistant" in p:
                target["subject"]["type"] = "ai_avatar"
            break
    # realistic humans -> photoreal character pipeline (or external source)
    if "realistic" in p and any(w in p for w in (
            "human", "person", "character", "presenter", "people",
            "woman", "man", "avatar")):
        st = target["subject"]["type"]
        if not (st.startswith("female") or st.startswith("ai")):
            target["subject"]["type"] = "realistic_human"

    # --- environment words
    if _has(p, "room", "interior", "studio", "facility"):
        target["environment"]["style"] = "premium cinematic futuristic interior"
        target["environment"]["complexity"] = "moderate"
    if _has(p, "environment", "background", "set"):
        target["environment"]["depth"] = "high"
    if _has(p, "expensive", "high-end", "finished product", "premium"):
        # keep a richer descriptor when one already exists
        if target["environment"]["style"] == "premium cinematic futuristic interior":
            pass
        else:
            target["environment"]["style"] = "premium"
        target["lighting"]["style"] = "premium cinematic"

    # --- UI terms
    if _has(p, "chat", "ui", "interface", "screen", "hud"):
        target["ui"]["present"] = True
    if _has(p, "glass") or _has(p, "glassmorphism"):
        target["ui"]["style"] = "premium dark glass"
    if _has(p, "live", "real", "working", "local"):
        target["ui"].setdefault("live_chat", True)

    # --- explicit placement words ("on the left", "UI on the right"...)
    if " left" in (" " + p):
        target["subject"]["screen_position"] = "left"
        if target["ui"].get("present") and any(w in p for w in
                                               ("ui", "interface", "panel")):
            target["ui"]["placement"] = "left"
    if " right" in (" " + p) and target["ui"].get("present") and any(
            w in p for w in ("ui", "interface", "panel", "chat")):
        target["ui"]["placement"] = "right"

    # --- reference image overrides
    if ref_image:
        spec = reference_spec(ref_image, vision=vision)
        target["reference"] = spec

    # --- art direction
    target["art_direction"] = art_direct(target).to_dict()
    return target


# --------------------------------------------------------------------------
# Reference image -> spec / acceptance target
# --------------------------------------------------------------------------

REFERENCE_PROMPT = (
    'Analyze this image as a visual reference for an Unreal-generated scene. '
    'Return JSON only: {"composition": "hero|balanced|centered|rule_of_thirds", '
    '"subject_position": "left|center|right|left_center", '
    '"subject_coverage": 0.0-1.0, "subject_type": "...", '
    '"ui_position": "none|left|right|bottom|top", "ui_coverage": 0.0-1.0, '
    '"palette": "...", "lighting_style": "...", "background_depth": "low|medium|high", '
    '"contrast": "low|medium|high", "brightness": "dark|moody|balanced|bright|blown", '
    '"major_geometry": "...", "visual_hierarchy": "..."}'
)


def reference_spec(
    image_path: str,
    vision: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Turn a reference image into a VisualReferenceSpec used as acceptance
    target. `vision` is an injected multimodal callable(path)->structured JSON
    dict (or raw text to best-effort parse). Falls back to safe defaults when
    no vision backend is available."""
    if not image_path or not os.path.isfile(image_path):
        return {"unavailable": True}
    default = {
        "composition": "balanced",
        "subject_position": "left_center",
        "subject_coverage": 0.35,
        "subject_type": "",
        "ui_position": "right",
        "ui_coverage": 0.30,
        "palette": "",
        "lighting_style": "cinematic",
        "background_depth": "high",
        "contrast": "medium",
        "brightness": "moody",
        "major_geometry": "",
        "visual_hierarchy": "hero subject + ui panel",
    }
    if vision is None:
        return {**default, "method": "defaults"}
    try:
        out = vision(image_path) or {}
        if isinstance(out, str):
            txt = out.strip()
            start, end = txt.find("{"), txt.rfind("}")
            if start >= 0 and end > start:
                out = json.loads(txt[start:end + 1])
            else:
                return {**default, "method": "vision_text_unparsed", "text": txt[:200]}
        spec = dict(default)
        for k in default:
            if out.get(k) is not None:
                spec[k] = out[k]
        spec["method"] = "vision"
        if spec.get("ui_position") == "right":
            spec["ui_position_frac"] = [0.6, 0.99]
        return spec
    except Exception as exc:  # pragma: no cover
        return {**default, "method": "error", "error": str(exc)[:120]}


# --------------------------------------------------------------------------
# Art director
# --------------------------------------------------------------------------

def art_direct(target: Dict[str, Any]) -> ArtDirection:
    """Decide visual hierarchy, palette, asset needs and tool routing from a
    VisualTarget. Pure logic — the user never makes these decisions."""
    d = ArtDirection()
    subject = target.get("subject") or {}
    ui = target.get("ui") or {}
    env = target.get("environment") or {}
    traits = target.get("mood_traits") or {}

    st = str(subject.get("type", ""))
    d.subject_style_hint = st
    d.lighting_mood = str(target.get("lighting", {}).get("style", "cinematic"))
    if str(traits.get("accent")) == "cyan" or "futuristic" in str(env.get("style")):
        d.palette = "cool_cyan_accents"
    elif str(traits.get("palette_hint")) == "warm":
        d.palette = "warm_neutral"
    else:
        d.palette = "cool_cyan_accents"

    d.environment_density = str(env.get("complexity", "moderate"))
    if ui.get("present"):
        d.ui_placement = str(ui.get("placement", "right"))
        d.hierarchy = "hero_subject_and_ui"
    else:
        d.hierarchy = "hero_subject"

    if "realistic" in st or "realistic" in str(subject.get("type", "")) \
            or str(subject.get("type")) == "realistic_human":
        d.needs_blender = True
        d.tool_routes = ["blender_agent", "vision_evaluator", "unreal_runtime"]
        d.notes.append("realistic human requested: character asset pipeline "
                       "required (or external photoreal source)")
    elif str(env.get("complexity")) == "high" or "max" in str(traits.get("quality", "")):
        d.needs_blender = True
        d.tool_routes = ["blender_agent", "unreal_runtime", "vision_evaluator"]
        d.notes.append("high complexity environment: Blender procedural "
                       "geometry recommended")
    if ui.get("live_chat"):
        d.tool_routes.append("ollama")
    return d


# --------------------------------------------------------------------------
# Defect -> action
# --------------------------------------------------------------------------

DEFECT_ACTIONS: Dict[str, str] = {
    "HEAD_CROPPED": "camera_framing_recompute",
    "SUBJECT_TOO_LARGE": "camera_pull_back",
    "SUBJECT_TOO_SMALL": "camera_move_closer",
    "BACKGROUND_OVEREXPOSED": "lighting_reduce_background",
    "SUBJECT_TOO_DARK": "lighting_raise_key",
    "WHITE_CLIPPING": "exposure_reduce_highlights",
    "BLACK_CLIPPING": "exposure_raise_blacks",
    "UI_TOO_SMALL": "ui_scale_up",
    "UI_LOW_CONTRAST": "ui_raise_contrast",
    "UI_OFF_SCREEN": "ui_relayout_runtime",
    "BLACK_BAND": "viewport_aspect_fix",
    "STALE_CAPTURE": "capture_force_fresh",
    "EMPTY_ENVIRONMENT": "environment_add_depth",
    "CHEAP_PRIMITIVE_LOOK": "blender_or_materials_upgrade",
    "CAMERA_ROLL": "camera_roll_reset",
}


def defect_to_action(defect: str) -> str:
    key = str(defect).split(":")[0].strip().upper()
    return DEFECT_ACTIONS.get(key, key)


CHANGED_STRATEGY: Dict[str, Callable[[float, float], float]] = {}


@dataclass
class IterationRecord:
    index: int
    problem: str
    hypothesis: str
    change: str
    before: Dict[str, float]
    after: Dict[str, float]
    result: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "problem": self.problem,
            "hypothesis": self.hypothesis,
            "change": self.change,
            "before": self.before,
            "after": self.after,
            "result": self.result,
        }


def choose_bounded_delta(action: str, magnitude: float = 0.5,
                         direction_sign: int = 1) -> float:
    """Return a bounded multiplier for an action (e.g. camera distance):
    never more than one 'step' at a time so iteration converges without
    random value shuffling."""
    step = max(0.08, min(0.45, abs(magnitude) * 0.6))
    return round(1.0 + direction_sign * step, 3)


# --------------------------------------------------------------------------
# Self critique
# --------------------------------------------------------------------------

def self_critique(
    captured_path: str,
    metrics: Any,
    score: Any,
    vision_review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evidence-based pre-delivery critique: 'if this were the finished
    product, does it match the request?'. Never language-only."""
    issues = list(metrics.issues)
    vision_issues = [str(i) for i in (vision_review or {}).get("issues", [])]
    problems = issues + [
        f"vision: {i}" for i in vision_issues if "low" not in i.lower()
    ]
    verdict = "ACCEPT" if (
        score.overall >= 8.0
        and not metrics.head_clipped
        and not metrics.stale
        and not metrics.bands
        and (vision_review is None or vision_review.get("pass") is not False)
    ) else "REVISE"
    return {
        "verdict": verdict,
        "overall": round(score.overall, 2),
        "problems": problems[:8],
        "path": captured_path,
        "evidence": {
            "head_clipped": metrics.head_clipped,
            "stale": metrics.stale,
            "bands": metrics.bands,
            "white_clip": metrics.pct_white,
            "black_clip": metrics.pct_black,
            "subject_coverage": metrics.subject_coverage,
            "ui_coverage": metrics.ui_screen_coverage,
        },
    }