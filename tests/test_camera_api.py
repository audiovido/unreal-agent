"""Hermetic tests for app.camera_api (no Unreal editor required).

Exercises the pure framing math, the actor/location target resolution
against a recording fake bridge, and the three /api/unreal/* endpoints
through FastAPI TestClient: request validation, unknown-actor 404,
viewport-changed verification, fresh-proof capture with durable mirror
copy, and the frame-and-proof composition.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import camera_api  # noqa: E402
from app.camera_api import (  # noqa: E402
    compute_view,
    forward_from_rot,
    look_at_error,
    resolve_target,
)


class FakeBridge:
    """Recording bridge that answers the framing/capture snippets with
    deterministic read-backs (same style as tests/test_unreal_fix_adapter.py)."""

    def __init__(self):
        self.calls = []
        self.actors = [
            {"name": "StaticMeshActor_0", "label": "Agent_Test_Cube",
             "class": "StaticMeshActor", "origin": [0.0, 0.0, 100.0],
             "extent": [50.0, 50.0, 50.0]},
            {"name": "PointLight_9", "label": "UA_UC_Live_fc84f9",
             "class": "PointLight", "origin": [0.0, 0.0, 300.0],
             "extent": [128.0, 128.0, 128.0]},
            {"name": "StaticMeshActor_1", "label": "UA_env_stage",
             "class": "StaticMeshActor", "origin": [0.0, 0.0, 100.0],
             "extent": [100.0, 100.0, 25.0]},
            {"name": "Ground", "label": "VD_Ground",
             "class": "StaticMeshActor", "origin": [2000.0, -300.0, 0.0],
             "extent": [400000.0, 400000.0, 0.0]},
        ]
        self.camera = {"loc": [600.0, -350.0, 170.0], "rot": [0.0, -3.0, 20.0]}

    def ping(self):
        return {"ok": True, "message": "UNREAL_BRIDGE_READY"}

    def get_project_identity(self):
        return {"ok": True,
                "result": {"ok": True,
                           "project_path": "C:/tmp/Proj/Proj.uproject"}}

    def execute_python(self, code):
        self.calls.append(code)

        if "capture_active_viewport_detailed" in code:
            # simulate the native capture writing the file synchronously
            m = re.search(r"p = '([^']+)'", code)
            path = Path(m.group(1))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                path.unlink()
            path.write_bytes(b"\x89PNG" + b"\x00" * 12341)
            return {"ok": True, "result": {
                "ok": True,
                "diag": ("OK|source=LevelViewport[1]|perspective=1"
                         "|visible=1|width=1994|height=735|bytes=12345"),
                "size": 12345}}

        if "RedrawAllViewports" in code or "save_dirty_packages" in code:
            return {"ok": True, "result": {"ok": True}}

        if "set_level_viewport_camera_info" in code and \
                "get_level_viewport_camera_info" in code:
            m = re.search(r"unreal\.Vector\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)",
                          code)
            loc = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
            m = re.search(r"unreal\.Rotator\(([-\d.]+), ([-\d.]+), "
                          r"([-\d.]+)\)", code)
            rot = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
            self.camera = {"loc": loc, "rot": rot}
            return {"ok": True, "result": {
                "ok": True, "loc": loc, "rot": rot}}

        if "get_level_viewport_camera_info" in code:
            return {"ok": True,
                    "result": dict(self.camera, ok=True)}

        if "matches = [a for a in actors if a.get_name()" in code:
            m = re.search(r"a\.get_actor_label\(\) == ([^\n]+?)\n", code)
            name = re.search(r"a\.get_name\(\) == '([^']+)'", code)
            label = re.search(r"a\.get_actor_label\(\) == '([^']+)'", code)
            want = name.group(1) if name else label.group(1)
            matches = [a for a in self.actors
                       if a["name"] == want or a["label"] == want]
            if len(matches) != 1:
                return {"ok": True, "result": {
                    "ok": False,
                    "code": "NOT_FOUND" if not matches else "AMBIGUOUS",
                    "error": f"actor not found or ambiguous: {want}",
                    "matches": [a["name"] for a in matches]}}
            a = matches[0]
            return {"ok": True, "result": {
                "ok": True, "kind": "actor", "name": a["name"],
                "label": a["label"], "class": a["class"],
                "origin": a["origin"], "extent": a["extent"],
                "radius": max(a["extent"]), "selected": True}}

        if "best_score" in code:
            # location scan: mirror the production scoring (static mesh -0.5)
            m = re.search(r"unreal\.Vector\(([-\d.]+), ([-\d.]+), "
                          r"([-\d.]+)\)", code)
            loc = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
            best = None
            best_score = 1e18
            best_dist = 1e18
            for a in self.actors:
                r = max(a["extent"])
                if r > 2000.0:
                    continue
                d = sum((a["origin"][i] - loc[i]) ** 2
                        for i in range(3)) ** 0.5
                score = d - (0.5 if a["class"] == "StaticMeshActor" else 0.0)
                if score < best_score:
                    best, best_score, best_dist = a, score, d
            if best is not None and best_dist <= 1500.0:
                return {"ok": True, "result": {
                    "ok": True, "kind": "actor", "name": best["name"],
                    "label": best["label"], "class": best["class"],
                    "origin": best["origin"], "extent": best["extent"],
                    "radius": max(best["extent"]), "dist": best_dist,
                    "selected": True}}
            return {"ok": True, "result": {
                "ok": True, "kind": "point", "origin": loc,
                "extent": [250.0, 250.0, 250.0], "radius": 250.0,
                "dist": 0.0, "selected": False}}

        return {"ok": True, "result": {"ok": True}}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app import api
    camera_api.ROOT = tmp_path_factory.mktemp("root")  # redirect durable copy
    register = camera_api.register_camera_api
    register(api.app, bridge_factory=lambda: FakeBridge())
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


# --------------------------------------------------------------------------
# Pure math
# --------------------------------------------------------------------------

class TestFramingMath:
    def test_compute_view_distance_scales_with_radius(self):
        cam, rot, dist = compute_view([0.0, 0.0, 100.0], 200.0)
        assert dist == 1000.0  # radius * FILL_FACTOR
        assert rot[0] == 0.0  # roll zeroed
        # camera above the target (elevation 12 deg) and distinct from it
        assert cam[2] > 100.0
        assert sum((cam[i] - [0.0, 0.0, 100.0][i]) ** 2 for i in range(3)) \
            ** 0.5 == pytest.approx(dist, rel=0.05)

    def test_compute_view_clamps(self):
        _, _, d = compute_view([0.0, 0.0, 0.0], 1.0)      # too close
        assert d == camera_api.MIN_DISTANCE
        _, _, d = compute_view([0.0, 0.0, 0.0], 5000.0)   # too far
        assert d == camera_api.MAX_DISTANCE

    def test_look_at_error_near_zero(self):
        for target in ([0.0, 0.0, 100.0], [0.0, 0.0, 200.0],
                       [350.0, -1400.0, 420.0]):
            cam, rot, _ = compute_view(target, 50.0)
            err = look_at_error(cam, rot, target)
            assert err < 0.5, (target, err)

    def test_forward_from_rot_pure_yaw(self):
        fwd = forward_from_rot([0.0, 0.0, 90.0])
        assert fwd[0] == pytest.approx(0.0, abs=1e-9)
        assert fwd[1] == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------
# Target resolution
# --------------------------------------------------------------------------

class TestResolveTarget:
    def test_resolve_by_actor_name(self):
        bridge = FakeBridge()
        t = resolve_target(bridge, actor_name="Agent_Test_Cube")
        assert t["ok"] and t["kind"] == "actor"
        assert t["actor"]["label"] == "Agent_Test_Cube"
        assert t["target"] == [0.0, 0.0, 100.0]
        # radius is floored so distance never drops below MIN_DISTANCE
        assert t["radius"] == camera_api.MIN_DISTANCE / camera_api.FILL_FACTOR
        assert t["selected"] is True

    def test_resolve_unknown_actor_honest(self):
        bridge = FakeBridge()
        t = resolve_target(bridge, actor_name="NoSuchThing")
        assert t["ok"] is False and t["code"] == "NOT_FOUND"

    def test_resolve_location_snaps_to_cube(self):
        # near 0,0,200 the cube (radius 50) beats the lights/props tie-break
        bridge = FakeBridge()
        t = resolve_target(bridge, location=[0.0, 0.0, 200.0])
        assert t["ok"] and t["kind"] == "actor"
        assert t["actor"]["label"] == "Agent_Test_Cube"
        assert t["target"] == [0.0, 0.0, 100.0]

    def test_resolve_location_far_point_fallback(self):
        bridge = FakeBridge()
        t = resolve_target(bridge, location=[9999.0, 9999.0, 9999.0])
        assert t["ok"] and t["kind"] == "point"
        assert t["target"] == [9999.0, 9999.0, 9999.0]
        assert t["radius"] == camera_api.DEFAULT_RADIUS
        assert t["selected"] is False


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

class TestEndpoints:
    def test_frame_actor_by_name(self, client):
        r = client.post("/api/unreal/frame-actor",
                        json={"actor_name": "Agent_Test_Cube"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["kind"] == "actor"
        assert body["actor"]["label"] == "Agent_Test_Cube"
        assert body["target"] == [0.0, 0.0, 100.0]
        assert body["viewport_changed"] is True
        assert body["look_at_error_deg"] < 0.5
        assert body["camera_after"]["loc"] != [600.0, -350.0, 170.0]

    def test_frame_actor_by_location_snaps(self, client):
        r = client.post("/api/unreal/frame-actor",
                        json={"location": [0.0, 0.0, 200.0]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "actor"
        assert body["target"] == [0.0, 0.0, 100.0]

    def test_frame_actor_no_target_422(self, client):
        r = client.post("/api/unreal/frame-actor", json={})
        assert r.status_code == 422

    def test_frame_actor_unknown_404(self, client):
        r = client.post("/api/unreal/frame-actor",
                        json={"actor_name": "MissingActor"})
        assert r.status_code == 404

    def test_capture_proof_fresh_and_mirrored(self, client, tmp_path):
        camera_api.ROOT = tmp_path  # durable mirror lands in tmp
        r = client.post("/api/unreal/capture-proof", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["url"] == "/api/proof/latest"
        assert body["visible"] is True
        assert body["size"] == 12345
        captured = Path(body["path"])
        assert captured.is_file() and captured.stat().st_size == 12345
        assert body["copied_to"] is not None
        mirrored = Path(body["copied_to"])
        assert mirrored.is_file() and mirrored.stat().st_size == 12345

    def test_frame_and_proof_composes(self, client, tmp_path):
        camera_api.ROOT = tmp_path
        before = time.time()
        r = client.post("/api/unreal/frame-and-proof",
                        json={"location": [0.0, 0.0, 200.0]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["framing"]["target"] == [0.0, 0.0, 100.0]
        assert body["framing"]["look_at_error_deg"] < 0.5
        assert body["proof"]["ok"] is True
        assert body["proof"]["size"] == 12345
        assert body["proof"]["captured_at"] >= before
        assert body["url"] == "/api/proof/latest"

    def test_openapi_schema_present(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        assert "/api/unreal/frame-actor" in paths
        assert "/api/unreal/capture-proof" in paths
        assert "/api/unreal/frame-and-proof" in paths
        assert schema["paths"]["/api/unreal/frame-actor"]["post"]["summary"]
        assert "FrameActorRequest" in schema["components"]["schemas"]
        assert "FrameAndProofResponse" in schema["components"]["schemas"]