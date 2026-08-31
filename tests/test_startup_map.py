from tools.unreal.unreal_bridge import verify_startup_map_result


def test_startup_map_persistence_requires_config_verification():
    assert verify_startup_map_result({"ok": True, "result": {"startup_map": "/Game/Maps/Test", "config_verified": True}})


def test_startup_map_failure_is_not_success():
    assert not verify_startup_map_result({"ok": True, "result": {"startup_map": "/Temp/Untitled_0.Untitled", "config_verified": False}})


def test_startup_map_must_be_game_asset():
    assert not verify_startup_map_result({"ok": True, "result": {"startup_map": "/Temp/Untitled_0.Untitled", "config_verified": True}})
