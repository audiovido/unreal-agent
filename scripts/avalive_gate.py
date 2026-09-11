#!/usr/bin/env python3
"""avalive_gate.py — AvaLive-side guarded launch / status / return contract.

Small configurable launcher usable by the AudioVido (AV) app to open AvaLive,
handshake with its local bridge, and return gracefully WITHOUT ever touching
the AV process or its 6767 bridge.

Commands:
    launch   open AvaLive only when 6766 is not READY (idempotent); wait for
             identity handshake; report structured success / busy / timeout /
             wrong-project collision; guard duplicate editors by exact
             uproject command line.
    status   structured live state: identity, AvaLive editor PIDs, port owner,
             backend status.
    return   gracefully save + close ONLY the verified AvaLive editor; confirm
             AvaLive gone; never targets AV.
    chat     user-flow entry: send ONE prompt through the existing FastAPI UI
             backend and return the answer (existing chat UI path, not rewritten).
    speak    user-flow entry: PIE MetaHuman speech regression using the frozen
             speaking pipeline (AS_AgentLine_Performance + agent_line) with
             mouth-churn proof.

All paths / ports / config live in avalive_gate.json (or --config) and may be
overridden by environment variables of the form AVG_<KEY> (dotted keys use "_").
No AV product code is touched.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

DEFAULT_CONFIG_PATH = SCRIPT_DIR / "avalive_gate.json"


# ---------------------------------------------------------------- config
def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # env overrides: AVG_PORT, AVG_AVALIVE_UPROJECT, AVG_UNREAL_EDITOR_EXE ...
    for key, val in os.environ.items():
        if key.startswith("AVG_"):
            sub_key = key[4:].lower()
            try:
                val = json.loads(val)
            except Exception:
                pass
            cfg[sub_key] = val
    cfg["_config_path"] = str(cfg_path)
    return cfg


def cfg(c, dotted: str, default=None):
    node = c
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ---------------------------------------------------------------- helpers
def ps_json(code: str):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True, text=True, timeout=60,
    )
    out = r.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return {"_raw": out}


def avalive_pids(uproject: str) -> list:
    """Editors whose command line contains the EXACT avalive uproject path."""
    needle = uproject.replace("\\", "/")
    data = ps_json(
        r"""Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" |
        Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"""
    )
    procs = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    pids = []
    for p in procs:
        cmd = str(p.get("CommandLine") or "").replace("\\", "/")
        if needle.lower() in cmd.lower():
            pids.append(int(p["ProcessId"]))
    return sorted(pids)


def audiovido_pids() -> list:
    data = ps_json(
        r"""Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" |
        Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"""
    )
    procs = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    return sorted(
        int(p["ProcessId"]) for p in procs
        if p and "AudioVidoLivingCity.uproject" in str(p.get("CommandLine") or "").replace("\\", "/")
    )


def bridge_identity(c: dict, timeout: float = 12.0):
    """Return the live listener identity dict or None if unreachable."""
    bridge = UnrealBridge(host=cfg(c, "host", "127.0.0.1"), port=cfg(c, "port", 6766), timeout=timeout)
    r = bridge.ping()
    if not isinstance(r, dict) or not r.get("ok"):
        return None
    ident = r.get("identity") or {}
    return dict(ident) if isinstance(ident, dict) else None


def identity_matches(c: dict, ident: dict | None) -> dict:
    """Structured handshake check (project, map, listener version, port)."""
    expected_project = cfg(c, "expected_project")
    expected_map = cfg(c, "expected_map")
    expected_listener = cfg(c, "expected_listener")
    port = int(cfg(c, "port", 6766))
    if not ident:
        return {"ok": False, "reason": "no_identity", "identity": None}
    checks = {
        "project": str(ident.get("project_name")) == expected_project,
        "map": str(ident.get("world") or "").split(".", 1)[0] == expected_map
               or str(ident.get("world")) == expected_map,
        "listener": str(ident.get("listener_version")) == expected_listener,
        "port": int(ident.get("bridge_port") or ident.get("bridge_port", 0)) == port,
        "uproject": str(ident.get("uproject_path") or "").replace("\\", "/").lower()
                    == str(cfg(c, "avalive_uproject")).replace("\\", "/").lower(),
    }
    ok = all(checks.values())
    return {"ok": ok, "checks": checks, "identity": ident}


def backend_state(c: dict):
    import requests
    try:
        r = requests.get(cfg(c, "backend_base", "http://127.0.0.1:8765") + "/api/status", timeout=4)
        return r.json() if r.ok else {"error": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- commands
def handoff_block(c: dict) -> dict:
    """Minimal supported user-flow handoff: point at the already-existing local
    AvaLive Chat UI served by the existing FastAPI backend (app/api.py, no new
    chat product; frozen MetaHuman pipeline untouched)."""
    base = str(cfg(c, "backend_base", "http://127.0.0.1:8765")).rstrip("/")
    return {
        "handoff": {
            "ui_url": base + "/",
            "open_command": "start " + base + "/",
            "dev_console_url": base + "/dev",
            "backend": "existing FastAPI app/api.py (uvicorn 0.0.0.0:8765)",
            "note": "Existing AvaLive Chat UI used as-is; no new chat product and no change to the frozen speaking pipeline.",
        }
    }


def cmd_launch(c: dict, caller: dict | None = None) -> dict:
    caller = caller or {}
    meta = {
        "source": caller.get("source"),
        "return_target": caller.get("return_target"),
        "intent": caller.get("intent"),
    }
    meta.update(handoff_block(c))
    port = int(cfg(c, "port", 6766))
    host = cfg(c, "host", "127.0.0.1")
    uproject = cfg(c, "avalive_uproject")
    timeout = float(cfg(c, "listen_timeout_seconds", 180))

    ident = bridge_identity(c)
    handshake = identity_matches(c, ident)
    if handshake["ok"]:
        return {
            "status": "ready",
            "action": "none_idempotent",
            "identity": handshake["identity"],
            "avalive_pids": avalive_pids(uproject),
            "message": "AvaLive bridge already READY; no launch required.",
            **meta,
        }

    # Busy guard: existing backend task running.
    bs = backend_state(c)
    if isinstance(bs, dict) and bs.get("execution_active"):
        return {"status": "busy", "error": "backend_task_active", "backend": bs,
                "identity": ident, **meta}

    # Wrong-project / collision guard: something else owns the port.
    if ident is not None and not handshake["ok"]:
        return {
            "status": "collision",
            "error": "WRONG_PROJECT_CONTEXT_OR_STALE_LISTENER",
            "actual_identity": ident,
            "expected": cfg(c, "expected_project"),
            "port": port,
            **meta,
        }
    try:
        probe = socket.create_connection((host, port), 2)
        probe.close()
        return {"status": "collision", "error": "port_occupied_no_valid_identity",
                "port": port, **meta}
    except Exception:
        pass

    # Duplicate-editor guard: exactly one avalive editor already starting.
    pids = avalive_pids(uproject)
    if pids:
        return {"status": "starting", "action": "none", "avalive_pids": pids,
                "message": "AvaLive editor already running/starting; waiting for handshake.",
                **meta}

    # Launch the exact avalive uproject.
    exe = cfg(c, "unreal_editor_exe")
    cwd = cfg(c, "project_cwd") or str(Path(uproject).parent)
    try:
        proc = subprocess.Popen([exe, uproject], cwd=cwd,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        launched_pid = proc.pid
    except Exception as exc:
        return {"status": "launch_failed", "error": f"{type(exc).__name__}: {exc}",
                **meta}

    deadline = time.time() + timeout
    last_ident = None
    while time.time() < deadline:
        ident = bridge_identity(c)
        handshake = identity_matches(c, ident)
        if handshake["ok"]:
            return {
                "status": "ready",
                "action": "launched",
                "launched_pid": launched_pid,
                "identity": handshake["identity"],
                "avalive_pids": avalive_pids(uproject),
                "wait_seconds": round(timeout - (deadline - time.time()), 1),
                **meta,
            }
        if ident is not None:
            last_ident = ident
            # wrong-project owner appeared while waiting -> collision
            if not handshake["ok"]:
                return {"status": "collision", "error": "WRONG_PROJECT_CONTEXT_OR_STALE_LISTENER",
                        "actual_identity": ident, "port": port, **meta}
        time.sleep(2)

    return {
        "status": "timeout",
        "error": "readiness_timeout",
        "timeout_seconds": timeout,
        "last_identity": last_ident,
        "avalive_pids": avalive_pids(uproject),
        **meta,
    }


def cmd_status(c: dict) -> dict:
    ident = bridge_identity(c)
    handshake = identity_matches(c, ident)
    return {
        "status": "ready" if handshake["ok"] else ("degraded" if ident else "unreachable"),
        "identity": ident,
        "handshake": handshake,
        "avalive_pids": avalive_pids(cfg(c, "avalive_uproject")),
        "audiovido_pids": audiovido_pids(),
        "backend": backend_state(c),
        "config_path": c["_config_path"],
        "port": cfg(c, "port", 6766),
        "expected": {"project": cfg(c, "expected_project"),
                     "map": cfg(c, "expected_map"),
                     "listener": cfg(c, "expected_listener")},
    }


def cmd_return(c: dict) -> dict:
    """Gracefully save + close ONLY the verified AvaLive editor."""
    uproject = cfg(c, "avalive_uproject")
    av_before = audiovido_pids()

    # 1) Save AvaLive dirty work through the verified bridge only.
    save_result = None
    ident = bridge_identity(c)
    if ident:
        bridge = UnrealBridge(host=cfg(c, "host", "127.0.0.1"),
                              port=cfg(c, "port", 6766), timeout=60)
        save_result = bridge.execute_python(
            "unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)",
            expected_project="AvaLive",
        )

    # 2) Gracefully close the verified AvaLive editor(s), matched by cmdline.
    pids = avalive_pids(uproject)
    closed, forced = [], []
    for pid in pids:
        close = ps_json(
            rf"""$p=Get-Process -Id {pid} -ErrorAction Stop; $p.CloseMainWindow() | Out-Null; 'sent'"""
        )
        deadline = time.time() + 45
        while time.time() < deadline:
            alive = ps_json(rf"""try{{Get-Process -Id {pid} -ErrorAction Stop | Select -Expand Id}}catch{{'gone'}}""")
            if alive is None or str(alive) == "gone" or alive == "gone":
                break
            time.sleep(2)
        else:
            ps_json(rf"""Stop-Process -Id {pid} -Force""")
            forced.append(pid)
            time.sleep(3)
        if pid not in forced:
            closed.append(pid)

    time.sleep(3)
    remaining = avalive_pids(uproject)
    av_after = audiovido_pids()
    return {
        "status": "returned" if not remaining else "partial",
        "saved": bool(save_result and save_result.get("ok")),
        "save_result_ok": bool(save_result and save_result.get("ok")),
        "closed_gracefully": closed,
        "forced": forced,
        "avalive_remaining_pids": remaining,
        "audiovido_pids_before": av_before,
        "audiovido_pids_after": av_after,
        "audiovido_untouched": av_before == av_after and bool(av_before),
    }


def cmd_chat(c: dict, prompt: str | None = None) -> dict:
    """Send ONE prompt to the existing FastAPI Chat endpoint (`/api/chat`)
    and return the REAL user-facing assistant reply.

    NEVER returns workflow/task-loop artifacts (goal criteria, plan steps,
    executor status). Only responses classified by the backend as `chat` or
    `plan` are surfaced as `answer`. If the backend classifies the prompt as
    `execute` (or returns an executor artifact), this returns an explicit
    `error` so the caller never mistakes a workflow artifact for a chat reply.
    """
    import requests
    base = cfg(c, "backend_base", "http://127.0.0.1:8765")
    prompt = (prompt or "").strip() or cfg(c, "chat_prompt")
    timeout = float(cfg(c, "chat_timeout_seconds", 180))
    try:
        r = requests.post(base + "/api/chat",
                          json={"message": prompt},
                          timeout=timeout)
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    if not r.ok:
        return {"status": "error", "error": f"HTTP {r.status_code}", "body": r.text[:300]}
    j = r.json()
    state = j.get("state")
    mode = j.get("mode")
    message_raw = j.get("message")
    answer = message_raw if isinstance(message_raw, str) and message_raw.strip() else None
    if not answer:
        return {"status": "error", "error": "no_user_facing_reply",
                "http": r.status_code, "response": j}
    # Truthful classification: only conversational/planning replies are
    # user-facing answers. Executor output is NOT an assistant reply.
    if mode not in ("chat", "plan"):
        return {
            "status": "error",
            "error": f"backend_classified_as_{mode or 'unknown'}",
            "message": "Prompt was routed to the executor workflow, not the chat model; "
                        "no user-facing reply available. Use a conversational prompt.",
            "backend_message": answer,
            "mode": mode, "state": state, "prompt": prompt,
            "endpoint": base + "/api/chat",
        }
    return {"status": "answered", "mode": mode, "state": state,
            "answer": answer, "prompt": prompt,
            "endpoint": base + "/api/chat"}


def _decode_png_rgba(path: Path):
    import struct
    import zlib
    data = path.read_bytes()
    pos = 8
    idat = b""
    w = h = ct = 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _bd, ct, _, _, _ = struct.unpack(">IIBBBBB", body[:13])
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    bpp = 4 if ct == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * bpp
    out = bytearray(w * h * bpp)
    prev = bytearray(stride)
    rp = 0
    for _y in range(h):
        f = raw[rp]; rp += 1
        line = bytearray(raw[rp:rp + stride]); rp += stride
        if f == 1:
            for i in range(bpp, stride): line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]; c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[_y * stride:(_y + 1) * stride] = line
        prev = line
    return w, h, bpp, out


def _mouth_churn_pct(a, b, w, h, bpp, thr=20):
    x0, y0 = int(w * 0.42), int(h * 0.42)
    x1, y1 = int(w * 0.58), int(h * 0.55)
    n = big = 0
    for y in range(y0, y1):
        o = y * w * bpp
        for x in range(x0, x1):
            i = o + x * bpp
            d = max(abs(a[i] - b[i]), abs(a[i + 1] - b[i + 1]), abs(a[i + 2] - b[i + 2]))
            n += 1
            if d > thr:
                big += 1
    return 100.0 * big / n


def cmd_speak(c: dict) -> dict:
    """PIE speech regression via the frozen pipeline + churn proof."""
    import base64
    ident = bridge_identity(c)
    if not ident:
        return {"status": "error", "error": "bridge_unreachable_for_speak"}
    bridge = UnrealBridge(host=cfg(c, "host", "127.0.0.1"), port=cfg(c, "port", 6766), timeout=90)
    anim = cfg(c, "speech.anim_sequence")
    sound = cfg(c, "speech.sound_wave")
    actor_name = cfg(c, "speech.actor_name")
    frame_interval = float(cfg(c, "speech.frame_interval", 1.1))
    frame_count = int(cfg(c, "speech.frame_count", 4))
    saved_dir = r"C:/Users/Shadow/Desktop/AvaLive/AvaLive/Saved/UnrealAgent"

    # 1) start PIE
    r = bridge.execute_python(
        """import unreal
sub=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
sub.editor_request_begin_play()
__bridge_result__={'requested':True}""", expected_project="AvaLive")
    if not r.get("ok"):
        return {"status": "error", "error": "PIE start failed", "result": r}
    gw = None
    for _ in range(30):
        q = bridge.execute_python(
            """import unreal
__bridge_result__=str(unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world())""",
            expected_project="AvaLive")
        if q.get("result") and "None" not in str(q.get("result")):
            gw = True
            break
        time.sleep(1)
    if not gw:
        bridge.execute_python(
            """import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
__bridge_result__=True""", expected_project="AvaLive")
        return {"status": "error", "error": "PIE world never appeared"}

    time.sleep(2.5)  # let PIE settle before driving the scene
    start = bridge.execute_python(
        f"""import unreal
eds=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
gw=eds.get_game_world()
actor=next((a for a in unreal.GameplayStatics.get_all_actors_of_class(gw,unreal.Actor) if a.get_name().startswith({actor_name!r})),None)
out={{'actor':bool(actor)}}
if actor:
    # portrait framing: point the PIE view at the scene CameraActor exactly like
    # the graduated speaking proof run.
    cam=next((a for a in unreal.GameplayStatics.get_all_actors_of_class(gw,unreal.Actor) if a.get_class().get_name()=='CameraActor'),None)
    if cam:
        unreal.GameplayStatics.get_player_controller(gw,0).set_view_target_with_blend(cam,0.0)
        out['framed']=cam.get_name()
    face=[c for c in actor.get_components_by_class(unreal.SkeletalMeshComponent) if c.get_name()=='Face'][0]
    face.play_animation(unreal.load_asset({anim!r}),False)
    unreal.GameplayStatics.play_sound_at_location(gw,unreal.load_asset({sound!r}),actor.get_actor_location(),unreal.Rotator())
    out['anim']=True
    out['audio']=True
__bridge_result__=out""", expected_project="AvaLive")
    if not (start.get("result") or {}).get("anim"):
        bridge.execute_python(
            """import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
__bridge_result__=True""", expected_project="AvaLive")
        return {"status": "error", "error": "face anim/audio start failed", "start": start}

    # 2) capture frames while speaking
    paths = []
    for i in range(1, frame_count + 1):
        if i > 1:
            time.sleep(frame_interval)
        fn = f"{saved_dir}/gate_speak_t{i}.png"
        cap = bridge.execute_python(
            f"""import unreal
__bridge_result__=unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(r'{fn}')""",
            expected_project="AvaLive")
        paths.append((fn, str(cap.get("result") or "")[:80]))
        # mirror the freshest frame to the UI proof feed so the chat PiP shows
        # the human speaking live during a speak run.
        import shutil as _shutil
        try:
            _shutil.copyfile(fn, f"{saved_dir}/pie_viewport_latest.png")
        except Exception:
            pass

    # 3) stop PIE
    bridge.execute_python(
        """import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
__bridge_result__=True""", expected_project="AvaLive")
    time.sleep(4)

    # 4) churn proof
    frames = {}
    for fn, _d in paths:
        p = Path(fn)
        if p.exists():
            frames[p.name] = _decode_png_rgba(p)
    churn = []
    names = [Path(fn).name for fn, _d in paths]
    for a, b in zip(names, names[1:]):
        if a in frames and b in frames:
            wa, ha, bppa, A = frames[a]
            churn.append(round(_mouth_churn_pct(A, frames[b][3], wa, ha, bppa), 2))
    ok = bool(churn and max(churn) > float(cfg(c, "speech.mouth_churn_threshold_pct", 1.0)))
    return {
        "status": "pass" if ok else "fail",
        "ok": ok,
        "churn_pct": churn,
        "threshold_pct": float(cfg(c, "speech.mouth_churn_threshold_pct", 1.0)),
        "frames": paths,
        "source": "GameViewport PIE",
        "speech_assets": {"anim_sequence": anim, "sound_wave": sound, "actor": actor_name},
    }


COMMANDS = {"launch": cmd_launch, "status": cmd_status, "return": cmd_return,
            "chat": cmd_chat, "speak": cmd_speak}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command = argv[0]
    config_path = None
    rest = []
    for a in argv[1:]:
        if a.startswith("--config="):
            config_path = a.split("=", 1)[1]
        elif a == "--config" and len(argv) > argv.index(a) + 1:
            config_path = argv[argv.index(a) + 1]
        else:
            rest.append(a)
    if command not in COMMANDS:
        print(json.dumps({"ok": False, "error": f"unknown command: {command}",
                          "commands": sorted(COMMANDS)}))
        return 2
    c = load_config(config_path)
    # AV launcher invocation shape: `launch [source] [return_target] [intent]`
    # is accepted (and echoed) without failing on those optional positionals.
    caller = None
    chat_prompt_arg = None
    if command == "launch":
        caller = {
            "source": rest[0] if len(rest) > 0 else None,
            "return_target": rest[1] if len(rest) > 1 else None,
            "intent": rest[2] if len(rest) > 2 else None,
        }
    elif command == "chat" and rest:
        chat_prompt_arg = " ".join(rest)
    if command == "launch":
        result = COMMANDS[command](c, caller)
    elif command == "chat":
        result = COMMANDS[command](c, chat_prompt_arg)
    else:
        result = COMMANDS[command](c)
    print(json.dumps({"ok": result.get("status") in ("ready", "returned", "answered",
                                                     "answered_sync", "pass", "starting"),
                      "command": command, "result": result},
                     indent=1, default=str))
    return 0 if result.get("status") in ("ready", "returned", "answered",
                                         "answered_sync", "pass") else 1


if __name__ == "__main__":
    sys.exit(main())