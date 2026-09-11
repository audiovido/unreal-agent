import sys
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.unreal.unreal_bridge import UnrealBridge

LABEL = "TERMINAL_STATE_FINAL_TEST"


def main():
    b = UnrealBridge(timeout=30)
    code = (
        "subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\n"
        "actors = unreal.EditorLevelLibrary.get_all_level_actors()\n"
        f"target = \"{LABEL}\"\n"
        "removed = 0\n"
        "for a in list(actors):\n"
        "    if a.get_actor_label() == target:\n"
        "        subsystem.destroy_actor(a)\n"
        "        removed += 1\n"
        "__bridge_result__ = {'ok': True, 'removed': removed}\n"
    )
    result = b.execute_python(code)
    print("CLEANUP_RESULT:", result)

    # Verify: count remaining actors with that label.
    verify = (
        "actors = unreal.EditorLevelLibrary.get_all_level_actors()\n"
        f"target = \"{LABEL}\"\n"
        "__bridge_result__ = {'ok': True, 'remaining': sum(1 for a in actors if a.get_actor_label() == target)}\n"
    )
    print("VERIFY_RESULT:", b.execute_python(verify))


if __name__ == "__main__":
    main()