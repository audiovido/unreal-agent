"""Decisive liveness probe: skylight 0.55 -> 6.0 is visible from ANY camera pose.
Pairs with av_global_probe_off.py (restore + second capture)."""
import unreal

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
sky = None
for a in ews.get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_SkyLight":
        sky = a
        break
sc = sky.get_component_by_class(unreal.SkyLightComponent)
orig = float(sc.get_editor_property("intensity"))
sc.set_editor_property("intensity", 6.0)
__bridge_result__ = {"skylight_orig": orig, "now": float(sc.get_editor_property("intensity"))}
