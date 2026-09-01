"""Shared synthetic-image builders for the visual director/acceptance/loop
regression tests. Pillow only — no editor, no network.

The scene mirrors the production layout contract (hero subject left-center,
dark glass UI panel on the right) with a bright gradient background — exactly
the kind of scene where the generic mid-tone subject heuristic is ambiguous,
so scene-specific locators are provided here and injected through
measure()/the loop (the documented injection point)."""
from __future__ import annotations

from PIL import Image, ImageDraw


def make_scene(
    size=(900, 500),
    subject=(0.12, 0.46, 60, 360),   # (x0_frac, x1_frac, y0, y1) px
    panel=True,
    white=False,
    bands=False,
    subject_fill=(210, 205, 195),
    panel_fill=(35, 35, 45),
    bg_gradient=(60, 130),
):
    """Bright cinematic-ish synthetic frame: gradient background, light hero
    subject on the left-center, dark glass panel on the right."""
    w, h = size
    if white:
        return Image.new("RGB", size, (250, 250, 250))
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for x in range(w):
        t = x / max(w - 1, 1)
        v = int(bg_gradient[0] + (bg_gradient[1] - bg_gradient[0]) * t)
        d.line([(x, 0), (x, h)], fill=(v, v, v))
    x0, x1, y0, y1 = subject
    d.rectangle([int(w * x0), y0, int(w * x1), y1], fill=subject_fill)
    if panel:
        d.rectangle([int(w * 0.60), int(h * 0.08), int(w * 0.97), int(h * 0.90)],
                    fill=panel_fill)
    if bands:
        bh = max(1, int(h * 0.10))
        d.rectangle([0, 0, w, bh], fill=(0, 0, 0))
        d.rectangle([0, h - bh, w, h], fill=(0, 0, 0))
    return img


def hero_locator(image, min_luma=140, max_luma=250,
                 roi=(0.02, 0.05, 0.72, 0.97)):
    """Scene-specific subject blob detection for the bright test scene: the
    hero is the bright mass (>= 140 luma) inside the left-center roi."""
    from core.visual_acceptance import find_subject_bbox
    return find_subject_bbox(image, roi=list(roi), min_luma=min_luma,
                             max_luma=max_luma)


def right_panel_locator(image, dark=60, x0f=0.55, x1f=0.99, min_frac=0.4):
    """Scene-specific dark-glass panel detection: the contiguous dark region
    on the right half of the frame."""
    w, h = image.size
    gray = image.convert("L")
    px = gray.load()
    x0, x1 = int(w * x0f), int(w * x1f)
    ys = [y for y in range(0, h, 2)
          if sum(1 for x in range(x0, x1, 2) if px[x, y] < dark) /
          max(1, (x1 - x0) / 2) > min_frac]
    xs = [x for x in range(x0, x1, 2)
          if sum(1 for y in range(0, h, 2) if px[x, y] < dark) /
          max(1, h / 2) > min_frac]
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def save_scene(tmp_path, name, **kwargs) -> str:
    p = tmp_path / name
    make_scene(**kwargs).save(p, format="PNG")
    return str(p)