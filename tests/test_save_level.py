from tools.unreal.unreal_bridge import verify_save_result


def result(**overrides):
    value = {
        "ok": True,
        "map_before": "/Temp/Untitled_0.Untitled",
        "map_after": "/Game/Maps/TestLevel.TestLevel",
        "requested_asset_path": "/Game/Maps/TestLevel",
        "package_exists": True,
        "dirty_before": True,
        "dirty_after": False,
        "verified": True,
    }
    value.update(overrides)
    return {"ok": True, "result": value}


def test_valid_saved_level_dirty_before_clean_after_is_verified():
    assert verify_save_result(result()) is True


def test_temp_level_save_as_real_game_map_is_verified():
    assert verify_save_result(result()) is True
    assert "/Temp/Untitled_" not in result()["result"]["map_after"]


def test_api_success_cannot_override_dirty_after():
    assert verify_save_result(result(dirty_after=True, verified=False)) is False


def test_missing_map_path_is_not_verified():
    assert verify_save_result(result(map_after="/Temp/Untitled_0.Untitled", package_exists=False, verified=False)) is False


def test_failed_save_remains_failed():
    assert verify_save_result({"ok": False, "result": {"verified": False}}) is False


def test_repeated_identical_failure_is_not_success():
    failed = result(package_exists=False, dirty_after=True, verified=False, map_after="/Temp/Untitled_0.Untitled")
    assert verify_save_result(failed) is False
    assert verify_save_result(failed) is False


def test_persisted_map_contract_survives_restart_shape():
    saved = result(map_before="/Temp/Untitled_0.Untitled", map_after="/Game/Maps/TestLevel.TestLevel")
    restarted = {"ok": True, "result": dict(saved["result"])}
    assert verify_save_result(restarted) is True


def test_reopened_game_map_remains_valid():
    assert verify_save_result(result(map_before="/Game/Maps/TestLevel.TestLevel", map_after="/Game/Maps/TestLevel.TestLevel", dirty_before=False)) is True
