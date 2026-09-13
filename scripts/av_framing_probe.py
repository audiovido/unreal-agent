"""Bridge-side: camera + character framing probe."""
import math

import unreal

out = {"cam": None, "chars": []}


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


cam = find("AIVIDO_HeroCamera")
if cam:
    loc = cam.get_actor_location()
    rot = cam.get_actor_rotation()
    fov = None
    try:
        cc = cam.get_cine_camera_component()
        fov = cc.get_editor_property("current_focal_length")
    except Exception:
        pass
    out["cam"] = {"pos": [round(loc.x), round(loc.y), round(loc.z)],
                  "yaw": round(rot.yaw, 1), "pitch": round(rot.pitch, 1),
                  "focal": fov}

for label in ("AIVIDO_Heidi", "AIVIDO_Worker01", "AIVIDO_Worker02", "AIVIDO_Worker03"):
    a = find(label)
    if a:
        loc = a.get_actor_location()
        rot = a.get_actor_rotation()
        out["chars"].append({"label": label,
                             "pos": [round(loc.x), round(loc.y), round(loc.z)],
                             "yaw": round(rot.yaw, 1)})

# framing math: angle of each char vs camera view axis
if out["cam"]:
    cx, cy = out["cam"]["pos"][0], out["cam"]["pos"][1]
    view_yaw = out["cam"]["yaw"]
    for c in out["chars"]:
        dx, dy = c["pos"][0] - cx, c["pos"][1] - cy
        ang = math.degrees(math.atan2(dy, dx))
        off = (ang - view_yaw + 180) % 360 - 180
        dist = math.hypot(dx, dy)
        c["offset_deg"] = round(off, 1)
        c["dist_cm"] = round(dist)

__bridge_result__ = out
