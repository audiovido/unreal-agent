from tools.unreal.unreal_bridge import UnrealBridge
import pprint

code = r'''
mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

a = sub.spawn_actor_from_class(
    unreal.StaticMeshActor,
    unreal.Vector(0, 0, 100)
)

a.static_mesh_component.set_static_mesh(mesh)
a.set_actor_label("Agent_Test_Cube")

__bridge_result__ = {
    "ok": True,
    "name": a.get_name(),
    "label": a.get_actor_label()
}
'''

pprint.pp(UnrealBridge().execute_python(code))
