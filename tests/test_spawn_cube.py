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

pprint.pp(UnrealBridge().execute_python(code))
