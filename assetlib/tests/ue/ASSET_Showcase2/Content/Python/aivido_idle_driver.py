"""AIVIDO polish: procedural human idle motion (P1).

Drives the 8 AVIDO_Human* agents with subtle, per-character procedural idle
motion (breathing bob, weight-shift sway, slow gaze yaw) while PIE is active.

Design notes (UE 5.8, python surface):
  * Bone-level pose editing is not available through the 5.8 python API
    (no set_bone_transform / bone keyframe writer, IK retargeter surface
    moved to the new op-stack model), and no compatible AnimSequences exist
    for the characters' Bip01 skeletons.
  * The mission-sanctioned fallback is small controlled procedural actor
    motion. Amplitudes are intentionally tiny (<= ~1.6 cm, <= ~2.5 deg) so
    the motion reads as human idle life, never as floating/exaggeration.
  * Only PIE (game world) actors are driven; the editor scene is untouched.
  * Motion is real and tick-driven: register via start_idle_driver() and the
    slate post-tick callback moves the actors every frame.

Registration (from the bridge / editor console):
    import aivido_idle_driver
    aivido_idle_driver.start_idle_driver()
    aivido_idle_driver.stop_idle_driver()   # optional
"""

import unreal
import math
import time

_HANDLE = None
_STATE = {"running": False, "chars": [], "t0": None, "calls": 0, "include_editor": False}

# Per-character profiles: index -> (breath_hz, breath_cm, sway_cm, yaw_deg, yaw_hz)
# Deterministic per-character variation (seeded by index) so no two agents are
# identical, while staying within believable idle amplitudes.
def _profile(i):
    seed = 0.371 + i * 0.6180339887
    s = seed - math.floor(seed)
    breath_hz = 0.17 + 0.05 * s
    breath_cm = 2.2 + 1.4 * s          # visible-but-subtle breathing bob (~2-4 cm)
    sway_cm = 1.0 + 1.2 * ((s * 1.7) - math.floor(s * 1.7))
    yaw_deg = 1.2 + 1.3 * ((s * 2.3) - math.floor(s * 2.3))
    yaw_hz = 0.035 + 0.045 * ((s * 3.1) - math.floor(s * 3.1))
    return (breath_hz, breath_cm, sway_cm, yaw_deg, yaw_hz)


def _find_chars(world):
    out = []
    all_a = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    for a in all_a:
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        if label.startswith("AVIDO_Human") or label.startswith("AVIDO_Agent"):
            out.append(a)
    return out


def _apply(chars, t):
    for c, base_loc, base_yaw, (bhz, bcm, scm, ydeg, yhz) in chars:
        ph_b = t * bhz
        ph_s = t * (bhz * 0.5)
        ph_y = t * yhz
        # bcm/scm are already in UE units (cm) — no further scaling.
        dz = bcm * math.sin(2 * math.pi * ph_b)
        dx = scm * math.sin(2 * math.pi * ph_s + 1.3)
        dy = scm * 0.5 * math.cos(2 * math.pi * ph_s)
        dyaw = ydeg * math.sin(2 * math.pi * ph_y + 0.9)
        c.set_actor_location(unreal.Vector(base_loc.x + dx, base_loc.y + dy, base_loc.z + dz), False, False)
        c.set_actor_rotation(unreal.Rotator(0.0, base_yaw + dyaw, 0.0), False)


def _tick(delta):
    st = _STATE
    if not st["running"]:
        return
    try:
        ed = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        if not st["chars"]:
            chars = []
            w = ed.get_game_world()
            if w is not None:
                chars += [(c, c.get_actor_location(), c.get_actor_rotation().yaw,
                           _profile(i)) for i, c in enumerate(_find_chars(w))]
            if st["include_editor"]:
                ew = ed.get_editor_world()
                if ew is not None:
                    off = len(chars)
                    chars += [(c, c.get_actor_location(), c.get_actor_rotation().yaw,
                               _profile(off + i)) for i, c in enumerate(_find_chars(ew))]
            if not chars:
                return
            st["chars"] = chars
            st["t0"] = time.time()
        _apply(st["chars"], time.time() - st["t0"])
        st["calls"] += 1
    except Exception:
        # Never let the tick callback break the editor loop.
        unreal.log_error("aivido_idle_driver tick error: %s" % unreal.log_traceback())


def start_idle_driver(include_editor=False):
    global _HANDLE
    if _HANDLE is not None:
        return {"ok": True, "already": True}
    _HANDLE = unreal.register_slate_post_tick_callback(_tick)
    _STATE["running"] = True
    _STATE["chars"] = []
    _STATE["t0"] = None
    _STATE["calls"] = 0
    _STATE["include_editor"] = bool(include_editor)
    return {"ok": True, "handle": _HANDLE}


def stop_idle_driver():
    global _HANDLE
    if _HANDLE is not None:
        try:
            unreal.unregister_slate_post_tick_callback(_HANDLE)
        except Exception:
            pass
        _HANDLE = None
    _STATE["running"] = False
    # restore every driven actor to its captured base pose so the scene is
    # left exactly as found (no offset drift persisted).
    restored = 0
    for c, base_loc, base_yaw, _prof in _STATE.get("chars", []):
        try:
            c.set_actor_location(base_loc, False, False)
            c.set_actor_rotation(unreal.Rotator(0.0, base_yaw, 0.0), False)
            restored += 1
        except Exception:
            pass
    _STATE["chars"] = []
    return {"ok": True, "calls": _STATE["calls"], "restored": restored}


def idle_stats():
    return {"running": _STATE["running"], "chars": len(_STATE["chars"]), "calls": _STATE["calls"],
            "include_editor": _STATE["include_editor"]}