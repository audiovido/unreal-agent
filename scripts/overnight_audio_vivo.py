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
TASK_TIMEOUT_MIN = 18
POLL_SECONDS = 3
MAX_RETRIES_PER_TASK = 2

LOG_DIR = PROJECT / "Saved" / "UnrealAgent" / "Overnight"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOG_DIR / f"overnight_{RUN_ID}.log"
STATE_FILE = LOG_DIR / "overnight_state.json"

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
- Do not call open_project unless the Unreal bridge is genuinely disconnected
  and opening the known project is the only recovery.
- Never repeat an identical failed tool call.
- If one approach fails, inspect the evidence and use a different valid approach.
- Preserve existing working systems.
- Do not spend the task repeatedly inspecting the same state.
- Prefer implementation over commentary.
- Do not modify /Game/AgentTests unless explicitly required for diagnostics.
- Do not claim PASS without actual verification.
- Finish the requested milestone and return final.
"""

TASKS = [

COMMON_RULES + r"""
MILESTONE 1 ? COMPLETE PRODUCT/PROJECT AUDIT

Inspect the current project implementation and runtime architecture.

Inspect relevant:
- AVGameMode
- AVCityBlock
- AVPlayerController
- AVCameraPawn
- AVHUD
- AVVenueData
- project config/startup settings
- current map/runtime state

Determine what is already complete versus missing for a coherent playable
AudioVido Living City vertical slice.

Do not polish tiny visual details.

Fix only critical architecture/startup problems discovered during the audit.

Verify the project still opens and the intended GameMode/runtime systems are active.

RETURN:
work completed, files changed, blockers, verification, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 2 ? PLAYER MOVEMENT + CAMERA SYSTEM

Make the city reliably explorable.

Requirements:
- WASD movement works predictably.
- Mouse look works.
- camera movement is smooth enough for a product prototype.
- venue selection camera framing never places the camera inside geometry.
- all four venues can be framed.
- Back/Escape restores a safe overview/home camera.
- selecting venues repeatedly does not accumulate camera drift.
- preserve existing venue interaction behavior.

Inspect existing AVCameraPawn and AVPlayerController first, then implement.

Verify behavior using PIE/runtime evidence where possible.

RETURN:
files changed, movement behavior, camera behavior, verification,
remaining blockers, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 3 ? INTERACTION + ALL FOUR VENUES

Complete the core interaction loop for:
- LUMIERE CINEMA
- VELVET ROOM
- THE FORUM
- COMMON GROUND

Requirements:
- each venue can be selected reliably.
- each venue produces its own correct data/details.
- selection state is deterministic.
- Back clears selection and restores camera.
- repeated selection/back cycles remain stable.
- no venue should depend on accidental actor ordering.
- venue IDs/data should remain the source of truth.

Do not merely change text.

Verify all four venue flows.

RETURN:
files changed, interaction changes, four venue verification results,
remaining blockers, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 4 ? HUD / MENUS / BUTTONS / NAVIGATION

Turn the existing AVHUD into a coherent usable product UI.

Functional requirements:
- Welcome state works.
- Continue dismisses Welcome.
- Privacy control has a defined safe behavior.
- SPACES navigation visibly indicates selection/hover where practical.
- all four space entries are usable.
- venue detail panel displays the selected venue.
- Back works.
- Escape works.
- controls do not overlap at the target runtime viewport.
- buttons have clear hit regions and predictable input behavior.
- UI remains readable over the world.
- maintain AudioVido visual identity.

Focus on functionality and hierarchy, not endless pixel polish.

Verify Welcome, Main HUD, each venue detail, Back/Escape.

RETURN:
files changed, controls implemented, states verified,
remaining blockers, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 5 ? CITY STRUCTURE + VENUE READABILITY

Improve the actual procedural city so it reads as a small creative district,
not four anonymous cubes.

Preserve the existing runtime procedural architecture.

Requirements:
- distinguish the four venue silhouettes.
- make entrances/facades clearly identifiable.
- preserve venue accent identities.
- improve street/public-realm readability.
- ensure roads, cross street, lights and crowd elements are coherent.
- eliminate obvious geometry/camera collisions that damage venue framing.
- keep performance appropriate for a prototype.
- do not replace everything with an unrelated architecture.

Verify in PIE.

RETURN:
files changed, geometry changes, venue identity changes,
runtime verification, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 6 ? PRODUCT FLOW + EDGE CASES

Test and fix the complete user journey:

launch
? Welcome
? Continue
? explore city
? select venue
? read details
? Back
? select another venue
? repeat for all four
? Escape/home recovery

Fix:
- stale UI state
- duplicate actions
- broken clicks
- invalid selected venue states
- camera recovery issues
- unsafe null assumptions
- obvious runtime errors

Do not redesign systems that already work.

RETURN:
issues found, issues fixed, files changed,
journey verification, remaining blockers, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 7 ? FINAL ENGINEERING HARDENING

Perform an engineering pass over the completed vertical slice.

Look for:
- compile risks
- duplicated logic
- dangerous null access
- unstable initialization
- runtime actor duplication
- incorrect GameMode/startup assumptions
- interaction/camera state inconsistencies
- obviously dead prototype paths that interfere with the main experience

Make conservative fixes only.

Do not perform cosmetic churn.

RETURN:
files changed, engineering fixes, verification,
remaining blockers, PASS/PARTIAL/FAIL.
""",

COMMON_RULES + r"""
MILESTONE 8 ? FINAL RUNTIME VALIDATION

Do not add new features unless required to fix a validation failure.

Validate:
- Unreal bridge
- AVLC_Main
- PIE starts
- intended GameMode/player/HUD
- Welcome
- main HUD
- movement/camera
- four venue selection flows
- Back/Escape
- runtime city
- final screenshot evidence

Fix only blocking defects found during validation.

RETURN a final release-style report:
DONE
BLOCKED
KNOWN ISSUES
FILES CHANGED
RUNTIME EVIDENCE
FINAL STATUS
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
        timeout=30,
    )

    return result.get("task_id") or (
        result.get("data", {}).get("task_id")
    )


def events():
    try:
        return http_json("GET", "/api/events", timeout=10).get("events", [])
    except Exception:
        return []


def wait_for_task(task_id, timeout_minutes):
    deadline = time.time() + timeout_minutes * 60
    seen = set()

    while time.time() < deadline:
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
                return True, detail or title

            if status in (
                "failed",
                "error",
                "cancelled",
                "canceled",
            ):
                return False, detail or title

            if (
                etype == "error"
                and "terminated" in title.lower()
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

    run(["git", "add", "-A"], cwd=PROJECT, timeout=60)

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
