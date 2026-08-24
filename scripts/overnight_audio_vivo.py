from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

AGENT = Path(r"C:\Users\Shadow\Desktop\Unreal-Agent")
PROJECT = Path(r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity")
UPROJECT = PROJECT / "AudioVidoLivingCity.uproject"

API = "http://127.0.0.1:8765"
BUILD_BAT = Path(
    r"C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat"
)

RUN_HOURS = 8.0
TASK_TIMEOUT_MIN = 12
POLL_SECONDS = 3
MAX_RETRIES_PER_TASK = 2

LOG_DIR = PROJECT / "Saved" / "UnrealAgent" / "Overnight"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOG_DIR / f"overnight_{RUN_ID}.log"
STATE_FILE = LOG_DIR / "overnight_state.json"
CONTROL_FILE = LOG_DIR / "overnight_control.json"

# ============================================================
# MISSION
# ============================================================

COMMON_RULES = r"""
PROJECT:
C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject

MAP:
/Game/AVLC_Main.AVLC_Main

OVERNIGHT AUTONOMOUS EXECUTION.

IMPORTANT:
- Work on the actual AudioVidoLivingCity project.
- Make real project improvements, not evaluation-only changes.
- Use registered Unreal Agent tools.
- Source files may be read and edited when required.
- Do not use visual_review_unreal.
- Do not call discover_projects.
- open_project is permitted ONLY as a recovery action when unreal_ping fails
  and the Unreal bridge is genuinely disconnected.
- When unreal_ping fails:
  1. check unreal_status once
  2. use open_project with the known AudioVidoLivingCity.uproject
  3. wait for the bridge
  4. retry unreal_ping
  5. continue the milestone after connection returns
- Never retry start_pie while unreal_ping is failing.
- Never repeat an identical failed tool call.
- If one approach fails, inspect the evidence and use a different valid approach.
- Preserve existing working systems.
- Do not spend the task repeatedly inspecting the same state.
- Prefer implementation over commentary.
- SOURCE TYPE SAFETY:
  * Files/classes under Source/AudioVidoLivingCity are native C++.
  * Inspect native .cpp/.h files with read_text_file.
  * NEVER call inspect_blueprint on AVGameMode, AVCityBlock,
    AVPlayerController, AVCameraPawn, AVHUD, or AVVenueData.
  * inspect_blueprint is ONLY for actual Blueprint assets under /Game.
  * A failed inspection tool is not a reason to abandon the milestone;
    recover with the correct registered tool and continue.
- Do not modify /Game/AgentTests unless explicitly required for diagnostics.
- Do not claim PASS without actual verification.
- Finish the requested milestone and return final.
"""

TASKS = [

COMMON_RULES + r"""
MILESTONE 01 ? STARTUP + ARCHITECTURE

Inspect AVGameMode, AVCityBlock, AVPlayerController, AVCameraPawn, AVHUD,
AVVenueData and startup config using read_text_file for native C++.

Confirm AVLC_Main launches with the intended GameMode, controller, pawn,
HUD and CityBlock. Fix concrete startup/initialization defects only.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 02 ? PLAYER MOVEMENT

Work only on AVCameraPawn movement/input.
Make WASD deterministic and usable.
Verify the implementation and PIE behavior where possible.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 03 ? CAMERA LOOK + HOME RESET

Work only on mouse look and ResetView/Home.
Prevent camera drift and invalid reset transforms.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 04 ? VENUE CAMERA FRAMING

Verify and fix framing for all four venues.
Camera must remain outside geometry.
Repeated select/back cycles must remain stable.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 05 ? VENUE DATA + SELECTION

Make selection deterministic for:
lumiere_cinema
velvet_room
the_forum
common_ground

Correct venue data must be shown.
Back clears selection.
Do not rely on actor ordering.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 06 ? WELCOME + MAIN HUD

Focus only on:
Welcome
Continue
SPACES navigation
button hit regions
main HUD state

Verify actual interaction.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 07 ? VENUE DETAIL UI + BACK

Verify selected venue detail data, Back and Escape for all four venues.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 08 ? PRIVACY + UI EDGE CASES

Give Privacy a defined safe behavior.
Fix stale UI state, duplicate clicks and invalid selection state only.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 09 ? CITY VENUE SILHOUETTES

Improve AVCityBlock so all four venues have distinct silhouettes,
entrances and identities without breaking the procedural architecture.

Do not modify camera or HUD systems.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 10 ? STREET + LIGHTS + PUBLIC REALM

Improve roads, cross street, lights, signage, crowd and public realm.
Keep prototype performance reasonable.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 11 ? COMPLETE PRODUCT FLOW

Verify and fix:
Welcome -> Continue -> movement -> venue -> details -> Back

Repeat for all four venues, then verify Escape/Home recovery.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 12 ? ENGINEERING HARDENING

Fix concrete:
null-safety issues
duplicate initialization
runtime actor duplication
state inconsistencies
compile risks

No cosmetic churn.

RETURN:
FINAL STATUS: PASS or FAIL
""",

COMMON_RULES + r"""
MILESTONE 13 ? FINAL RUNTIME VALIDATION

Validate:
bridge
AVLC_Main
PIE
movement
camera
Welcome
HUD
all four venue flows
Back/Escape
runtime city

Use capture_pie_viewport for evidence.
Do not use visual_review_unreal.

RETURN:
FINAL STATUS: PASS or FAIL
RUNTIME EVIDENCE:
...
""",

]


# ============================================================
# HELPERS
# ============================================================

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_json(method, path, body=None, timeout=20):
    data = None
    headers = {}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers=headers,
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def reset_agent():
    try:
        http_json("POST", "/api/reset", {})
        log("Agent reset OK")
        return True
    except Exception as exc:
        log(f"Agent reset failed: {exc}")
        return False


def ping_agent():
    try:
        result = http_json(
            "POST",
            "/api/action",
            {
                "action": "ping",
                "payload": {},
                "context": {},
            },
        )
        return bool(result.get("ok"))
    except Exception:
        return False


def launch_agent_task(prompt):
    result = http_json(
        "POST",
        "/api/action",
        {
            "action": "prompt",
            "payload": {"message": prompt},
            "context": {
                "project": {
                    "name": "AudioVidoLivingCity",
                    "path": str(PROJECT),
                },
                "provider": "Ollama",
                "language": "en",
            },
        },
        timeout=120,
    )

    return result.get("task_id") or (
        result.get("data", {}).get("task_id")
    )


def events():
    try:
        return http_json("GET", "/api/events", timeout=10).get("events", [])
    except Exception:
        return []



def final_result_is_real_success(value):
    text = str(value or "").lower()

    bad = (
        "cannot be completed",
        "could not be completed",
        "could not complete",
        "unable to proceed",
        "unable to complete",
        "could not proceed",
        "further investigation is required",
        "blocked",
        "final status: fail",
        "final status: partial",
        "status: fail",
        "status: partial",
        "not completed",
        "not complete",
        "verification failed",
        "could not verify",
        "unable to verify",
        "no venue-related actors found",
    )

    if any(x in text for x in bad):
        return False

    return (
        "final status: pass" in text
        or "status: pass" in text
    )


def wait_for_task(task_id, timeout_minutes):
    deadline = time.time() + timeout_minutes * 60
    seen = set()

    while time.time() < deadline:
        control_action = mission_control_gate()

        if control_action == "stop":
            reset_agent()
            return False, "Mission stopped from Unreal Agent UI"

        rows = [
            e for e in events()
            if e.get("task_id") == task_id
        ]

        for e in rows:
            eid = e.get("id")
            if eid in seen:
                continue

            seen.add(eid)

            title = str(e.get("title") or "")
            status = str(e.get("status") or "")
            etype = str(e.get("type") or "")

            log(f"AGENT {etype}/{status}: {title}")

        for e in reversed(rows):
            etype = str(e.get("type") or "").lower()
            status = str(e.get("status") or "").lower()
            title = str(e.get("title") or "")
            detail = e.get("detail")

            if etype in ("answer", "final") and status in (
                "success", "complete", "completed"
            ):
                final_value = detail or title

                if final_result_is_real_success(final_value):
                    return True, final_value

                return False, (
                    "Terminal response did not prove completion: "
                    + str(final_value)
                )

            # Individual tool errors are NOT terminal.
            # The Agent must be allowed to inspect the failure and recover.
            terminal_title = title.lower()

            if etype in ("answer", "final") and status in (
                "failed",
                "error",
                "cancelled",
                "canceled",
            ):
                return False, detail or title

            if etype == "error" and any(
                marker in terminal_title
                for marker in (
                    "background execution terminated",
                    "background execution crashed",
                    "background execution failed",
                    "background execution ended unexpectedly",
                )
            ):
                return False, detail or title

        time.sleep(POLL_SECONDS)

    return False, f"Task exceeded {timeout_minutes} minutes"


def run(cmd, cwd=None, timeout=None):
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=False,
    )

    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def git_status():
    code, out = run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT,
        timeout=30,
    )
    return code == 0, out


def build_project():
    log("BUILD starting")

    cmd = [
        str(BUILD_BAT),
        "AudioVidoLivingCityEditor",
        "Win64",
        "Development",
        str(UPROJECT),
        "-WaitMutex",
        "-FromMsBuild",
    ]

    try:
        code, out = run(
            cmd,
            cwd=PROJECT,
            timeout=20 * 60,
        )
    except subprocess.TimeoutExpired:
        log("BUILD timeout")
        return False, "Build timed out"

    tail = "\n".join(out.splitlines()[-35:])
    log("BUILD tail:\n" + tail)

    ok = code == 0 and "Result: Succeeded" in out

    return ok, tail


def git_checkpoint(index, title):
    ok, status = git_status()

    if not ok:
        return False, "git status failed"

    if not status.strip():
        log("No project changes to checkpoint")
        return True, "clean"

    run(
        [
            "git", "add", "-A",
            "--",
            ".",
            ":(exclude)Content/AgentTests/**",
            ":(exclude)Content/AAA_Workroom/**",
        ],
        cwd=PROJECT,
        timeout=60,
    )

    msg = f"Overnight {index:02d}: {title}"

    code, out = run(
        ["git", "commit", "-m", msg],
        cwd=PROJECT,
        timeout=120,
    )

    if code != 0 and "nothing to commit" not in out.lower():
        return False, out

    code, out = run(
        ["git", "push"],
        cwd=PROJECT,
        timeout=180,
    )

    if code != 0:
        return False, out

    log(f"GIT pushed: {msg}")
    return True, out


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )



def read_mission_control():
    try:
        return json.loads(
            CONTROL_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {
            "pause": False,
            "stop": False,
        }


def mission_control_gate():
    announced_pause = False

    while True:
        control = read_mission_control()

        if control.get("stop"):
            log("STOP requested from Unreal Agent UI")
            return "stop"

        if not control.get("pause"):
            if announced_pause:
                log("RESUME received from Unreal Agent UI")
            return "continue"

        if not announced_pause:
            log("PAUSED from Unreal Agent UI")
            announced_pause = True

        time.sleep(2)


# ============================================================
# MAIN
# ============================================================

def main():
    started = time.time()
    absolute_deadline = started + RUN_HOURS * 3600

    state = {
        "run_id": RUN_ID,
        "started": datetime.now().isoformat(),
        "tasks": [],
    }

    log("=" * 72)
    log("AUDIOVIDO OVERNIGHT MISSION START")
    log(f"Maximum mission window: {RUN_HOURS} hours")
    log("=" * 72)

    if not ping_agent():
        log("FATAL: Unreal Agent API is not reachable.")
        return 2

    for index, task in enumerate(TASKS, 1):
        control_action = mission_control_gate()

        if control_action == "stop":
            log("Mission stopped by user.")
            break

        if time.time() >= absolute_deadline:
            log("Mission deadline reached.")
            break

        title_line = next(
            (
                line.strip()
                for line in task.splitlines()
                if line.strip().startswith("MILESTONE")
            ),
            f"MILESTONE {index}",
        )

        record = {
            "index": index,
            "title": title_line,
            "attempts": [],
            "status": "PENDING",
        }

        state["tasks"].append(record)
        save_state(state)

        log("")
        log("=" * 72)
        log(title_line)
        log("=" * 72)

        task_success = False

        for attempt in range(1, MAX_RETRIES_PER_TASK + 1):
            if time.time() >= absolute_deadline:
                break

            log(f"Attempt {attempt}/{MAX_RETRIES_PER_TASK}")

            reset_agent()
            time.sleep(1)

            try:
                task_id = launch_agent_task(task)
            except Exception as exc:
                log(f"Launch failed: {exc}")
                record["attempts"].append({
                    "attempt": attempt,
                    "ok": False,
                    "result": f"launch failed: {exc}",
                })
                continue

            if not task_id:
                log("No task_id returned")
                continue

            log(f"Task ID: {task_id}")

            ok, result = wait_for_task(
                task_id,
                TASK_TIMEOUT_MIN,
            )

            record["attempts"].append({
                "attempt": attempt,
                "ok": ok,
                "result": str(result)[:6000],
            })
            save_state(state)

            if ok:
                task_success = True
                break

            log(f"Task failed/blocked: {result}")
            reset_agent()
            time.sleep(2)

        if not task_success:
            record["status"] = "BLOCKED"
            log("Milestone BLOCKED ? continuing to next milestone.")
            save_state(state)
            continue

        # Build gate.
        build_ok, build_result = build_project()
        record["build_ok"] = build_ok
        record["build_result"] = build_result

        if not build_ok:
            record["status"] = "BUILD_FAILED"
            log(
                "Build failed. Changes are NOT committed. "
                "Continuing to next milestone for possible recovery."
            )
            save_state(state)
            continue

        # Git checkpoint only after a successful build.
        git_ok, git_result = git_checkpoint(
            index,
            title_line.replace("MILESTONE ", "").replace("?", "-")[:60],
        )

        record["git_ok"] = git_ok
        record["git_result"] = git_result
        record["status"] = "DONE" if git_ok else "GIT_FAILED"

        save_state(state)

        # Brief cool-down for Unreal/Ollama.
        time.sleep(5)

    # Final build regardless of individual task outcomes.
    log("")
    log("=" * 72)
    log("FINAL BUILD")
    log("=" * 72)

    final_build_ok, final_build = build_project()

    state["finished"] = datetime.now().isoformat()
    state["elapsed_hours"] = round((time.time() - started) / 3600, 2)
    state["final_build_ok"] = final_build_ok
    state["final_build"] = final_build
    save_state(state)

    done = sum(1 for x in state["tasks"] if x.get("status") == "DONE")
    blocked = [
        x["title"]
        for x in state["tasks"]
        if x.get("status") != "DONE"
    ]

    log("")
    log("=" * 72)
    log("OVERNIGHT MISSION FINISHED")
    log(f"DONE: {done}/{len(state['tasks'])}")
    log(f"FINAL BUILD: {'PASS' if final_build_ok else 'FAIL'}")

    if blocked:
        log("NOT DONE:")
        for x in blocked:
            log(" - " + x)

    log(f"State: {STATE_FILE}")
    log(f"Log:   {LOG_FILE}")
    log("=" * 72)

    return 0 if final_build_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
