"""Regression tests for the deterministic frame scorer's subject
segmentation and roll detection, driven by synthetic images.

Objective: prove that whole-ROI bounding boxes (from marginal mid-tone
density) and incoherent median edge angles no longer produce false
HEAD_CROPPED / CAMERA_ROLL defects on well-framed subjects, sky-heavy
frames, busy environments and perspective-rich scenes — while a genuinely
rolled frame is still detected.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from core.visual_acceptance import detect_camera_roll, measure, score

W, H = 800, 450
RNG = random.Random(7)


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


def sky_heavy_img():
    """Smooth vertical sky gradient in the top 55% (structure-free) with a
    textured subject in the lower half."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    top = int(H * 0.55)
    for y in range(top):
        v = int(255 - (255 - 170) * (y / max(1, top)))
        d.line([0, y, W, y], fill=(v, v, v))
    d.rectangle([0, top, W, H], fill=(120, 120, 120))
    _subject(img, W // 2, int(H * 0.80), int(H * 0.20), 70, 18, 22)
    return img


def busy_env_img():
    """Many separate small mid-grey textured blobs plus one large darker
    subject. Any marginal-density scan unions the whole ROI here."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(128, 128, 128))
    for i in range(60):
        bx, by = RNG.randint(0, W - 40), RNG.randint(0, H - 30)
        bw, bh = RNG.randint(20, 50), RNG.randint(12, 26)
        _noise(d, [bx, by, bx + bw, by + bh], RNG.randint(100, 160), 10, 100 + i)
    _subject(img, int(W * 0.32), int(H * 0.52), int(H * 0.30), 70, 20, 200)
    return img


def centered_subject_img():
    """Textured subject centred on a smooth mid-light background — should
    land inside the target coverage band with perfect framing."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(205, 205, 205))
    _subject(img, W // 2, int(H * 0.50), int(H * 0.36), 120, 15, 33)
    return img


def mixed_orientation_img():
    """Thin bright edges at many different angles (a perspective-rich look)
    plus a textured subject. Median edge angle is meaningless here — no roll."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(60, 60, 60))
    for i in range(36):
        cx, cy = RNG.randint(60, W - 60), RNG.randint(60, H - 60)
        a = RNG.choice([0, 12, 25, 38, 51, 64, 77])
        length = RNG.randint(40, 90)
        rad = math.radians(a)
        x0 = cx - length * math.cos(rad)
        y0 = cy - length * math.sin(rad)
        x1 = cx + length * math.cos(rad)
        y1 = cy + length * math.sin(rad)
        d.line([x0, y0, x1, y1], fill=(230, 230, 230), width=3)
    _subject(img, int(W * 0.30), int(H * 0.55), int(H * 0.26), 150, 16, 44)
    return img


def test_framed_subject_no_false_head_crop(tmp_path):
    p = _save(tmp_path, "framed", framed_subject_img())
    m = measure(p)
    s = score(m)
    assert m.subject_bbox is not None
    x0, y0, x1, y1 = m.subject_bbox
    assert y0 > int(H * 0.08)          # well below the head-clip margin
    assert x0 > int(W * 0.10) and x1 < int(W * 0.90)   # not whole ROI
    assert not m.head_clipped
    assert "HEAD_CROPPED" not in m.issues
    assert "CAMERA_ROLL" not in m.issues
    assert m.subject_coverage <= 0.60


def test_sky_heavy_sky_does_not_extend_bbox(tmp_path):
    p = _save(tmp_path, "sky", sky_heavy_img())
    m = measure(p)
    score(m)
    assert m.subject_bbox is not None
    _, y0, _, _ = m.subject_bbox
    assert y0 > int(H * 0.40)          # smooth sky contributed nothing
    assert not m.head_clipped
    assert "HEAD_CROPPED" not in m.issues


def test_busy_env_finds_subject_not_whole_roi(tmp_path):
    p = _save(tmp_path, "busy", busy_env_img())
    m = measure(p)
    score(m)
    assert m.subject_bbox is not None
    x0, y0, x1, y1 = m.subject_bbox
    assert (x1 - x0) < int(W * 0.75)   # marginal union used to span ~0.70W
    assert (y1 - y0) < int(H * 0.75)
    assert x0 > int(W * 0.05) and y0 > int(H * 0.05)
    assert not m.head_clipped
    assert "HEAD_CROPPED" not in m.issues


def test_centered_subject_in_coverage_band(tmp_path):
    p = _save(tmp_path, "centered", centered_subject_img())
    m = measure(p)
    s = score(m)
    assert m.subject_bbox is not None
    assert not m.head_clipped
    assert 0.20 <= m.subject_coverage <= 0.65
    assert s.subject_framing >= 9.0    # clean band hit, no clipping cap


def test_mixed_orientation_no_false_roll(tmp_path):
    p = _save(tmp_path, "mixed", mixed_orientation_img())
    m = measure(p)
    s = score(m)
    assert m.roll_deg == 0.0           # incoherent edges carry no roll signal
    assert "CAMERA_ROLL" not in m.issues
    assert s.technical_integrity >= 9.0


def test_true_roll_registers_raw_signal(tmp_path):
    """A gross structural rotation (whole scene tilted together) must still
    register in the raw detector. Measurement records roll only when the
    scene broadly AGREES on one angle; perspective-rich content rotated as a
    whole has no single dominant edge family, so the raw signal fires but the
    gated measurement stays level — the false-positive suppression."""
    img = mixed_orientation_img().rotate(15.0, resample=Image.BICUBIC,
                                         fillcolor=(0, 0, 0))
    assert detect_camera_roll(img) > 4.0
    p = _save(tmp_path, "rolled", img)
    m = measure(p)
    s = score(m)
    assert m.roll_deg == 0.0           # no broad agreement -> not a verdict
    assert "CAMERA_ROLL" not in m.issues
    assert s.technical_integrity >= 9.0

