"""Deterministic tests for tools.visual.shot_quality (no editor required)."""
import io

import pytest
from PIL import Image, ImageDraw

from tools.visual.shot_quality import analyze_frame, classify_frame


def _save(img: Image.Image, tmp_path, name: str) -> str:
    p = tmp_path / name
    img.save(p, format="PNG")
    return str(p)


def _solid(color, size=(320, 180)):
    return Image.new("RGB", size, color)


def _gradient(size=(320, 180), start=(10, 10, 10), end=(245, 245, 245)):
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    w, h = size
    for x in range(w):
        t = x / max(w - 1, 1)
        c = tuple(int(start[i] + (end[i] - start[i]) * t) for i in range(3))
        draw.line([(x, 0), (x, h)], fill=c)
    return img


def _scene(size=(320, 180)):
    img = Image.new("RGB", size, (18, 16, 22))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 40, 200, 170], fill=(120, 130, 160))
    draw.rectangle([120, 20, 150, 90], fill=(235, 225, 210))
    draw.ellipse([60, 50, 110, 100], fill=(80, 90, 70))
    for x in range(0, 320, 8):
        draw.line([(x, 178), (x + 4, 170)], fill=(60, 55, 50))
    return img


def test_black_frame_is_black(tmp_path):
    v = classify_frame(_save(_solid((0, 0, 0)), tmp_path, "black.png"))
    assert v.label == "black"
    assert v.ok is False
    assert v.pct_black > 0.99


def test_white_frame_is_white(tmp_path):
    v = classify_frame(_save(_solid((255, 255, 255)), tmp_path, "white.png"))
    assert v.label == "white"
    assert v.ok is False
    assert v.pct_white > 0.99


def test_normal_scene_is_normal(tmp_path):
    v = classify_frame(_save(_scene(), tmp_path, "scene.png"))
    assert v.label == "normal"
    assert v.ok is True
    assert 15.0 < v.mean_luma < 210.0
    assert v.std_luma > 20.0


def test_gradient_has_content_and_is_normal(tmp_path):
    v = classify_frame(_save(_gradient(), tmp_path, "grad.png"))
    assert v.label == "normal"
    assert v.std_luma > 60.0


def test_underexposed_detected(tmp_path):
    v = classify_frame(_save(_scene().point(lambda p: p // 4), tmp_path, "dark.png"))
    assert v.label in ("underexposed", "black")
    assert v.ok is False


def test_overexposed_detected(tmp_path):
    img = _solid((235, 232, 228))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 280, 140], fill=(250, 250, 250))
    v = classify_frame(_save(img, tmp_path, "bright.png"))
    assert v.label in ("overexposed", "white")
    assert v.ok is False


def test_letterbox_bands_reported(tmp_path):
    img = _solid((0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 24, 319, 155], fill=(60, 70, 90))
    v = classify_frame(_save(img, tmp_path, "letterbox.png"))
    assert "top letterbox band" in v.issues
    assert "bottom letterbox band" in v.issues


def test_analyze_reports_dimensions(tmp_path):
    raw = analyze_frame(_save(_scene(size=(640, 360)), tmp_path, "size.png"))
    assert raw["width"] == 640
    assert raw["height"] == 360


def test_missing_file_is_unreadable(tmp_path):
    v = classify_frame(str(tmp_path / "missing.png"))
    assert v.label == "unreadable"
    assert v.ok is False


def test_rgb_compatible_with_grayscale_inputs(tmp_path):
    img = _scene().convert("RGB")
    v = classify_frame(_save(img, tmp_path, "rgb.png"))
    assert v.ok is True


def test_low_contrast_flagged(tmp_path):
    img = _solid((48, 48, 48))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 30, 290, 150], fill=(58, 58, 58))
    v = classify_frame(_save(img, tmp_path, "flat.png"))
    assert v.label == "low_contrast"
    assert v.ok is False