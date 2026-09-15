"""Bridge-side: force-tick pose and measure bone motion (binding proof)."""
import time

import unreal

out = {"samples": []}
heidi = None
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_Heidi":
        heidi = a
        break
comp = heidi.get_component_by_class(unreal.SkeletalMeshComponent)
IDLE = unreal.load_asset("/Game/Mannequins/Anims/Unarmed/MM_Idle")

comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
comp.call_method("SetAnimation", args=(IDLE,))
comp.call_method("SetPosition", args=(0.0,))
comp.call_method("Play", args=(True,))

bones = ["head", "hand_l", "hand_r"]


def sample(tag):
    s = {"tag": tag}
    for b in bones:
        loc = comp.get_socket_location(b)
        s[b] = [round(loc.x, 2), round(loc.z, 2)]
    out["samples"].append(s)


sample("t0")
out["tickpose_err"] = []
for i in range(12):
    try:
        comp.call_method("TickPose", args=(0.033, True))
    except Exception as e:
        out["tickpose_err"].append(str(e)[:80])
        break
    time.sleep(0.05)
sample("t1")

try:
    a, b = out["samples"]
    out["any_motion"] = any(a[k] != b[k] for k in bones)
except Exception:
    out["any_motion"] = "undetermined"

out["tick_err_count"] = len(out["tickpose_err"])

__bridge_result__ = out
