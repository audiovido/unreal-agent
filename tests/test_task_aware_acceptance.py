"""TASK-AWARE VISUAL ACCEPTANCE — hermetic regression suite.

The acceptance contract was task-blind: ``score()`` always aggregated
ui/readability (floor 2.0 each without a panel), so a frame could never
reach the 8.5 gate unless it contained a detected UI slab — even for a
task like "Add a cube" that never asked for UI.  The product task ended
FAILED on a well-lit, cleanly framed scene purely because no UI panel was
requested.

The fix is a generic, task-aware required-category contract:

  * a VisualTarget may declare ``required_visual_categories``;
  * ``score()`` then aggregates ONLY over those categories (same fixed
    weights, renormalized) — every category value is still the honest
    measurement, nothing is fabricated for unrequested categories;
  * without the key, scoring is byte-identical to the historic behavior
    (full all-categories gate, including every Step-5/6 / UI mission).

These tests are fully hermetic: Pillow synthetic frames only.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

from core.visual_acceptance import SCORE_CATEGORIES, measure, score

# Hermetic synthetic-scene helpers (kept local so this suite is fully
# self-contained at HEAD — it must not depend on any untracked module).
W, H = 800, 450


def _noise(draw, box, base, amp, seed):
    r2 = random.Random(seed)
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            v = max(0, min(255, base + r2.randint(-amp, amp)))
            draw.point((x, y), fill=(v, v, v))


def _subject(img, cx, cy, r, base, amp, seed):
    """Textured circular subject centred at (cx, cy) with radius r."""
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(base, base, base))
    _noise(d, [cx - r + 5, cy - r + 5, cx + r - 5, cy + r - 5], base, amp, seed)
    return d


def _save(tmp_path, name, img):
    p = tmp_path / f"{name}.png"
    img.save(str(p))
    return str(p)


def framed_subject_img():
    """Textured darker subject mid-frame on a flat mid-grey background. The
    subject's top is far below the frame margin — never HEAD_CROPPED."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(150, 150, 150))
    _subject(img, W // 2, int(H * 0.55), int(H * 0.36), 90, 16, 11)
    return img

# Non-UI actor-task scope (must mirror product_core.ACTOR_TASK_CATEGORIES).
ACTOR_TASK_CATEGORIES = ["composition", "subject_framing", "lighting",
                         "environment", "technical_integrity"]
ALL_CATEGORIES = list(SCORE_CATEGORIES)
UI_REQUIRED_TARGET = {"required_visual_categories": list(ALL_CATEGORIES)}
SCENE_TARGET = {"required_visual_categories": list(ACTOR_TASK_CATEGORIES)}


def _clean_scene_no_ui(tmp_path, name="scene_plain") -> str:
    """A cleanly framed, well-lit scene with NO UI panel."""
    return _save(tmp_path, name, framed_subject_img())


def _clean_scene_with_ui_panel(tmp_path, name="scene_ui") -> str:
    """A clean, well-lit scene PLUS a genuine crisp dark UI panel on the
    right band (dark slab, bright text rows) — a real UI-overlay
    composition.  The subject sits LEFT of the slab so the panel keeps a
    crisp unoccluded edge — detectable by the committed luminance detector
    AND the structural gate (interior stays dark with sparse text rows)."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(150, 150, 150))
    _subject(img, int(W * 0.32), int(H * 0.55), int(H * 0.36), 90, 16, 11)
    d = ImageDraw.Draw(img)
    x0, x1 = int(W * 0.55), int(W * 0.99)
    y0, y1 = int(H * 0.08), int(H * 0.92)
    d.rectangle([x0, y0, x1, y1], fill=(26, 26, 30))
    for yy in range(y0 + int(H * 0.05), y1, int(H * 0.20)):
        d.rectangle([x0 + 12, yy, x1 - 12, yy + int(H * 0.02)],
                    fill=(210, 214, 220))
    return _save(tmp_path, name, img)


def _measure(p: str):
    m = measure(p)
    assert m.ok
    return m


# ---------------------------------------------------------------------------
# A / B — no-UI tasks: absence of a panel must not fail the task
# ---------------------------------------------------------------------------

def test_no_ui_frame_full_gate_is_below_acceptance(tmp_path):
    """Without the task-aware scope the old blind gate caps this clean
    frame under 8.5 (that is the exact defect being fixed)."""
    p = _clean_scene_no_ui(tmp_path)
    m = _measure(p)
    assert m.ui_bbox is None            # genuinely no UI content
    s = score(m)                        # default target: all categories
    assert s.ui <= 2.0 and s.readability <= 2.0
    assert float(s.overall) < 8.5


def test_add_cube_target_scoped_overall_passes(tmp_path):
    """The SAME frame under the actor-task scope (what 'Add a cube' really
    requires) reaches acceptance.  Components stay honest — only the
    aggregation is scoped to applicable categories."""
    p = _clean_scene_no_ui(tmp_path)
    m = _measure(p)
    assert not m.issues and not m.head_clipped
    s_plain = score(m)
    s_scoped = score(m, SCENE_TARGET)
    assert s_scoped.ui <= 2.0 and s_scoped.readability <= 2.0   # not faked
    assert s_scoped.composition == s_plain.composition          # honest
    assert s_scoped.subject_framing == s_plain.subject_framing
    assert float(s_scoped.overall) >= 8.5
    assert float(s_plain.overall) < float(s_scoped.overall)


def test_unknown_categories_ignored_in_scope(tmp_path):
    """A scope listing only unknown names falls back to the full gate (a
    future category can never silently vanish from acceptance)."""
    p = _clean_scene_no_ui(tmp_path)
    m = _measure(p)
    s = score(m, {"required_visual_categories": ["not_a_category"]})
    s_default = score(m)
    assert float(s.overall) == float(s_default.overall)


# ---------------------------------------------------------------------------
# C / D / E — UI tasks keep the strict gate
# ---------------------------------------------------------------------------

def test_ui_required_and_missing_still_fails(tmp_path):
    """A UI-required target with NO ui_bbox must still FAIL — the strict
    UI acceptance gate is preserved for tasks that ask for UI."""
    p = _clean_scene_no_ui(tmp_path)
    m = _measure(p)
    assert m.ui_bbox is None
    s = score(m, UI_REQUIRED_TARGET)
    assert float(s.overall) < 8.5
    assert s.ui <= 2.0 and s.readability <= 2.0


def test_ui_task_with_panel_passes_strict_gate(tmp_path):
    """A UI-required task whose frame DOES carry the genuine panel passes
    the full all-categories gate unchanged (no weakening of UI acceptance)."""
    p = _clean_scene_with_ui_panel(tmp_path)
    m = _measure(p)
    assert m.ui_bbox is not None
    assert not m.issues and not m.head_clipped
    s_default = score(m)
    s_full = score(m, UI_REQUIRED_TARGET)
    assert float(s_default.overall) >= 8.5          # historic gate intact
    # same categories, same weights -> same math up to float noise
    assert abs(float(s_full.overall) -
               float(s_default.overall)) < 1e-9


def test_missing_scope_key_is_historic_default(tmp_path):
    """No ``required_visual_categories`` key -> byte-identical default
    aggregation (regression guard for Step-5/6 and all existing callers)."""
    p = _clean_scene_with_ui_panel(tmp_path)
    m = _measure(p)
    a = float(score(m).overall)
    b = float(score(m, {}).overall)
    c = float(score(m, None).overall)
    assert abs(a - b) < 1e-9 and abs(b - c) < 1e-9


def test_scene_and_full_scopes_agree_on_ui_panel_frame(tmp_path):
    """A frame with a real panel satisfies BOTH the strict UI gate and the
    actor-task scope — the two contracts only differ on UI-less frames."""
    p = _clean_scene_with_ui_panel(tmp_path)
    m = _measure(p)
    assert float(score(m, SCENE_TARGET).overall) >= 8.5
    assert float(score(m, UI_REQUIRED_TARGET).overall) >= 8.5


def test_scoping_never_weakens_measured_defects(tmp_path):
    """Task-aware scoping renormalizes the aggregate only; measured defects
    and the honest low categories are untouched and still reported."""
    p = _clean_scene_no_ui(tmp_path)
    m = _measure(p)
    s = score(m, SCENE_TARGET)
    assert s.technical_integrity == score(m).technical_integrity
    assert list(m.issues) == list(measure(p).issues)


# ---------------------------------------------------------------------------
# product-core planning contract (hermetic, no bridge / no session init)
# ---------------------------------------------------------------------------

def _planner():
    import core.product_core as pc
    obj = pc.ProductSession.__new__(pc.ProductSession)
    obj.PLANNED_PATTERNS = pc.ProductSession.PLANNED_PATTERNS
    return obj


def test_plan_carries_task_aware_target_for_prop():
    plan = _planner()._plan("Add a cube named TestCube")
    assert plan.get("ok")
    assert plan.get("capability") == "add_visible_prop"
    assert (plan["visual_target"].get("required_visual_categories")
            == ACTOR_TASK_CATEGORIES)
    plan2 = _planner()._plan("Remove the actor named TestCube")
    assert plan2.get("capability") == "remove_actor"
    assert (plan2["visual_target"].get("required_visual_categories")
            == ACTOR_TASK_CATEGORIES)


def test_unplanned_ui_prompts_carry_no_visual_target():
    """Out-of-scope prompts (e.g. UI requests) fail fast in the product
    planner and carry no visual target (never silently accepted)."""
    for prompt in ("Create a premium chat interface", "Build a dashboard"):
        plan = _planner()._plan(prompt)
        assert not plan.get("ok")
        assert plan.get("visual_target") is None
