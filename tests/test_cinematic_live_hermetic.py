"""Cinematic live adapter + MRQ driver — hermetic tests (no live Unreal).

These tests protect the truthful-contract rules of the V2 live layer with a
scripted bridge:

1. MRQ detection never assumes support; a render is BLOCKED (not faked) when
   the probe reports the subsystem absent.
2. Engine results pass through verbatim (errors are never success).
3. Emitted editor python JSON-quotes user content.
4. The live adapter is constructible and its guard logic (engine-closed
   actions, verified read-back contract) is intact without an editor.
"""

from __future__ import annotations

from tools.unreal.movie_render_queue import MovieRenderQueueDriver
from tools.unreal.cinematic_live import CinematicLiveAdapter


class ScriptedBridge:
    def __init__(self, responses=None):
        self.calls: list = []
        self.responses = list(responses or [])
        self.actor_result = {"ok": True, "location": [0.0, -500.0, 180.0]}

    def execute_python(self, code: str):
        self.calls.append(code)
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "result": {"ok": True}}

    def get_actor(self, actor_name: str):
        self.calls.append(f"get_actor:{actor_name}")
        return {"ok": True, "result": self.actor_result}

    def frame_viewport_from_actor(self, actor_name: str, distance: float = 0.0):
        self.calls.append(f"frame:{actor_name}")
        return {"ok": True, "result": {"ok": True}}


# --------------------------------------------------------------------------
# MRQ driver
# --------------------------------------------------------------------------

def test_mrq_probe_returns_structured_evidence():
    b = ScriptedBridge([{"ok": True, "result": {"supported": False,
                                                "classes_present": [],
                                                "subsystem_ok": False}}])
    probe = MovieRenderQueueDriver(b).probe()
    payload = probe.get("result") if isinstance(probe, dict) else probe
    assert payload["supported"] is False
    assert "MovieRenderQueueSubsystem" in b.calls[0]


def test_mrq_render_blocked_truthfully_when_unsupported():
    b = ScriptedBridge([{"ok": True, "result": {"supported": False,
                                                "classes_present": []}}])
    out = MovieRenderQueueDriver(b).render_sequence(
        "/Game/Cine/Seq", "C:/out", width=1920, height=1080, fps=30,
        duration_s=8.0)
    payload = out
    assert payload["ok"] is False
    assert payload["blocked"] == "movie_render_queue"
    assert "no render was faked" in payload["error"] or \
        "not faked" in payload["error"] or \
        "no render" in payload["error"].lower()
    assert len(b.calls) == 1        # probe only; render never attempted


def test_mrq_engine_error_passes_through_verbatim():
    supported = {"ok": True, "result": {"supported": True,
                                        "classes_present": ["MovieRenderQueueSubsystem"],
                                        "subsystem_ok": True}}
    engine_err = {"ok": False, "result": {"ok": False,
                                          "blocked": "movie_render_queue",
                                          "error": "allocate_new_job failed"}}
    b = ScriptedBridge([supported, engine_err])
    out = MovieRenderQueueDriver(b).render_sequence("/Game/Cine/S")
    payload = out
    assert payload["ok"] is False
    assert "allocate_new_job" in payload["error"]


def test_mrq_probe_accepts_ue58_surface(tmp_path):
    """UE 5.4+ surface (MoviePipelineQueueSubsystem / PIE executor) is
    detected as supported; a real MRQ submission path then renders frames."""
    import os
    from PIL import Image
    out_dir = str(tmp_path / "mrq")
    os.makedirs(out_dir)
    for i in range(1, 5):
        Image.new("RGB", (1920, 1080), (20 + i, 40, 60)).save(
            os.path.join(out_dir, f"{i:04d}.png"))
    supported = {"ok": True, "result": {
        "supported": True,
        "classes_present": ["MoviePipelineQueueSubsystem",
                             "MoviePipelinePIEExecutor",
                             "MoviePipelineExecutorJob",
                             "MoviePipelinePrimaryConfig",
                             "MoviePipeline"],
        "subsystem_ok": True}}
    submitted = {"ok": True, "result": {"ok": True, "submitted": True,
                                         "output_dir": out_dir}}
    b = ScriptedBridge([supported, submitted])
    out = MovieRenderQueueDriver(b).render_sequence(
        "/Game/Cine/S", out_dir, width=1920, height=1080, fps=30,
        duration_s=8.0, poll_timeout_s=5.0)
    assert out["ok"] is True
    assert out["renderer_is_mrq"] is True
    assert out["frame_count"] == 4
    assert out["resolution"] == [1920, 1080]
    assert len(b.calls) == 2        # probe + engine submission


def test_mrq_submitted_but_no_frames_is_not_faked(tmp_path):
    """A submitted MRQ job that never produces output frames is reported as
    a failed/blocked render, never as success."""
    out_dir = str(tmp_path / "empty")
    supported = {"ok": True, "result": {"supported": True,
                                        "classes_present": ["MoviePipelineQueueSubsystem"],
                                        "subsystem_ok": True}}
    submitted = {"ok": True, "result": {"ok": True, "submitted": True,
                                         "output_dir": out_dir}}
    b = ScriptedBridge([supported, submitted])
    out = MovieRenderQueueDriver(b).render_sequence(
        "/Game/Cine/S", out_dir, fps=30, duration_s=8.0,
        poll_timeout_s=2.0)
    assert out["ok"] is False
    assert out["blocked"] == "movie_render_queue"
    assert "no output frames" in out["error"]


def test_resolution_presets():
    driver = MovieRenderQueueDriver(ScriptedBridge())
    assert driver.resolution_for("4k") == [3840, 2160]
    assert driver.resolution_for("1920x1080") == [1920, 1080]
    assert driver.resolution_for([640, 360]) == [640, 360]
    assert driver.resolution_for("garbage") == [1920, 1080]


# --------------------------------------------------------------------------
# Live adapter guards
# --------------------------------------------------------------------------

def test_live_adapter_constructs_and_inspects_subjects():
    rows = [
        {"label": "HQ_Lead", "name": "HQ_Lead", "class": "SkeletalMeshActor",
         "low": "hq_lead skeletalmeshactor"},
        {"label": "DirectionalLight1", "name": "DL1",
         "class": "DirectionalLight", "low": "directionallight1"},
        {"label": "CineCameraActor0", "name": "CC0",
         "class": "CineCameraActor", "low": "cinecameraactor0"},
    ]
    b = ScriptedBridge([{"result": rows}])
    adapter = CinematicLiveAdapter(b)
    subjects = adapter.inspect_subjects({"subjects": []})
    labels = [s["label"] for s in subjects]
    assert labels == ["HQ_Lead"]         # lights/cameras excluded
    assert subjects[0]["kind"] == "actor"


def test_live_adapter_place_camera_quotes_label_and_reads_back():
    b = ScriptedBridge([{"result": {"ok": True, "spawned": True,
                                    "camera": "AVCam_Shot01",
                                    "location": [0.0, -300.0, 170.0],
                                    "rotation": [0.0, 0.0, 0.0],
                                    "focal_props": {}}}])
    adapter = CinematicLiveAdapter(b)
    out = adapter.place_camera(
        {"index": 1, "pose": {"location_x": 0.0, "location_y": -300.0,
                              "location_z": 170.0, "pitch": 0.0, "yaw": 0.0,
                              "roll": 0.0}})
    assert out["ok"] is True
    assert "CineCameraActor" in b.calls[0]
    assert adapter._current_cam_label == "AVCam_Shot01"


def test_live_adapter_unknown_fix_action_reports_engine_closed():
    b = ScriptedBridge()
    adapter = CinematicLiveAdapter(b)
    adapter._current_cam_label = "AVCam_Shot01"
    out = adapter.apply_fix("some_mystery_action", None, None, None, 1)
    assert out["engine_closed"] is True
    assert out["ok"] is False


def test_live_adapter_noop_actions_are_clearly_noop():
    b = ScriptedBridge()
    adapter = CinematicLiveAdapter(b)
    adapter._current_cam_label = "AVCam_Shot01"
    out = adapter.apply_fix("capture_force_fresh", None, None, None, 1)
    assert out["ok"] is True and out.get("noop") is True


def test_live_adapter_exposure_change_records_mutation_for_restore():
    b = ScriptedBridge([{"result": {"ok": True,
                                    "action": "exposure_adjust",
                                    "change": {"prop": "auto_exposure_bias",
                                                "before": 1.0, "after": 0.5},
                                    "readback": True}}])
    adapter = CinematicLiveAdapter(b)
    adapter._current_cam_label = "AVCam_Shot01"
    out = adapter.apply_fix("exposure_reduce_highlights", None, None, None, 1)
    assert out["ok"] is True
    assert adapter._mutations == [{"kind": "ppv",
                                  "prop": "auto_exposure_bias",
                                  "before": 1.0}]
    # restore replays a set back to 1.0
    b2 = ScriptedBridge()
    adapter2 = CinematicLiveAdapter(b2)
    adapter2._mutations = [{"kind": "ppv", "prop": "auto_exposure_bias",
                            "before": 1.0}]
    rest = adapter2.restore_scene()
    assert rest["ok"] is True
    assert rest["restored_count"] == 1
    assert "auto_exposure_bias" in b2.calls[0]


def test_live_adapter_capture_kicks_viewport_for_fresh_frame(tmp_path):
    import shutil
    src = tmp_path / "viewport_latest.png"
    dst = tmp_path / "out.png"
    # simple valid png
    from PIL import Image
    Image.new("RGB", (640, 360), (120, 120, 120)).save(str(src))

    class _CapBridge(ScriptedBridge):
        def capture_unreal_viewport(self):
            self.calls.append("capture_unreal_viewport")
            return {"ok": True, "result": {"ok": True, "path": str(src)}}

    b = _CapBridge()
    adapter = CinematicLiveAdapter(b)
    shot = {"index": 1, "pose": {"location_x": 0.0, "location_y": -400.0,
                                 "location_z": 180.0, "pitch": 0.0, "yaw": 0.0,
                                 "roll": 0.0}}
    out = adapter.capture(shot, str(dst))
    assert out["ok"] is True
    # the fresh-render contract emits a viewport camera set before capture
    assert any("set_level_viewport_camera_info" in c for c in b.calls)
    assert b.calls[-1] == "capture_unreal_viewport"
    assert dst.exists()
