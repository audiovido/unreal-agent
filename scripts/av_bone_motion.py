"""Bridge-side: detect actual bone motion on Heidi (true animation test)."""
import time

import unreal

out = {"samples": []}
heidi = None
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_Heidi":
        heidi = a
        break
comp = heidi.get_component_by_class(unreal.SkeletalMeshComponent)

bones = ["head", "hand_l", "hand_r", "spine_03"]
IDLE = unreal.load_asset("/Game/Mannequins/Anims/Unarmed/MM_Idle")

# ensure single-node + anim is set once more, then sample twice
comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
comp.call_method("SetAnimation", args=(IDLE,))
comp.call_method("SetPlayRate", args=(1.0,))
try:
    comp.call_method("Play", args=(True,))  # bLooping
except Exception:
    try:
        comp.call_method("PlayAnimation", args=(IDLE, True))
    except Exception:
        pass


def sample(tag):
    s = {"tag": tag, "t": round(time.monotonic() % 1000, 2)}
    for b in bones:
        try:
            loc = comp.get_socket_location(b)
            s[b] = [round(loc.x, 2), round(loc.z, 2)]
        except Exception as e:
            s[b] = "err:" + str(e)[:40]
    try:
        s["instance"] = comp.get_anim_instance() is not None
    except Exception:
        pass
    out["samples"].append(s)
    return s


sample("t0")
time.sleep(1.2)
sample("t1")
time.sleep(1.2)
sample("t2")

# motion verdict
try:
    a, b = out["samples"][0], out["samples"][-1]
    out["any_motion"] = any(
        isinstance(a[k], list) and a[k] != b[k] for k in bones
    )
except Exception:
    out["any_motion"] = "undetermined"

__bridge_result__ = out
