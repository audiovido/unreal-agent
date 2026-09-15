# >>> UNREAL_AGENT_ASSET_BRIDGE >>>
import socket as _ua_socket
import traceback as _ua_traceback
import unreal as _ua_unreal
_ua_listener = r"C:\Users\Shadow\Desktop\Unreal-Agent\assetlib\tests\ue\ASSET_Showcase2\Content\Python\ue_listener_asset.py"
_ua_host = "127.0.0.1"
_ua_port = 6766
_ua_expected_project = r"C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/ASSET_Showcase2/ASSET_Showcase2.uproject"
_ua_tick_handle = None
_ua_state = {"started": False, "source": None, "error": None}


def _ua_port_open():
    s = _ua_socket.socket(_ua_socket.AF_INET, _ua_socket.SOCK_STREAM)
    s.settimeout(.2)
    try:
        return s.connect_ex((_ua_host, _ua_port)) == 0
    finally:
        s.close()


def _ua_start_bridge(_delta=0.0):
    global _ua_tick_handle
    actual = str(_ua_unreal.Paths.get_project_file_path()).replace(chr(92), "/")
    if actual.lower() != _ua_expected_project.lower():
        _ua_unreal.log_error("WRONG_PROJECT_CONTEXT: " + actual)
        return
    if _ua_state["started"] and _ua_port_open():
        return
    if _ua_port_open():
        _ua_state["started"] = True
        return
    try:
        with open(_ua_listener, "r", encoding="utf-8-sig") as f:
            src = f.read()
        ns = {"__name__": "__main__", "__file__": _ua_listener, "PORT": _ua_port}
        exec(compile(src, _ua_listener, "exec"), ns, ns)
        _ua_state.update({"started": True, "source": ns, "error": None})
    except Exception:
        _ua_state["error"] = _ua_traceback.format_exc()
        _ua_unreal.log_error("ASSET bridge startup failed:\n" + _ua_state["error"])


try:
    _ua_tick_handle = _ua_unreal.register_slate_post_tick_callback(_ua_start_bridge)
except Exception:
    _ua_start_bridge(0.0)
# <<< UNREAL_AGENT_ASSET_BRIDGE <<<