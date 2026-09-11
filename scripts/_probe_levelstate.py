import unreal, traceback
out = {}
try:
    ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = ews.get_all_level_actors()
    out["actor_count"] = len(actors)
    labs = []
    for a in actors:
        try:
            labs.append(a.get_actor_label())
        except Exception:
            pass
    out["labeled"] = sorted(labs)[:100]
    # editor world lighting
    import unreal as u
    w = unreal.EditorLevelLibrary.get_editor_world()
    out["map"] = str(w.get_path_name()) if w else None
except Exception:
    out["error"] = traceback.format_exc()
out["done"] = True
__bridge_result__ = out
