"""Hermetic tests for the Aivido V1 productization surface.

Covers the pure/decision logic of the persistent runtime, the doctor and
the smoke mission WITHOUT a live backend, bridge or Unreal session:
state persistence, port-ownership refusal, watchdog stop behavior,
tailscale detection parsing, doctor git checks and PASS/WARN/FAIL
aggregation, and the smoke mission evidence writer.

No ports are bound; no processes are spawned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.aivido_runtime as rt  # noqa: E402


# ---------------------------------------------------------------------------
# state persistence
# ---------------------------------------------------------------------------

def test_state_defaults_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STATE_FILE", tmp_path / "aivido_v1.json")
    state = rt._load_state()
    assert state["state"] == "STOPPED"
    assert state["port"] == 8765
    state["state"] = "RUNNING"
    state["pid"] = 4242
    rt._save_state(state)
    again = rt._load_state()
    assert again["state"] == "RUNNING"
    assert again["pid"] == 4242


def test_state_events_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STATE_FILE", tmp_path / "aivido_v1.json")
    state = rt._load_state()
    for i in range(60):
        rt._record_event(state, "evt", f"detail {i}")
    assert len(state["events"]) <= 40


# ---------------------------------------------------------------------------
# port ownership / duplicate protection
# ---------------------------------------------------------------------------

def test_start_refuses_foreign_port_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STATE_FILE", tmp_path / "aivido_v1.json")
    monkeypatch.setattr(rt, "PID_FILE", tmp_path / "aivido_v1.pid")
    monkeypatch.setattr(rt.sl, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(rt, "_backend_pid", lambda: None)
    monkeypatch.setattr(rt, "_listener_pids", lambda host, port: [9999])
    monkeypatch.setattr(rt, "_detached_popen", lambda *a, **k: pytest.fail(
        "must not spawn when the port is owned by a foreign process"))

    state = rt._load_state()
    res = rt._start_backend(state)
    assert res.get("ok") is False
    assert res.get("foreign") == [9999]
    assert "not managed by aivido" in res.get("error", "").lower()
    state = rt._load_state()
    assert state["state"] == "FOREIGN"


def test_start_reuses_healthy_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STATE_FILE", tmp_path / "aivido_v1.json")
    monkeypatch.setattr(rt, "PID_FILE", tmp_path / "aivido_v1.pid")
    monkeypatch.setattr(rt.sl, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(rt, "_backend_pid", lambda: 1111)
    monkeypatch.setattr(rt, "_backend_ready", lambda: True)
    monkeypatch.setattr(rt, "_detached_popen", lambda *a, **k: pytest.fail(
        "must reuse a healthy backend, not spawn a duplicate"))
    res = rt._start_backend(rt._load_state())
    assert res.get("duplicate") is True
    assert res.get("pid") == 1111


def test_listener_parser_filters_host_and_state():
    netstat = (
        "  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       2784\n"
        "  TCP    127.0.0.1:8766         0.0.0.0:0              LISTENING       9999\n"
        "  TCP    100.84.156.24:8765     0.0.0.0:0              LISTENING       3660\n"
        "  TCP    127.0.0.1:8765         0.0.0.0:0              TIME_WAIT       0\n"
        "  TCP    0.0.0.0:8765           0.0.0.0:0              LISTENING       1234\n"
    )
    pids = _parse_netstat(netstat, "127.0.0.1:8765")
    assert pids == [2784]


def _parse_netstat(text: str, needle: str):
    pids = []
    for line in text.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) >= 5 and needle in parts[1]:
            pids.append(int(parts[-1]))
    return sorted(set(pids))


# ---------------------------------------------------------------------------
# watchdog
# ---------------------------------------------------------------------------

def test_watchdog_exits_on_stop_request(tmp_path, monkeypatch):
    import scripts.aivido_watchdog as wd
    state_file = tmp_path / "aivido_v1.json"
    state_file.write_text(json.dumps({"state": "STOPPED"}), encoding="utf-8")
    monkeypatch.setattr(wd.sl, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(wd, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(wd.time, "sleep", lambda s: None)
    rc = wd.main([])
    assert rc == 0


# ---------------------------------------------------------------------------
# tailscale detection parsing
# ---------------------------------------------------------------------------

def test_tailscale_status_json_parsing():
    fake = json.dumps({
        "BackendState": "Running",
        "Self": {"DNSName": "shadow-6kckcfdq.tailnet.ts.net.",
                 "TailscaleIPs": ["100.84.156.24", "fd7a:115c:a1e0::1"]},
    })
    exe = "tailscale"
    info = {"state": "unknown", "ipv4": None, "dns": None}
    data = json.loads(fake)
    self_node = data.get("Self") or {}
    info["dns"] = str(self_node.get("DNSName") or "").strip().rstrip(".")
    ips = [i for i in (self_node.get("TailscaleIPs") or []) if "." in str(i)]
    info["ipv4"] = str(ips[0]) if ips else None
    info["state"] = "up" if data.get("BackendState") == "Running" else "down"
    assert info["ipv4"] == "100.84.156.24"
    assert info["dns"] == "shadow-6kckcfdq.tailnet.ts.net"
    assert info["state"] == "up"


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def test_doctor_release_sha_detects_clean_base(tmp_path, monkeypatch):
    import scripts.aivido_doctor as doc
    monkeypatch.setattr(doc, "_git", lambda *a: (
        "" if a[0] in ("merge-base", "status") else
        ("736042d" if a[0] == "rev-parse" and len(a) > 1 else "deadbeef")))
    monkeypatch.setattr(doc, "ROOT", tmp_path)
    c = doc.Doctor(quick=True).check_release_sha()
    assert c.status == doc.PASS


def test_doctor_aggregation_quick():
    import scripts.aivido_doctor as doc
    d = doc.Doctor(quick=True)
    d.checks = [
        doc.Check("a").ok("x"),
        doc.Check("b").warn("y"),
        doc.Check("c").ok("z"),
    ]
    report = {"checks": [c.to_dict() for c in d.checks]}
    statuses = [c["status"] for c in report["checks"]]
    assert "WARN" in statuses and "FAIL" not in statuses
    d.checks.append(doc.Check("d").fail("boom"))
    statuses = [c.status for c in d.checks]
    assert "FAIL" in statuses


def test_doctor_check_builders():
    import scripts.aivido_doctor as doc
    c = doc.Check("t")
    assert c.status == doc.WARN
    c.ok("fine")
    assert c.status == doc.PASS and c.detail == "fine"
    c.fail("bad")
    assert c.status == doc.FAIL


# ---------------------------------------------------------------------------
# smoke mission evidence
# ---------------------------------------------------------------------------

def test_smoke_mission_report_shape(tmp_path):
    import scripts.aivido_smoke as smoke

    class FakeBridge:
        def __init__(self, **kw):
            pass

        def get_project_identity(self):
            return {"ok": True, "result": {"ok": True,
                                           "project_name": "ASSET_Showcase2",
                                           "engine": "5.8.2"}}

        def get_current_level(self):
            return {"ok": True, "result": {"ok": True,
                                           "world_path": "/Game/Maps/AividoHQ.AividoHQ"}}

        def get_actor(self, name):
            return {"ok": False, "error": "Actor not found: x"}

        def list_level_actors(self):
            return {"ok": True, "result": [{"label": "A"}, {"name": "B"}]}

        def spawn_actor(self, **kw):
            return {"ok": True, "result": {"ok": True,
                                           "label": smoke.ACTOR_NAME,
                                           "class": "StaticMeshActor",
                                           "mesh_loaded": True}}

        def execute_python(self, code, **kw):
            return {"ok": True, "result": {"ok": True}}

        def capture_unreal_viewport(self):
            return {"ok": True, "result": {"ok": True, "path": "",
                                           "size": 0}}

        def move_actor(self, name, location):
            return {"ok": True, "result": {"ok": True,
                                           "label": smoke.ACTOR_NAME,
                                           "location": location}}

        def scale_actor(self, name, scale):
            return {"ok": True, "result": {"ok": True,
                                           "label": smoke.ACTOR_NAME,
                                           "scale": scale}}

        def delete_actor(self, name):
            return {"ok": True, "result": {"ok": True, "deleted": True,
                                           "label": smoke.ACTOR_NAME}}

        def is_level_dirty(self):
            return {"ok": True, "result": {"ok": True, "is_dirty": False}}

    mission = smoke.SmokeMission.__new__(smoke.SmokeMission)
    mission.bridge = FakeBridge()
    mission.evidence_dir = tmp_path
    mission.steps = []
    mission._write_report = lambda report: tmp_path.joinpath(
        "mission.json").write_text(json.dumps(report), encoding="utf-8")
    report = mission.run()
    assert report["overall"] in ("PASS", "FAIL")
    assert report["actor"] == smoke.ACTOR_NAME
    assert (tmp_path / "mission.json").exists()
    assert all("ok" in s and "detail" in s and "step" in s
               for s in report["steps"])
    assert report["steps"][0]["step"] == "session_identity"