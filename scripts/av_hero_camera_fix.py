"""PERMANENT HERO CAMERA FIX (tasks 1-2 of the foreground-capture mission).

AIVIDO_HeroCamera was recorded outside the room (loc -950,-420,235; front wall
spans X -913..-863) staring at the unlit wall exterior. This moves it to the
verified interior wide pose (-820,-350,270 / pitch -10 / yaw 0) which frames:
  Heidi (-28.8deg), W02 (+10), W03 (+2.2), W01 (+26.4), dais core (+23.1),
  UA/AU/AV stations. The empty ASSET station (+70) stays out of the hero frame.

Also keeps the AIVIDO_VCam SceneCapture2D twin in the same pose so any future
render-target use matches the hero view, then saves the map.
Before-transforms are printed so the change is reversible.
"""
import unreal

BEFORE = {}

NEW_LOC = unreal.Vector(-820.0, -350.0, 270.0)
NEW_ROT = unreal.Rotator(roll=0.0, pitch=-10.0, yaw=0.0)  # explicit kwargs: this
# build's positional Rotator order is (roll, pitch, yaw); kwargs are unambiguous.

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = ews.get_all_level_actors()

targets = {}
for a in actors:
    lbl = a.get_actor_label()
    if lbl in ("AIVIDO_HeroCamera", "AIVIDO_VCam"):
        targets[lbl] = a

for lbl, a in targets.items():
    loc = a.get_actor_location()
    rot = a.get_actor_rotation()
    BEFORE[lbl] = {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                   "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}
    a.set_actor_location(NEW_LOC, False, False)
    a.set_actor_rotation(NEW_ROT, False)

# verify readback
AFTER = {}
for lbl, a in targets.items():
    loc = a.get_actor_location()
    rot = a.get_actor_rotation()
    AFTER[lbl] = {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                  "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}

saved = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, False)

__bridge_result__ = {"before": BEFORE, "after": AFTER,
                     "map_saved": bool(saved),
                     "missing": [l for l in ("AIVIDO_HeroCamera", "AIVIDO_VCam")
                                 if l not in targets]}
