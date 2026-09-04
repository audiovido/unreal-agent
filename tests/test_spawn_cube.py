from tools.unreal.unreal_bridge import UnrealBridge
import pprint

code = '''
actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.StaticMeshActor,
    unreal.Vector(0, 0, 100)
)
mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
actor.static_mesh_component.set_static_mesh(mesh)
actor.set_actor_label("Agent_Test_Cube")

__bridge_result__ = {
    "ok": True,
    "actor": actor.get_actor_label(),
    "mesh": mesh.get_name()
}
'''

# Manual live-editor probe, NOT a pytest test.  The spawn must only run when
# executed directly as a script: pytest imports this module during collection,
# and module-level bridge calls would mutate the live editor with no isolation
# guard coverage (the guard patches _send at test-execution time, after import).
if __name__ == "__main__":
    pprint.pp(UnrealBridge().execute_python(code))
