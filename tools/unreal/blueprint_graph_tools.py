from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class BlueprintGraphTools:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge


    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(value)


    def add_event_override(
        self,
        asset_path: str,
        event_name: str,
        x: int = 0,
        y: int = 0,
    ) -> Dict[str, Any]:

        a = self._q(asset_path)
        e = self._q(event_name)

        return self.bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset({a})

if bp is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint not found"
    }}
else:
    node = unreal.BlueprintEditorLibrary.add_event_override(
        bp,
        {e},
        unreal.IntPoint({int(x)}, {int(y)})
    )

    __bridge_result__ = {{
        "ok": node is not None,
        "title": node.get_node_title() if node else None,
        "position": str(node.get_node_pos()) if node else None,
        "outputs": [
            str(p.get_pin_name())
            for p in node.list_output_pins()
        ] if node else []
    }}
''')


    def add_call_function_node(
        self,
        asset_path: str,
        graph_name: str,
        function_class_path: str,
        function_name: str,
        x: int = 350,
        y: int = 0,
    ) -> Dict[str, Any]:

        a = self._q(asset_path)
        g = self._q(graph_name)
        c = self._q(function_class_path)
        f = self._q(function_name)

        return self.bridge.execute_python(f'''
node = unreal.UnrealAgentBlueprintLibrary.add_call_function_node(
    {a},
    {g},
    {c},
    {f},
    {int(x)},
    {int(y)}
)

__bridge_result__ = {{
    "ok": node is not None,
    "title": node.get_node_title() if node else None,
    "inputs": [
        {{
            "name": str(p.get_pin_name()),
            "type": str(p.get_pin_type_display_string())
        }}
        for p in node.list_input_pins()
    ] if node else [],
    "outputs": [
        {{
            "name": str(p.get_pin_name()),
            "type": str(p.get_pin_type_display_string())
        }}
        for p in node.list_output_pins()
    ] if node else []
}}
''')


    def connect_pins(
        self,
        asset_path: str,
        graph_name: str,
        from_node_title: str,
        from_pin: str,
        to_node_title: str,
        to_pin: str,
    ) -> Dict[str, Any]:

        values = [
            self._q(asset_path),
            self._q(graph_name),
            self._q(from_node_title),
            self._q(from_pin),
            self._q(to_node_title),
            self._q(to_pin),
        ]

        return self.bridge.execute_python(f'''
connected = unreal.UnrealAgentBlueprintLibrary.connect_pins_by_title(
    {values[0]},
    {values[1]},
    {values[2]},
    {values[3]},
    {values[4]},
    {values[5]}
)

__bridge_result__ = {{
    "ok": bool(connected),
    "connected": bool(connected)
}}
''')


    def set_pin_default(
        self,
        asset_path: str,
        graph_name: str,
        node_title: str,
        pin_name: str,
        value: str,
    ) -> Dict[str, Any]:

        return self.bridge.execute_python(f'''
changed = unreal.UnrealAgentBlueprintLibrary.set_pin_default_value_by_title(
    {self._q(asset_path)},
    {self._q(graph_name)},
    {self._q(node_title)},
    {self._q(pin_name)},
    {self._q(value)}
)

__bridge_result__ = {{
    "ok": bool(changed),
    "changed": bool(changed)
}}
''')


    def compile_save(
        self,
        asset_path: str,
    ) -> Dict[str, Any]:

        return self.bridge.execute_python(f'''
saved = unreal.UnrealAgentBlueprintLibrary.compile_and_save_blueprint(
    {self._q(asset_path)}
)

__bridge_result__ = {{
    "ok": bool(saved),
    "saved": bool(saved)
}}
''')


    def list_graph_nodes(
        self,
        asset_path: str,
        graph_name: str = "EventGraph",
    ) -> Dict[str, Any]:

        return self.bridge.execute_python(f'''
nodes = unreal.UnrealAgentBlueprintLibrary.list_graph_nodes(
    {self._q(asset_path)},
    {self._q(graph_name)}
)

__bridge_result__ = {{
    "ok": True,
    "nodes": [str(x) for x in nodes]
}}
''')


    def delete_node(
        self,
        asset_path: str,
        graph_name: str,
        node_title: str,
    ) -> Dict[str, Any]:

        return self.bridge.execute_python(f"""
deleted = unreal.UnrealAgentBlueprintLibrary.delete_node_by_title(
    {self._q(asset_path)},
    {self._q(graph_name)},
    {self._q(node_title)}
)

__bridge_result__ = {{
    "ok": bool(deleted),
    "deleted": bool(deleted),
    "node_title": {self._q(node_title)}
}}
""")


    def build_beginplay_print(
        self,
        asset_path: str,
        message: str = "Unreal Agent graph bridge OK",
    ) -> Dict[str, Any]:

        a = self._q(asset_path)
        m = self._q(message)

        return self.bridge.execute_python(f"""
asset_path = {a}
message = {m}

bp = unreal.EditorAssetLibrary.load_asset(asset_path)

if bp is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint not found",
        "mutated": False
    }}
else:
    nodes_before = [
        str(x)
        for x in unreal.UnrealAgentBlueprintLibrary.list_graph_nodes(
            asset_path,
            "EventGraph"
        )
    ]

    def _norm(value):
        return "".join(
            ch.lower()
            for ch in str(value)
            if ch.isalnum()
        )

    begin_titles = [
        x for x in nodes_before
        if "beginplay" in _norm(x)
    ]

    print_titles = [
        x for x in nodes_before
        if "printstring" in _norm(x)
    ]

    # Critical safety rule:
    # never create another BeginPlay when duplicates already exist.
    if len(begin_titles) > 1:
        __bridge_result__ = {{
            "ok": False,
            "error": "duplicate_beginplay_requires_cleanup",
            "beginplay_count": len(begin_titles),
            "printstring_count": len(print_titles),
            "nodes": nodes_before,
            "mutated": False
        }}

    # Existing PrintString is ambiguous because title-only graph APIs
    # cannot prove its message. Refuse instead of overwriting user logic.
    elif len(print_titles) > 0:
        __bridge_result__ = {{
            "ok": False,
            "error": "existing_printstring_requires_explicit_resolution",
            "beginplay_count": len(begin_titles),
            "printstring_count": len(print_titles),
            "nodes": nodes_before,
            "mutated": False
        }}

    else:
        if len(begin_titles) == 0:
            begin = unreal.BlueprintEditorLibrary.add_event_override(
                bp,
                "ReceiveBeginPlay",
                unreal.IntPoint(0, 0)
            )

            if begin is None:
                __bridge_result__ = {{
                    "ok": False,
                    "error": "Could not create BeginPlay",
                    "mutated": False
                }}
            else:
                begin_title = str(begin.get_node_title())
        else:
            begin_title = begin_titles[0]

        if "__bridge_result__" not in globals():
            call = unreal.UnrealAgentBlueprintLibrary.add_call_function_node(
                asset_path,
                "EventGraph",
                "/Script/Engine.KismetSystemLibrary",
                "PrintString",
                350,
                0
            )

            if call is None:
                __bridge_result__ = {{
                    "ok": False,
                    "error": "Could not create PrintString",
                    "mutated": True
                }}

            else:
                call_title = str(call.get_node_title())

                connected = bool(
                    unreal.UnrealAgentBlueprintLibrary.connect_pins_by_title(
                        asset_path,
                        "EventGraph",
                        begin_title,
                        "then",
                        call_title,
                        "execute"
                    )
                )

                string_pin = None

                for pin in call.list_input_pins():
                    pin_name = str(pin.get_pin_name())
                    low = pin_name.lower()

                    if low in ("instring", "string") or "string" in low:
                        string_pin = pin_name
                        break

                default_set = False

                if string_pin:
                    default_set = bool(
                        unreal.UnrealAgentBlueprintLibrary.set_pin_default_value_by_title(
                            asset_path,
                            "EventGraph",
                            call_title,
                            string_pin,
                            message
                        )
                    )

                saved = bool(
                    unreal.UnrealAgentBlueprintLibrary.compile_and_save_blueprint(
                        asset_path
                    )
                )

                nodes_after = [
                    str(x)
                    for x in unreal.UnrealAgentBlueprintLibrary.list_graph_nodes(
                        asset_path,
                        "EventGraph"
                    )
                ]

                begin_after = [
                    x for x in nodes_after
                    if "beginplay" in _norm(x)
                ]

                print_after = [
                    x for x in nodes_after
                    if "printstring" in _norm(x)
                ]

                __bridge_result__ = {{
                    "ok": bool(
                        connected
                        and default_set
                        and saved
                        and len(begin_after) == 1
                        and len(print_after) == 1
                    ),
                    "connected": connected,
                    "default_set": default_set,
                    "saved": saved,
                    "beginplay_count": len(begin_after),
                    "printstring_count": len(print_after),
                    "begin_title": begin_title,
                    "call_title": call_title,
                    "nodes": nodes_after,
                    "mutated": True
                }}
""")

