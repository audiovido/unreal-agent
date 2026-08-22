from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
asset_path = "/Game/AgentTests/BP_AgentSmoke"

bp = unreal.EditorAssetLibrary.load_asset(asset_path)

if bp is None:
    __bridge_result__ = {
        "ok": False,
        "error": "Blueprint not found"
    }
else:
    events_before = unreal.BlueprintEditorLibrary.list_events(bp)

    begin_play = unreal.BlueprintEditorLibrary.add_event_override(
        bp,
        "ReceiveBeginPlay",
        unreal.IntPoint(0, 0)
    )

    if begin_play is None:
        __bridge_result__ = {
            "ok": False,
            "error": "Could not create ReceiveBeginPlay event"
        }
    else:
        outputs = begin_play.list_output_pins()
        inputs = begin_play.list_input_pins()

        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        saved = unreal.EditorAssetLibrary.save_loaded_asset(bp, False)

        __bridge_result__ = {
            "ok": True,
            "asset_path": asset_path,
            "node_title": begin_play.get_node_title(),
            "node_pos": str(begin_play.get_node_pos()),

            "inputs": [
                {
                    "name": str(p.get_pin_name()),
                    "type": str(p.get_pin_type_display_string())
                }
                for p in inputs
            ],

            "outputs": [
                {
                    "name": str(p.get_pin_name()),
                    "type": str(p.get_pin_type_display_string())
                }
                for p in outputs
            ],

            "then_pin_found":
                begin_play.find_then_pin() is not None,

            "saved": bool(saved)
        }
'''

pprint.pp(b.execute_python(code), width=150)
