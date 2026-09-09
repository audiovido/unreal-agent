from __future__ import annotations

import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    def git(*args: str):
        return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True)
    git("init", "-q"); git("config", "user.name", "api-test"); git("config", "user.email", "api@test")
    (path / "README.md").write_text("base\n"); git("add", "."); git("commit", "-qm", "base")
    return path


def test_api_mission_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("YODAW_STATE_DIR", str(tmp_path / "state"))
    import importlib
    import yodaw.api as api
    api = importlib.reload(api)
    repo = make_repo(tmp_path / "repo")
    with TestClient(api.app) as client:
        assert client.get("/health").json() == {"api": "ready", "workers": "ready", "git": "ready"}
        assert client.get("/api/code/targets").json()["targets"][0]["name"] == "local"
        command = client.post("/api/code/command", json={"cwd": str(repo), "allowed_root": str(repo), "command":["python", "-c", "print('api-ok')"]})
        assert command.status_code == 200 and command.json()["stdout"].strip() == "api-ok"
        created = client.post("/api/code/missions", json={
            "repo": str(repo),
            "prompt": "Create a small feature touching multiple files, introduce a test failure, correct it automatically, run tests, commit and push.",
            "auto_commit": True,
        })
        assert created.status_code == 202
        mission_id = created.json()["mission_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            status = client.get(f"/api/code/missions/{mission_id}").json()
            if status["state"] in {"PASS", "FAILED", "BLOCKED", "CANCELLED"}:
                break
            time.sleep(.1)
        assert status["state"] == "PASS", status
        evidence = client.get(f"/api/code/missions/{mission_id}/evidence").json()
        assert evidence["evidence"] and evidence["evidence"][-1]["result"]["state"] == "PASS"
        assert (repo / "feature.py").exists() and (repo / "FEATURE.md").exists()
