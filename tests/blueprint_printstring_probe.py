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
    begin_play = unreal.BlueprintEditorLibrary.add_event_override(
        bp,
        "ReceiveBeginPlay",
        unreal.IntPoint(0, 0)
    )

    graph = unreal.BlueprintEditorLibrary.find_event_graph(bp)

    if begin_play is None or graph is None:
        __bridge_result__ = {
            "ok": False,
            "error": "BeginPlay or EventGraph not found"
        }
    else:
        call_node = unreal.new_object(
            unreal.K2Node_CallFunction,
            outer=graph,
            name="AgentPrintString"
        )

        # Try common function-reference properties.
        set_ok = False
        set_errors = []

        for prop, value in [
            ("function_reference", None),
            ("function_name", "PrintString"),
        ]:
            try:
                if value is not None:
                    call_node.set_editor_property(prop, value)
                    set_ok = True
            except Exception as exc:
                set_errors.append(f"{prop}: {exc}")

        # Inspect whether pins were allocated.
        inputs = call_node.list_input_pins()
        outputs = call_node.list_output_pins()

        begin_then = begin_play.find_then_pin()
        call_exec = call_node.find_execute_pin()

        connected = False
        can_connect = False

        if begin_then is not None and call_exec is not None:
            can_connect = begin_then.can_create_connection(call_exec)

            if can_connect:
                connected = begin_then.try_create_connection(call_exec)

        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        saved = unreal.EditorAssetLibrary.save_loaded_asset(bp, False)

        __bridge_result__ = {
            "ok": True,
            "set_ok": set_ok,
            "set_errors": set_errors,
            "node_title": call_node.get_node_title(),
            "input_pins": [
                {
                    "name": str(p.get_pin_name()),
                    "type": str(p.get_pin_type_display_string())
                }
                for p in inputs
            ],
            "output_pins": [
                {
                    "name": str(p.get_pin_name()),
                    "type": str(p.get_pin_type_display_string())
                }
                for p in outputs
            ],
            "begin_then_found": begin_then is not None,
            "call_exec_found": call_exec is not None,
            "can_connect": can_connect,
            "connected": connected,
            "saved": bool(saved)
        }
'''

pprint.pp(b.execute_python(code), width=150)
