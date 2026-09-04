"""Regression tests for the generic UI-panel detector's structural gate.

Reported defect: a dark dawn sky (a smooth gradient / silhouette region on
the right side of the frame) was detected as a dark UI panel because the old
detector only tested low luminance.  Step-9 received 8.66 partly from that
false bonus; a later equivalent scene scored ~7.64 with UI 8->2 and
readability 5->2.

The corrected ``find_ui_bbox`` requires structural/spatial evidence beyond
low luminance: local contrast against the scene the overlay would cover,
crisp top/bottom slab boundaries, and a crisp left boundary or viewport-edge
anchoring.  These tests pin the contract:

  * sky cannot count as UI (dark gradient sky, silhouette dawn, bright sky),
  * a genuine panel is still found,
  * lighting/time-of-day does not materially change the UI score,
  * the scorer grants no UI/readability bonus without a real panel.

Fully offline: Pillow synthetic frames only, no editor, no network.
"""
from __future__ import annotations

import os

import pytest
from PIL import Image, ImageDraw

from core.visual_acceptance import find_ui_bbox, measure, score
from tests.img_helpers import make_scene, save_scene

W, H = 900, 500


def _bright_sky() -> Image.Image:
    """Uniformly bright gradient sky — nothing remotely panel-like."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for x in range(W):
        t = x / max(W - 1, 1)
        v = int(200 + 40 * t)
        d.line([(x, 0), (x, H)], fill=(v, v, v))
    return img


def _dark_sky() -> Image.Image:
    """Full-frame dusk gradient: dark at the top, brighter horizon at the
    bottom.  The right band is dark yet has no panel structure at all."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        v = int(25 + (110 - 25) * (y / max(H - 1, 1)))
        d.line([(0, y), (W, y)], fill=(v, v, v))
    return img


def _silhouette_dawn() -> Image.Image:
    """The structure of the reported false positive: a bright scene with a
    crisp-edged dark silhouette on the top-right that fades into the ground
    (no crisp top/bottom slab boundary) and is surrounded by brighter sky —
    dark, but clearly not an overlay panel."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for x in range(W):
        t = x / max(W - 1, 1)
        v = int(120 + 60 * t)
        d.line([(x, 0), (x, H)], fill=(v, v, v))
    d.rectangle([0, int(H * 0.85), W, H], fill=(180, 180, 180))
    bx0, bx1 = int(W * 0.60), int(W * 0.76)
    top, bottom = int(H * 0.04), int(H * 0.35)
    for x in range(bx0, bx1):
        for y in range(top, bottom):
            f = (y - top) / max(1, bottom - top)
            fade = 1.0 if f < 0.7 else 1.0 - (f - 0.7) / 0.3
            bg = 120 + 60 * (x / max(W - 1, 1))
            v = int(6 * fade + bg * (1.0 - fade))
            d.point((x, y), fill=(v, v, v))
    return img


def _darken_scene(img: Image.Image, k: float) -> Image.Image:
    """Scale the scene by ``k`` while keeping the emissive UI panel fill
    constant — simulates the same composition at a different time of day."""
    px = img.load()
    out = Image.new("RGB", img.size)
    op = out.load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            r, g, b = px[x, y]
            if 35 <= r <= 45 and 35 <= g <= 45 and 40 <= b <= 50:
                op[x, y] = (r, g, b)
            else:
                op[x, y] = (int(r * k), int(g * k), int(b * k))
    return out


def _save(tmp_path, name, img) -> str:
    p = tmp_path / f"{name}.png"
    img.save(str(p))
    return str(p)


# --------------------------------------------------------------------------
# sky / environment can never count as UI
# --------------------------------------------------------------------------

def test_dark_sky_is_not_ui(tmp_path):
    assert find_ui_bbox(_dark_sky()) is None
    m = measure(_save(tmp_path, "dark_sky", _dark_sky()))
    assert m.ui_bbox is None
    s = score(m)
    assert s.ui <= 2.0            # no dark-region bonus
    assert s.readability <= 2.0   # readability bonus requires a real panel


def test_silhouette_dawn_is_not_ui(tmp_path):
    """The exact failure shape: crisp left edge + fading bottom + floating in
    the frame.  It is dark but has no crisp top/bottom slab boundaries."""
    assert find_ui_bbox(_silhouette_dawn()) is None
    m = measure(_save(tmp_path, "sil_dawn", _silhouette_dawn()))
    assert m.ui_bbox is None
    s = score(m)
    assert s.ui <= 2.0
    assert s.readability <= 2.0


def test_bright_sky_is_not_ui(tmp_path):
    assert find_ui_bbox(_bright_sky()) is None
    m = measure(_save(tmp_path, "bright_sky", _bright_sky()))
    assert m.ui_bbox is None


# --------------------------------------------------------------------------
# a genuine panel still works
# --------------------------------------------------------------------------

def test_genuine_panel_still_detected(tmp_path):
    bbox = find_ui_bbox(make_scene())
    assert bbox is not None
    w, h = make_scene().size
    assert bbox[0] >= w * 0.50          # panel on the right band
    assert bbox[2] >= w * 0.80          # and it spans most of the band
    m = measure(save_scene(tmp_path, "panel.png"), {
        "ui": {"placement": "right", "screen_coverage": [0.20, 0.45]},
    })
    assert m.ui_bbox is not None
    assert 0.20 <= m.ui_screen_coverage <= 0.45


def test_default_ui_scan_still_finds_panel(tmp_path):
    """Generic measurement (no injected locator) must keep finding the
    synthetic dark-glass panel — the documented default path."""
    m = measure(save_scene(tmp_path, "panel_generic.png"))
    assert m.ui_bbox is not None
    assert m.ui_bbox[0] >= m.width * 0.5


def test_locator_pins_ui_region(tmp_path):
    """scene_locators' dark_panel_ui_locator delegates to the same corrected
    scan, so a mission that pins the right band keeps its contract."""
    from core.scene_locators import dark_panel_ui_locator
    bbox = dark_panel_ui_locator(dark_threshold=70)(make_scene())
    assert bbox is not None
    assert bbox[0] >= make_scene().size[0] * 0.55


# --------------------------------------------------------------------------
# time-of-day stability
# --------------------------------------------------------------------------

def test_time_of_day_does_not_change_ui_score(tmp_path):
    """The same composition at bright day vs dusk (scene dimmed, emissive
    panel constant) must be detected either way with the same UI score."""
    day = save_scene(tmp_path, "day.png")
    dusk = _save(tmp_path, "dusk", _darken_scene(make_scene(), 0.7))
    m_day = measure(day)
    m_dusk = measure(dusk)
    assert m_day.ui_bbox is not None
    assert m_dusk.ui_bbox is not None
    s_day, s_dusk = score(m_day), score(m_dusk)
    assert abs(s_day.ui - s_dusk.ui) <= 1.0


def test_sky_rejected_across_time_of_day(tmp_path):
    """A sky at two different lighting levels is never UI at either."""
    for k in (1.0, 0.6):
        img = _dark_sky()
        if k != 1.0:
            img = Image.eval(img, lambda v: int(v * k))
        assert find_ui_bbox(img) is None
        m = measure(_save(tmp_path, f"sky_{k}", img))
        assert m.ui_bbox is None
        assert score(m).ui <= 2.0