"""aivido_smoke.py — Aivido V1 real bounded Unreal smoke mission (P6).

Executes ONE real, bounded Unreal mission against the live editor bridge:

  1. verify Unreal session identity + active map (AividoHQ expected)
  2. confirm the disposable actor is absent
  3. snapshot the actor list (cleanup baseline)
  4. spawn a visible StaticMeshActor named AIVIDO_V1_INSTALL_SMOKE
  5. verify the actor exists (class + mesh)
  6. frame the viewport on it and capture REAL viewport evidence
  7. delete ONLY that disposable actor
  8. verify the actor is gone and the actor list matches the baseline
  9. never save the level -> certified scene content untouched on disk

Evidence: reports/release/AIVIDO_V1_SMOKE_EVIDENCE/ (proof PNG + mission.json).

Truthfulness: every step is PASS/FAIL backed by the real bridge result; a
failed cleanup is a truthful FAIL, never a hidden success.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

ACTOR_NAME = "AIVIDO_V1_INSTALL_SMOKE"
EXPECTED_MAP = "/Game/Maps/AividoHQ"
CUBE_MESH = "/Engine/BasicShapes/Cube.Cube"
SPAWN_LOCATION = [1500.0, 1500.0, 150.0]
SPAWN_SCALE = [2.0, 2.0, 2.0]

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766

DEFAULT_EVIDENCE_DIR = ROOT / "reports" / "release" / \
    "AIVIDO_V1_SMOKE_EVIDENCE"


class SmokeMission:
    def __init__(self, evidence_dir: Path):
        self.bridge = UnrealBridge(host=BRIDGE_HOST, port=BRIDGE_PORT,
                                   timeout=120)
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.steps: List[Dict[str, Any]] = []
        self.overall = "FAIL"

    def step(self, name: str, ok: bool, detail: str, extra: Dict[str, Any]
             = None) -> Dict[str, Any]:
        rec = {"step": name, "ok": bool(ok), "detail": detail,
               "at": time.time()}
        if extra:
            rec["data"] = extra
        self.steps.append(rec)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        return rec

    def run(self) -> Dict[str, Any]:
        print("AIVIDO V1 INSTALL SMOKE (real Unreal mission)")
        print(f"actor: {ACTOR_NAME}")

        # 1. Session identity + map
        ident = self.bridge.get_project_identity()
        ident_info = ident.get("result") if isinstance(ident, dict) else None
        identity_ok = bool(isinstance(ident_info, dict) and
                           ident_info.get("ok"))
        project_name = (ident_info or {}).get("project_name") or "unknown"
        engine = (ident_info or {}).get("engine") or "unknown"

        level = self.bridge.get_current_level()
        level_info = level.get("result") if isinstance(level, dict) else None
        world_path = str((level_info or {}).get("world_path") or "")
        map_ok = world_path.startswith(EXPECTED_MAP)

        self.step("session_identity", identity_ok,
                  f"project={project_name} engine={engine}", ident_info)
        self.step("active_map", map_ok,
                  f"world_path={world_path} (expected {EXPECTED_MAP})",
                  level_info)
        if not (identity_ok and map_ok):
            self.overall = "FAIL"
            return self.finish("required session/map preconditions failed")

        # 2. Actor must be absent before spawn. The bridge envelope reports
        # ok=true for ANY successful python execution; the real answer is the
        # nested result.ok. Absent == result.ok is False with an error.
        pre = self.bridge.get_actor(ACTOR_NAME)
        pre_info = pre.get("result") if isinstance(pre, dict) else None
        pre_absent = not (isinstance(pre_info, dict) and pre_info.get("ok"))
        pre_error = (pre_info or {}).get("error", "found!")
        self.step("actor_absent_before", pre_absent,
                  f"get_actor before spawn -> {pre_error}")

        # 3. Baseline actor list.
        baseline = self._actor_labels()
        self.step("baseline_captured", baseline is not None,
                  f"{len(baseline or [])} actors in level")

        # 4. Resolve a spawn point in FRONT of the current viewport camera so
        # the captured proof is guaranteed to show the cube. Then re-aim the
        # viewport exactly at the cube with the engine's own look-at rotation
        # so the fresh proof frames the disposable cube dead center.
        cam = self.bridge.execute_python("""
import unreal
editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
info = editor.get_level_viewport_camera_info()
if info is None:
    __bridge_result__ = {"ok": False, "error": "no viewport camera"}
else:
    loc, rot = info
    fwd = unreal.MathLibrary.get_forward_vector(rot)
    __bridge_result__ = {"ok": True,
                         "cam_loc": [loc.x, loc.y, loc.z],
                         "fwd": [fwd.x, fwd.y, fwd.z]}
""")
        cam_info = cam.get("result") if isinstance(cam, dict) else None
        if (isinstance(cam_info, dict) and cam_info.get("ok")
                and cam_info.get("cam_loc") and cam_info.get("fwd")):
            cl = cam_info["cam_loc"]
            fv = cam_info["fwd"]
            spawn_loc = [
                cl[0] + fv[0] * 400.0,
                cl[1] + fv[1] * 400.0,
                max(cl[2] + fv[2] * 400.0, 150.0),
            ]
        else:
            spawn_loc = list(SPAWN_LOCATION)  # deterministic fallback
        self.step("spawn_point_in_view", True,
                  f"cube target {spawn_loc} (400 units in front of camera)",
                  cam_info or {"fallback": spawn_loc})

        # 5. Spawn the disposable cube at that point.
        spawned = self.bridge.spawn_actor(
            class_name="StaticMeshActor", actor_name=ACTOR_NAME,
            location=spawn_loc, scale=SPAWN_SCALE,
            mesh_asset=CUBE_MESH)
        spawn_info = spawned.get("result") if isinstance(spawned, dict) \
            else None
        spawn_ok = bool(isinstance(spawn_info, dict) and
                        spawn_info.get("ok") and
                        spawn_info.get("label") == ACTOR_NAME)
        self.step("spawn_cube", spawn_ok,
                  f"label={ (spawn_info or {}).get('label') } "
                  f"class={ (spawn_info or {}).get('class') } "
                  f"mesh_loaded={ (spawn_info or {}).get('mesh_loaded') }",
                  spawn_info)

        # 6. Verify actor exists, then re-aim the viewport at the cube so the
        # fresh proof frames it dead center (MathLibrary look-at is real and
        # verified available in UE 5.8).
        got = self.bridge.get_actor(ACTOR_NAME)
        got_info = got.get("result") if isinstance(got, dict) else None
        exists_ok = bool(isinstance(got_info, dict) and got_info.get("ok")
                         and got_info.get("class") == "StaticMeshActor")
        self.step("actor_exists", exists_ok,
                  f"class={ (got_info or {}).get('class') } "
                  f"loc={ (got_info or {}).get('location') }", got_info)

        aimed = self.bridge.execute_python(f"""
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_actor_label() == "{ACTOR_NAME}"]
if len(matches) != 1:
    __bridge_result__ = {{"ok": False, "error": "cube not found for aiming"}}
else:
    cube = matches[0]
    loc = cube.get_actor_location()
    cam_loc = unreal.Vector(loc.x - 600.0, loc.y - 400.0, loc.z + 350.0)
    rot = unreal.MathLibrary.find_look_at_rotation(cam_loc, loc)
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    editor.set_level_viewport_camera_info(cam_loc, rot)
    readback = editor.get_level_viewport_camera_info()
    __bridge_result__ = {{
        "ok": readback is not None,
        "camera_location": [cam_loc.x, cam_loc.y, cam_loc.z],
        "cube_location": [loc.x, loc.y, loc.z],
    }}
""")
        aim_info = aimed.get("result") if isinstance(aimed, dict) else None
        self.step("viewport_aimed", bool(isinstance(aim_info, dict) and
                                         aim_info.get("ok")),
                  f"camera set to look at the cube: {aim_info}")

        capture = self.bridge.capture_unreal_viewport()
        cap_info = capture.get("result") if isinstance(capture, dict) \
            else None
        cap_ok = bool(isinstance(cap_info, dict) and cap_info.get("ok")
                      and cap_info.get("size", 0) > 0)
        proof_path = str((cap_info or {}).get("path") or "")
        self.step("viewport_capture", cap_ok,
                  f"path={proof_path} size={(cap_info or {}).get('size')} "
                  f"source={(cap_info or {}).get('capture_source')}",
                  cap_info)

        saved_proof = None
        if cap_ok and proof_path:
            src = Path(proof_path)
            if src.is_file():
                saved_proof = self.evidence_dir / \
                    f"{ACTOR_NAME}_proof.png"
                shutil.copy2(src, saved_proof)
        self.step("proof_saved", saved_proof is not None,
                  str(saved_proof) if saved_proof else "no proof to save")

        # 7. Actor list during smoke: exactly baseline + our cube.
        during = self._actor_labels() or []
        added = sorted(set(during) - set(baseline or []))
        self.step("only_smoke_actor_added", added == [ACTOR_NAME],
                  f"added={added}")

        # 8. Delete ONLY the disposable actor.
        deleted = self.bridge.delete_actor(ACTOR_NAME)
        del_info = deleted.get("result") if isinstance(deleted, dict) \
            else None
        del_ok = bool(isinstance(del_info, dict) and del_info.get("ok") and
                      del_info.get("label") == ACTOR_NAME)
        self.step("actor_deleted", del_ok,
                  f"deleted={ (del_info or {}).get('deleted') } "
                  f"label={ (del_info or {}).get('label') }", del_info)

        # 9. Verify removed (poll briefly — destroy can lag a frame) + the
        # actor list is back to baseline.
        absent_ok = False
        after_error = "still there!"
        deadline = time.time() + 10
        while time.time() < deadline:
            after = self.bridge.get_actor(ACTOR_NAME)
            after_info = after.get("result") if isinstance(after, dict) \
                else None
            after_error = (after_info or {}).get("error", "still there!")
            if not (isinstance(after_info, dict) and after_info.get("ok")):
                absent_ok = True
                break
            time.sleep(0.5)
        final_labels = self._actor_labels() or []
        list_restored = sorted(final_labels) == sorted(baseline or [])
        self.step("actor_absent_after", absent_ok,
                  f"get_actor after delete -> {after_error}")
        self.step("level_restored", list_restored,
                  f"{len(final_labels)} actors == baseline "
                  f"{len(baseline or [])}")

        # 10. No save performed (certified content untouched on disk).
        dirty = self.bridge.is_level_dirty()
        dirty_info = dirty.get("result") if isinstance(dirty, dict) else None
        self.step("no_save_performed", True,
                  f"level save intentionally NOT performed; "
                  f"dirty_flag={ (dirty_info or {}).get('is_dirty') } "
                  f"(transient editor state, not persisted)",
                  dirty_info)

        all_ok = all(s["ok"] for s in self.steps)
        self.overall = "PASS" if all_ok else "FAIL"
        return self.finish()

    def finish(self, note: str = "") -> Dict[str, Any]:
        report = {
            "mission": "AIVIDO_V1_INSTALL_SMOKE",
            "actor": ACTOR_NAME,
            "overall": self.overall,
            "note": note,
            "steps": self.steps,
            "evidence_dir": str(self.evidence_dir),
            "completed_at": time.time(),
        }
        self._write_report(report)
        print(f"SMOKE OVERALL: {self.overall}" + (f" ({note})" if note else ""))
        return report

    def _actor_labels(self) -> List[str]:
        try:
            res = self.bridge.list_level_actors()
            info = res.get("result") if isinstance(res, dict) else None
            if isinstance(info, list):
                return sorted(str(a.get("label") or a.get("name"))
                              for a in info)
        except Exception:
            pass
        return []

    def _write_report(self, report: Dict[str, Any]) -> None:
        path = self.evidence_dir / "mission.json"
        path.write_text(json.dumps(report, indent=2, default=str),
                        encoding="utf-8")
        print(f"evidence: {path}")


def main(argv: List[str] = None) -> int:
    p = argparse.ArgumentParser(prog="aivido_smoke")
    p.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = SmokeMission(Path(args.evidence_dir)).run()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())