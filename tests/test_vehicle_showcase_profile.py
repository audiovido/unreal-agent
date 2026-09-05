"""Focused regressions for the vehicle-showcase detector and bounded loop."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from core.scene_locators import (
    VEHICLE_SHOWCASE_PROFILE,
    locators_from_profile,
)
from core.visual_director import parse_intent
from core.visual_loop import AutonomousVisualLoop


def _vehicle_frame(path: Path, *, vehicle: bool = True) -> str:
    image = Image.new("RGB", (1000, 600), (128, 132, 138))
    draw = ImageDraw.Draw(image)
    for x in range(0, 1000, 40):
        draw.line((x, 0, x, 599), fill=(105 + (x // 40) % 3 * 8, 110, 118), width=3)
    for y in range(20, 430, 35):
        draw.line((0, y, 999, y), fill=(150, 150, 155), width=2)
    # Dark floor/map mass outside the sanctioned hero band: it must not win.
    draw.rectangle((0, 430, 999, 599), fill=(32, 34, 36))
    if vehicle:
        # Body + two separated wheel silhouettes, joined by the detector's
        # bounded morphology/near-component assembly step.
        draw.rounded_rectangle((335, 180, 700, 390), radius=35,
                               fill=(25, 27, 30), outline=(90, 95, 100), width=8)
        draw.ellipse((380, 340, 475, 455), fill=(8, 9, 10))
        draw.ellipse((560, 340, 655, 455), fill=(8, 9, 10))
        draw.rectangle((430, 215, 520, 290), fill=(55, 60, 65))
        draw.rectangle((535, 215, 625, 290), fill=(55, 60, 65))
    image.save(path, format="PNG")
    return str(path)


def test_vehicle_prompt_routes_profile_and_non_destructive_policy():
    target = parse_intent("Showcase the black SUV in a premium garage scene")
    assert target["visual_profile"] == "vehicle_showcase"
    assert target["subject"]["type"] == "vehicle"
    strategy = target["visual_strategy"]
    assert strategy["allow_geometry_edits"] is False
    assert strategy["allow_scale_edits"] is False
    assert strategy["correction_order"][0] == "subject_bbox_validity"


def test_vehicle_locator_finds_assembled_vehicle_and_fails_closed(tmp_path):
    locator = locators_from_profile(VEHICLE_SHOWCASE_PROFILE)["subject_locator"]
    bbox = locator(__import__("PIL").Image.open(_vehicle_frame(tmp_path / "vehicle.png")))
    assert bbox is not None
    x0, y0, x1, y1 = bbox
    assert x0 < 360 and x1 > 650
    assert y0 < 220 and y1 > 400

    empty = locator(__import__("PIL").Image.open(
        _vehicle_frame(tmp_path / "empty.png", vehicle=False)))
    assert empty is None


def test_vehicle_loop_rolls_back_regression_before_next_strategy(tmp_path):
    frames = []
    for idx in range(3):
        path = Path(tmp_path / f"p{idx}.png")
        _vehicle_frame(path)
        # Fresh evidence must hash differently even when the visible scene is
        # unchanged; this models the live capture adapter's fresh PNG bytes.
        with path.open("ab") as fh:
            fh.write(bytes([idx + 1]))
        frames.append(str(path))
    index = {"n": 0}
    applied = []
    rolled_back = []

    # Keep the test about strategy/rollback routing rather than the full score
    # contract: measure() still reads every real PNG and the injected gate is
    # intentionally strict until the final frame.
    def capture():
        p = frames[min(index["n"], len(frames) - 1)]
        index["n"] += 1
        return p

    def apply(action, metrics, score, target, pass_index):
        applied.append(action)
        return {"note": action, "score_before": score.overall}

    def rollback(score, metrics):
        rolled_back.append(True)
        return {"ok": True, "restored": "camera"}

    target = parse_intent("Showcase the black SUV in a garage scene")
    target["subject"]["target_screen_coverage"] = [0.12, 0.20]
    target["subject"]["head_fully_visible"] = False

    class VehicleLoop(AutonomousVisualLoop):
        def _post_measure(self, metrics):
            # Keep the synthetic geometry focused on rollback routing; the
            # live adapter supplies camera read-back for roll ground truth.
            metrics.roll_deg = 0.0

    loop = VehicleLoop(
        target, capture=capture, apply=apply, rollback=rollback,
        max_passes=3, gate=lambda metrics, score: False,
        subject_locator=locators_from_profile(VEHICLE_SHOWCASE_PROFILE)["subject_locator"],
    )
    result = loop.run()
    assert result["iterations"] == 3
    assert applied == ["camera_pull_back", "camera_framing_recompute"]
    assert rolled_back == [True]
    assert result["passes"][0]["reverted"] is True
    assert result["passes"][0]["change"]["rollback"]["ok"] is True
    assert result["passes"][0]["kept"] is False
