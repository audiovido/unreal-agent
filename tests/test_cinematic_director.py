"""Cinematic director — hermetic regression suite (no live Unreal).

Covers the deterministic core of the V2 cinematic pipeline:
  * brief parsing and request classification
  * shot-plan framing math (verified against camera_framing projection)
  * the seven-dimension cinematic scorecard (measured vs vision basis)
  * the bounded (<=3) quality loop — including its no-fake-PASS gate
  * full run_cinematic orchestration with an injected adapter
  * asset reuse/fix/create/blocker decisions
Pillow synthetic frames only.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from core.cinematic_assets import decide_asset_strategy
from core.cinematic_director import (
    CINEMATIC_DIMENSIONS,
    CinematicShotLoop,
    parse_cinematic_brief,
    plan_cinematic_shots,
    run_cinematic,
    score_cinematic_frame,
    is_cinematic_request,
    cinematic_target,
    verify_pose,
)
from core.cinematic_assets import catalog_reuse_shortlist


W, H = 1280, 720


def _noise(draw, box, base, amp, seed):
    import random
    r2 = random.Random(seed)
    for y in range(box[1], box[3], 2):
        for x in range(box[0], box[2], 2):
            v = max(0, min(255, base + r2.randint(-amp, amp)))
            draw.point((x, y), fill=(v, v, v))


def framed_subject_img(black=False, tiny=False):
    """Good cinematic synthetic frame: textured darker hero mid-frame on a
    flat mid-grey background, head well inside the frame (never clipped)."""
    img = Image.new("RGB", (W, H), (150, 150, 150))
    if black:
        return Image.new("RGB", (W, H), (4, 4, 4))
    d = ImageDraw.Draw(img)
    r = int(H * 0.16) if tiny else int(H * 0.34)
    cy = int(H * 0.52)
    d.ellipse([W // 2 - r, cy - r, W // 2 + r, cy + r], fill=(92, 92, 92))
    _noise(d, [W // 2 - r + 5, cy - r + 5, W // 2 + r - 5, cy + r - 5],
           92, 14, 11)
    return img


def save(tmp_path, name, img):
    p = tmp_path / f"{name}.png"
    img.save(str(p))
    return str(p)


def sample_subjects(n=3):
    return [
        {"label": f"HQ_{i}", "kind": "actor",
         "location": [-80 + i * 80, -40, 0.0], "height_cm": 175.0}
        for i in range(n)
    ]


# --------------------------------------------------------------------------
# Brief parsing
# --------------------------------------------------------------------------

def test_parse_hero_cinematic_brief():
    b = parse_cinematic_brief(
        "Create a 10-second cinematic hero shot of the AividoHQ team with "
        "premium lighting and smooth camera movement at 30 fps 1920x1080")
    assert b["duration_s"] == 10.0
    assert b["fps"] == 30
    assert b["resolution"] == [1920, 1080]
    assert b["premium"] is True
    assert "aividohq" in " ".join(b["subjects"]).lower()
    assert b["motion"] and any("camera" in m or "smooth" in m
                               for m in b["motion"])
    assert b["lighting_requested"] is True


def test_parse_4k_and_defaults():
    b = parse_cinematic_brief("wide shot of a vehicle, 4k")
    assert b["resolution"] == [3840, 2160]
    assert b["shot"] == "wide shot"
    assert b["duration_s"] == 8.0
    assert b["fps"] == 30


def test_is_cinematic_request_gate():
    assert is_cinematic_request(
        "Create a 10-second cinematic hero shot with smooth camera")
    assert not is_cinematic_request("spawn a cube at the origin")


# --------------------------------------------------------------------------
# Shot plan + framing math
# --------------------------------------------------------------------------

def test_plan_single_hero_shot_frames_subject():
    brief = parse_cinematic_brief("hero shot of the AividoHQ team, 6 seconds")
    plan = plan_cinematic_shots(brief, sample_subjects())
    assert plan["ok"] is True
    shots = plan["shots"]
    assert len(shots) == 1          # 6 s -> single cut
    pose = shots[0]["pose"]
    subj = plan["subject"]
    # verify the group head point is projected on-screen
    head = (subj["location"][0], subj["location"][1], subj["location"][2])
    v = verify_pose(pose, {"head": head}, aspect=1.78)
    assert v["ok"] is True
    proj = v["points"]["head"]
    assert proj is not None
    assert abs(proj[0]) <= 1.0 and -0.6 <= proj[1] <= 1.0
    assert plan["note"]  # engine keyframing caveat is recorded


def test_plan_long_cinematic_uses_cuts_and_varies_yaw():
    brief = parse_cinematic_brief(
        "10-second cinematic hero shot of the AividoHQ team")
    plan = plan_cinematic_shots(brief, sample_subjects())
    shots = plan["shots"]
    assert 2 <= len(shots) <= 3
    yaws = {round(s["pose"]["yaw"], 1) for s in shots}
    assert len(yaws) > 1            # directed camera arc, not one static pose
    total = sum(s["end_s"] - s["start_s"] for s in shots)
    assert abs(total - 10.0) < 1e-6


def test_plan_no_subjects_is_blocked():
    plan = plan_cinematic_shots(parse_cinematic_brief("hero shot"), [])
    assert plan["ok"] is False


# --------------------------------------------------------------------------
# Scorecard
# --------------------------------------------------------------------------

def _good_target(tmp_path):
    brief = parse_cinematic_brief("hero shot of the team, 8 seconds")
    plan = plan_cinematic_shots(brief, sample_subjects())
    return cinematic_target(brief, plan), save(tmp_path, "good",
                                               framed_subject_img())


def test_scorecard_good_frame_measured_dims_pass(tmp_path):
    target, path = _good_target(tmp_path)
    sc = score_cinematic_frame(path, target)
    assert sc["ok"] is True
    for dim in ("composition", "framing", "lighting", "subject_visibility"):
        e = sc["dimensions"][dim]
        assert e["basis"] == "measured"
        assert e["value"] is not None
    # vision-only dims are never invented without evidence
    for dim in ("material_readability", "cinematic_depth", "visual_polish"):
        e = sc["dimensions"][dim]
        assert e["basis"] == "vision_unavailable"
        assert e["value"] is None
    assert sc["overall_basis"] == "measured_dimensions"
    assert sc["overall"] >= 8.0
    assert not sc["issues"]


def test_scorecard_vision_review_contributes_only_with_evidence(tmp_path):
    target, path = _good_target(tmp_path)
    review = {"score": 9.0, "pass": True, "model": "hermetic_fake",
              "issues": ["slight depth separation could be stronger"]}
    sc_plain = score_cinematic_frame(path, target)
    sc = score_cinematic_frame(path, target, vision=review)
    for dim in ("material_readability", "cinematic_depth", "visual_polish"):
        e = sc["dimensions"][dim]
        assert e["basis"] == "vision"
        assert e["value"] is not None
        assert e["model"] == "hermetic_fake"
    # measured dims are unchanged by the vision panel, but the overall is
    # blended at the same 0.35 weight V1 uses (vision evidence only)
    assert sc_plain["overall_basis"] == "measured_dimensions"
    assert sc["overall_basis"] == "blended_measured_vision"
    for dim in ("composition", "framing", "lighting"):
        assert sc["dimensions"][dim]["value"] == sc_plain["dimensions"][dim]["value"]
    assert sc["overall"] >= sc_plain["overall"]
    assert sc["overall"] >= 8.0   # premium vision evidence supports the gate


def test_scorecard_black_frame_never_passes(tmp_path):
    brief = parse_cinematic_brief("hero shot, 8 seconds")
    plan = plan_cinematic_shots(brief, sample_subjects())
    target = cinematic_target(brief, plan)
    path = save(tmp_path, "black", framed_subject_img(black=True))
    sc = score_cinematic_frame(path, target)
    assert sc["dimensions"]["lighting"]["value"] < 6.0
    assert sc["overall"] < 8.0
    assert sc["issues"]


# --------------------------------------------------------------------------
# Bounded quality loop
# --------------------------------------------------------------------------

class _FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.n = 0

    def __call__(self, shot):
        path = self.frames[min(self.n, len(self.frames) - 1)]
        self.n += 1
        return {"ok": True, "path": path}


class _FakeApply:
    def __init__(self):
        self.calls = []

    def __call__(self, action, metrics, scorecard, target, pass_index):
        self.calls.append(action)
        return {"note": f"applied {action} (fake)"}


def _loop(tmp_path, frames):
    brief = parse_cinematic_brief("hero shot of the team, 8 seconds")
    plan = plan_cinematic_shots(brief, sample_subjects())
    target = cinematic_target(brief, plan)
    loop = CinematicShotLoop(target, _FakeCapture(frames), _FakeApply())
    return loop.run(plan["shots"][0])


def test_quality_loop_passes_on_clean_frame(tmp_path):
    good = save(tmp_path, "g", framed_subject_img())
    out = _loop(tmp_path, [good])
    assert out["ok"] is True
    assert out["status"] == "PASS"
    assert out["iterations"] == 1


def test_quality_loop_is_bounded_and_never_fakes_pass(tmp_path):
    good = save(tmp_path, "g2", framed_subject_img())
    black = save(tmp_path, "b2", framed_subject_img(black=True))
    out = _loop(tmp_path, [black] * 5)
    assert out["ok"] is False
    assert out["status"] == "REVISE_MAXED"
    assert out["iterations"] <= 3          # bounded by the V2 contract
    assert out["final_scorecard"]["overall"] < 8.0


def test_quality_loop_recovers_on_second_capture(tmp_path):
    good = save(tmp_path, "g3", framed_subject_img())
    black = save(tmp_path, "b3", framed_subject_img(black=True))
    out = _loop(tmp_path, [black, good])
    assert out["iterations"] == 2


# --------------------------------------------------------------------------
# run_cinematic orchestration
# --------------------------------------------------------------------------

class FakeCinematicAdapter:
    """Deterministic CinematicAdapter used for hermetic orchestration."""

    def __init__(self, tmp_path, good=True):
        self.tmp = tmp_path
        self.good = good
        self.rendered = None
        self.capture_count = 0

    def inspect_subjects(self, brief):
        return sample_subjects(3)

    def blender_if_needed(self, plan):
        return {"decision": "reuse", "blender_used": False,
                "reason": "existing AividoHQ cast reused (hermetic)"}

    def place_camera(self, shot):
        return {"ok": True, "camera": f"AVCam_{shot['index']}"}

    def aim_viewport(self, shot):
        return {"ok": True}

    def capture(self, shot, out_path):
        self.capture_count += 1
        frame = framed_subject_img(black=not self.good)
        frame.save(out_path)
        return {"ok": True, "path": out_path}

    def apply_fix(self, action, metrics, scorecard, target, pass_index):
        return {"note": f"fake {action}"}

    def render(self, brief, shots, out_dir):
        import os
        os.makedirs(out_dir, exist_ok=True)
        frames = []
        for s in shots:
            p = os.path.join(out_dir, f"frame_{s['index']}.png")
            framed_subject_img().save(p)
            frames.append(p)
        self.rendered = {"ok": True, "renderer": "hermetic_fake",
                         "frames": frames, "frame_count": len(frames),
                         "video": {"status": "done", "path": "fake.mp4"}}
        return self.rendered


def test_run_cinematic_complete_with_proof(tmp_path):
    adapter = FakeCinematicAdapter(tmp_path, good=True)
    out = run_cinematic(
        "Create a 10-second cinematic hero shot of the AividoHQ team with "
        "premium lighting and smooth camera movement",
        adapter, str(tmp_path))
    assert out["status"] == "COMPLETE"
    assert out["critical"] == []
    assert out["scorecard"]["overall"] >= 8.0
    assert out["video"]["ok"] is True
    assert out["video"]["frames"]
    assert out["asset_decision"]["decision"] == "reuse"
    assert out["shots"] and all(s["ok"] for s in out["shots"])


def test_run_cinematic_blocked_when_no_shot_passes(tmp_path):
    adapter = FakeCinematicAdapter(tmp_path, good=False)
    out = run_cinematic("hero shot of the team", adapter, str(tmp_path))
    assert out["status"] == "BLOCKED"
    assert out["blockers"]                    # never a fake PASS
    assert out["cinematic_v1_ready"] is False


def test_run_cinematic_unconfigured_adapter_is_truthful(tmp_path):
    class NeverAdapter:
        def inspect_subjects(self, brief):
            raise NotImplementedError("live adapter not configured")

    out = run_cinematic("hero shot", NeverAdapter(), str(tmp_path))
    assert out["status"] == "BLOCKED"
    assert "live adapter not configured" in out["blockers"]


# --------------------------------------------------------------------------
# Asset decisions (reuse -> fix -> create -> blocked)
# --------------------------------------------------------------------------

def _catalog(validation="valid", asset_id="black_suv", path="C:/a/black.fbx"):
    return [{"id": asset_id, "name": "Black SUV", "validation_status": validation,
             "path": path, "category": "Vehicles"}]


def test_asset_reuse_when_valid_and_ranked():
    out = decide_asset_strategy("vehicle", _catalog(), scores={"black_suv": 0.9})
    assert out["decision"] == "reuse"
    assert out["fast_path"] is True and out["blender_used"] is False
    assert out["asset_id"] == "black_suv"


def test_asset_fix_via_blender_when_below_reuse_bar():
    out = decide_asset_strategy("black suv", _catalog(validation="indexed"))
    assert out["decision"] == "fix_via_blender"
    assert out["blender_used"] is True
    assert out["blender_operation"] == "prepare_asset"
    assert out["source"].endswith("black.fbx")


def test_asset_create_via_blender_for_bounded_shape():
    out = decide_asset_strategy("crate", [])
    assert out["decision"] == "create_via_blender"
    assert out["blender_params"]["shape"] == "crate"


def test_asset_blocked_without_source_or_bounded_shape():
    out = decide_asset_strategy("helicopter", [])
    assert out["decision"] == "blocked"
    assert out["blocked"] == "ASSET_SOURCE_REQUIRED"
    assert "external source required" in out["reason"]


def test_reuse_shortlist_ranked_and_trimmed():
    rows = _catalog(asset_id="a") + _catalog(asset_id="b") + [
        {"id": "c", "name": "C", "validation_status": "valid", "path": "x"}]
    sl = catalog_reuse_shortlist(rows, scores={"b": 1.0, "a": 0.5, "c": 0.1},
                                 top_n=2)
    assert [r["id"] for r in sl] == ["b", "a"]


# --------------------------------------------------------------------------
# Dimensions contract
# --------------------------------------------------------------------------

def test_seven_cinematic_dimensions_present_in_scorecard(tmp_path):
    target, path = _good_target(tmp_path)
    sc = score_cinematic_frame(path, target)
    assert list(sc["dimensions"].keys()) == list(CINEMATIC_DIMENSIONS)
    assert len(CINEMATIC_DIMENSIONS) == 7
