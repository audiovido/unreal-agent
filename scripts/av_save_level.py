"""Force-save the loaded showcase map and report dirty state.
Verifies the save path actually persists (checked on disk by the caller)."""
import unreal

map_name = unreal.EditorLevelLibrary.get_editor_world().get_path_name()

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
dirty_before = les.is_level_dirty() if hasattr(les, "is_level_dirty") else None
ok = les.save_current_level()
dirty_after = les.is_level_dirty() if hasattr(les, "is_level_dirty") else None

__bridge_result__ = {"map": map_name, "save_ok": bool(ok),
                     "dirty_before": dirty_before, "dirty_after": dirty_after}
