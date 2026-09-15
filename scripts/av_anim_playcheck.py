"""Bridge-side: prove/disprove live idle playback via position sampling."""
import time

import unreal

out = {}
heidi = None
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_Heidi":
        heidi = a
        break
comp = heidi.get_component_by_class(unreal.SkeletalMeshComponent)


def snap():
    d = {}
    for prop in ("position", "play_rate", "playing", "is_playing"):
        try:
            d[prop] = comp.get_editor_property(prop)
        except Exception:
            pass
    try:
        d["mono_time"] = time.monotonic()
    except Exception:
        pass
    return d


out["before"] = snap()
time.sleep(1.5)
out["after"] = snap()
out["position_advanced"] = out["before"].get("position") != out["after"].get("position")

# also try the anim instance object
try:
    ai = comp.get_anim_instance()
    out["anim_instance"] = str(ai.get_class().get_name()) if ai else None
    if ai:
        try:
            cur = ai.get_current_active_transition() if hasattr(ai, "get_current_active_transition") else None
        except Exception:
            pass
except Exception as e:
    out["ai_err"] = str(e)[:100]

__bridge_result__ = out
