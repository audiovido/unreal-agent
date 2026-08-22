from pathlib import Path
import re
import shutil
import time

ROOT = Path(r"C:\Users\Shadow\Desktop\Unreal-Agent")
ORCH = ROOT / "core" / "orchestrator.py"
API  = ROOT / "app" / "api.py"

stamp = time.strftime("%Y%m%d_%H%M%S")

orch_backup = ORCH.with_name(f"orchestrator.pre_heavy_{stamp}.py")
api_backup  = API.with_name(f"api.pre_heavy_{stamp}.py")

shutil.copy2(ORCH, orch_backup)
shutil.copy2(API, api_backup)

orch = ORCH.read_text(encoding="utf-8-sig")
api = API.read_text(encoding="utf-8-sig")


# ============================================================
# ORCHESTRATOR: Heavy model config
# ============================================================

heavy_config = '''
# ============================================================
# HEAVY SPECIALIST v3
# ============================================================

HEAVY_MODEL = os.getenv(
    "UNREAL_AGENT_HEAVY_MODEL",
    "unreal-coder:latest",
)

HEAVY_MODEL_AVAILABLE = (
    HEAVY_MODEL in AVAILABLE_MODELS
)
'''

if "HEAVY_MODEL_AVAILABLE" not in orch:

    anchor = "MODEL = CODER_MODEL"

    if anchor not in orch:
        raise RuntimeError(
            "Could not find MODEL = CODER_MODEL anchor."
        )

    orch = orch.replace(
        anchor,
        anchor + "\n" + heavy_config,
        1,
    )


# ============================================================
# Heavy task intelligence
# ============================================================

heavy_router = r'''
# ============================================================
# HEAVY TASK ROUTER
# ============================================================

def should_use_heavy(task):

    text = str(task).lower()

    strong_terms = (
        "c++ crash",
        "access violation",
        "segmentation",
        "memory corruption",
        "engine source",
        "unrealbuildtool",
        "build.cs",
        "target.cs",
        "linker error",
        "link error",
        "shader compiler",
        "hlsl",
        "usf",
        "ush",
        "rendering pipeline",
        "rhi",
        "replication architecture",
        "network prediction",
        "mass entity",
        "gameplay ability system",
        "gas architecture",
        "plugin architecture",
        "module architecture",
        "large refactor",
        "performance profiling",
        "memory leak",
        "race condition",
        "multithread",
        "thread safety",
        "کرش",
        "پلاگین",
        "شیدر",
        "لینکر",
        "مموری لیک",
        "رفکتور سنگین",
        "معماری سی پلاس پلاس",
        "سی پلاس پلاس پیچیده",
        "پرفورمنس سنگین",
    )

    if any(term in text for term in strong_terms):
        return True

    prompt = """
You route complex Unreal Engine engineering work.

Decide whether this task deserves the very slow
HEAVY Unreal specialist model.

Use HEAVY only for genuinely difficult work such as:
- complex Unreal C++
- plugins/modules
- engine-level crashes
- difficult build/link errors
- shaders/rendering
- deep performance debugging
- memory/threading bugs
- large architecture/refactors
- difficult networking/replication systems

Do NOT use HEAVY for:
- normal conversation
- planning a game
- level editing
- spawning/moving actors
- normal Blueprint work
- simple Python
- routine Unreal operations
- ordinary coding

Return JSON only:

{
  "heavy": true,
  "reason": "short reason"
}
"""

    try:

        raw = call_model(
            [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": str(task),
                },
            ],
            model=FAST_MODEL,
            json_mode=True,
            temperature=0,
            num_ctx=4096,
            timeout=120,
        )

        data = json.loads(raw)

        return bool(
            data.get("heavy", False)
        )

    except Exception:
        return False
'''

if "def should_use_heavy(task):" not in orch:

    anchor = (
        "# ============================================================\n"
        "# EXECUTION PLANNER\n"
        "# ============================================================"
    )

    if anchor not in orch:
        raise RuntimeError(
            "Could not find EXECUTION PLANNER section."
        )

    orch = orch.replace(
        anchor,
        heavy_router + "\n\n" + anchor,
        1,
    )


# ============================================================
# Replace execution planner
# Heavy = senior advisor
# Qwen3 14B = structured planner
# ============================================================

new_plan = r'''def create_execution_plan(task):

    use_heavy = (
        HEAVY_MODEL_AVAILABLE
        and should_use_heavy(task)
    )

    specialist_advice = ""

    if use_heavy:

        specialist_prompt = f"""
You are the HEAVY senior Unreal Engine specialist.

Analyze this difficult engineering task deeply.

USER TASK:
{task}

AVAILABLE TOOL NAMES:
{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

You are an ADVISOR, not the tool executor.

Provide:
- root technical interpretation
- architecture
- likely failure modes
- Unreal-specific constraints
- safest implementation strategy
- verification strategy
- recovery alternatives

Important:
- Never pretend execution occurred.
- Never invent available tools.
- Levels are not Blueprints.
- Prefer robust Unreal Engine 5.8 engineering.
"""

        try:

            specialist_advice = call_model(
                [
                    {
                        "role": "system",
                        "content": specialist_prompt,
                    }
                ],
                model=HEAVY_MODEL,
                json_mode=False,
                temperature=0.05,
                num_ctx=8192,
                timeout=900,
            )

        except Exception as exc:

            specialist_advice = (
                "HEAVY SPECIALIST FAILED: "
                f"{type(exc).__name__}: {exc}. "
                "Continue using the reasoning model."
            )

    planner = f"""
You are the planning brain of an autonomous
Unreal Engine engineering agent.

USER TASK:

{task}

HEAVY SPECIALIST ADVICE:

{specialist_advice if specialist_advice else "Not required for this task."}

REAL AVAILABLE TOOL NAMES:

{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

Create an execution strategy.

Important:

- Never invent a tool.
- A Level/Map is NOT a Blueprint.
- Blueprint compile tools must never receive Level/Map paths.
- Large creative tasks require many steps.
- Do not stop after one tiny action.
- Inspect real state first when appropriate.
- Every mutation must later be independently verified.
- Recover from failed tool calls.
- Prefer an alternate valid approach instead of repeating
  the exact same failed call.
- Use the HEAVY specialist advice when present,
  but only use tools that actually exist.

Return JSON only:

{{
  "goal": "...",
  "steps": [
    "...",
    "..."
  ],
  "success_criteria": [
    "...",
    "..."
  ],
  "risks": [
    "..."
  ]
}}
"""

    try:

        raw = call_model(
            [
                {
                    "role": "system",
                    "content": planner,
                }
            ],
            model=REASONING_MODEL,
            json_mode=True,
            temperature=0.1,
            num_ctx=16384,
            timeout=600,
        )

        result = json.loads(raw)

        if isinstance(result, dict):

            result["_routing"] = {
                "reasoning_model":
                    REASONING_MODEL,
                "heavy_specialist":
                    HEAVY_MODEL
                    if use_heavy
                    else None,
                "heavy_used":
                    use_heavy,
            }

            return result

    except Exception as exc:

        return {
            "goal": task,
            "steps": [
                "Inspect real state",
                "Perform smallest safe change",
                "Verify independently",
                "Continue until complete",
            ],
            "success_criteria": [
                "Actual tool evidence confirms completion"
            ],
            "risks": [
                "Planner fallback: "
                + type(exc).__name__
            ],
            "_routing": {
                "reasoning_model":
                    REASONING_MODEL,
                "heavy_specialist":
                    HEAVY_MODEL
                    if use_heavy
                    else None,
                "heavy_used":
                    use_heavy,
            },
        }

    return {
        "goal": task,
        "steps": [
            "Inspect",
            "Execute",
            "Verify",
        ],
        "success_criteria": [
            "Result is verified"
        ],
        "risks": [],
        "_routing": {
            "reasoning_model":
                REASONING_MODEL,
            "heavy_specialist":
                HEAVY_MODEL
                if use_heavy
                else None,
            "heavy_used":
                use_heavy,
        },
    }
'''

pattern = (
    r"def create_execution_plan\(task\):"
    r".*?"
    r"(?=\n# ============================================================\n"
    r"# EXECUTOR PROMPT)"
)

orch, count = re.subn(
    pattern,
    new_plan.rstrip(),
    orch,
    count=1,
    flags=re.S,
)

if count != 1:
    raise RuntimeError(
        "Could not replace create_execution_plan."
    )


# ============================================================
# Replace recovery reviewer
# Heavy activates after repeated failures too.
# ============================================================

new_recovery = r'''def recovery_review(
    task,
    plan,
    trace,
):

    recent_failures = sum(
        1
        for item in trace[-6:]
        if not item.get("ok", False)
    )

    use_heavy = (
        HEAVY_MODEL_AVAILABLE
        and (
            should_use_heavy(task)
            or recent_failures >= 2
        )
    )

    prompt = f"""
You are the recovery reviewer for an autonomous
Unreal Engine agent.

USER TASK:
{task}

PLAN:
{json.dumps(plan, ensure_ascii=False)}

RECENT REAL TOOL RESULTS:
{trace_summary(trace, 10)}

AVAILABLE TOOL NAMES:
{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

The previous approach failed.

Give the executor a SHORT concrete recovery instruction.

Rules:

- Trust actual tool output.
- Do not claim success.
- Do not repeat the exact same failed call.
- Suggest inspection or a different valid strategy.
- Never invent tools.
- Levels are not Blueprints.
"""

    preferred_model = (
        HEAVY_MODEL
        if use_heavy
        else REASONING_MODEL
    )

    try:

        return call_model(
            [
                {
                    "role": "system",
                    "content": prompt,
                }
            ],
            model=preferred_model,
            json_mode=False,
            temperature=0.05,
            num_ctx=8192
                if use_heavy
                else 12000,
            timeout=900
                if use_heavy
                else 300,
        )

    except Exception as first_exc:

        # Automatic fallback if Heavy fails.
        if use_heavy:

            try:

                return call_model(
                    [
                        {
                            "role": "system",
                            "content":
                                prompt
                                + "\nHeavy specialist failed. "
                                  "Provide recovery using the "
                                  "standard reasoning model.",
                        }
                    ],
                    model=REASONING_MODEL,
                    json_mode=False,
                    temperature=0.1,
                    num_ctx=12000,
                    timeout=300,
                )

            except Exception:
                pass

        return (
            "Inspect the real error and use "
            "a different valid approach. "
            f"Reviewer error: {type(first_exc).__name__}"
        )
'''

pattern = (
    r"def recovery_review\("
    r".*?"
    r"(?=\n# ============================================================\n"
    r"# FINAL REVIEWER)"
)

orch, count = re.subn(
    pattern,
    new_recovery.rstrip(),
    orch,
    count=1,
    flags=re.S,
)

if count != 1:
    raise RuntimeError(
        "Could not replace recovery_review."
    )


# ============================================================
# runtime_info
# ============================================================

if '"heavy_model_available"' not in orch:

    needle = '"coder_model": CODER_MODEL,'

    if needle not in orch:
        raise RuntimeError(
            "runtime_info coder_model anchor missing."
        )

    orch = orch.replace(
        needle,
        needle + '''
        "heavy_model":
            HEAVY_MODEL
            if HEAVY_MODEL_AVAILABLE
            else None,
        "heavy_model_available":
            HEAVY_MODEL_AVAILABLE,''',
        1,
    )


# ============================================================
# API: expose Heavy status
# ============================================================

if "HEAVY_MODEL," not in api:

    needle = "    CODER_MODEL,\n"

    if needle not in api:
        raise RuntimeError(
            "API CODER_MODEL import anchor missing."
        )

    api = api.replace(
        needle,
        needle
        + "    HEAVY_MODEL,\n"
        + "    HEAVY_MODEL_AVAILABLE,\n",
        1,
    )

api = api.replace(
    'version="2.0.0"',
    'version="3.0.0"',
)

api = api.replace(
    '"version": "Adaptive API v2"',
    '"version": "Adaptive API v3"',
)

if '"heavy":' not in api:

    needle = '"coder": CODER_MODEL,'

    if needle not in api:
        raise RuntimeError(
            "API status coder anchor missing."
        )

    api = api.replace(
        needle,
        needle + '''
            "heavy":
                HEAVY_MODEL
                if HEAVY_MODEL_AVAILABLE
                else None,''',
        1,
    )

if '"heavy_model":' not in api:

    needle = '"coder_model": CODER_MODEL,'

    if needle in api:
        api = api.replace(
            needle,
            needle + '''
            "heavy_model":
                HEAVY_MODEL
                if HEAVY_MODEL_AVAILABLE
                else None,''',
            1,
        )


# ============================================================
# Validate BEFORE writing
# ============================================================

compile(
    orch,
    str(ORCH),
    "exec",
)

compile(
    api,
    str(API),
    "exec",
)

ORCH.write_text(
    orch,
    encoding="utf-8",
)

API.write_text(
    api,
    encoding="utf-8",
)

print("HEAVY SPECIALIST PATCH: PASS")
print("Backup:", orch_backup)
print("Backup:", api_backup)