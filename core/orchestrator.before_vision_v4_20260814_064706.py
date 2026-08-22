import json
import os
import re
import sys
import time
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.project_manager import (
    discover_projects,
    inspect_project,
    open_project,
)

from tools.system.tool_runner import (
    read_text_file,
    write_text_file,
    run_powershell,
    unreal_status,
)

from core.tool_registry import build_registry, tool_prompt, validate_args
from tools.unreal.unreal_bridge import UnrealBridge


# ============================================================
# CONFIG
# ============================================================

OLLAMA_URL = os.getenv(
    "UNREAL_AGENT_OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat",
)

DEFAULT_MODEL = os.getenv(
    "UNREAL_AGENT_DEFAULT_MODEL",
    "qwen2.5-coder:14b",
)

SESSION_FILE = ROOT / "memory" / "conversation.json"
STATE_FILE = ROOT / "memory" / "agent_state.json"

BRIDGE = UnrealBridge()

REGISTRY = build_registry(
    discover_projects,
    inspect_project,
    open_project,
    read_text_file,
    write_text_file,
    run_powershell,
    unreal_status,
    bridge=BRIDGE,
)


# ============================================================
# MODEL ROUTER
# ============================================================

def ollama_base():
    if "/api/" in OLLAMA_URL:
        return OLLAMA_URL.split("/api/", 1)[0]
    return OLLAMA_URL.rstrip("/")


def discover_models():
    try:
        r = requests.get(
            ollama_base() + "/api/tags",
            timeout=5,
        )
        r.raise_for_status()

        models = []

        for item in r.json().get("models", []):
            name = item.get("name") or item.get("model")

            if name:
                models.append(str(name))

        return models or [DEFAULT_MODEL]

    except Exception:
        return [DEFAULT_MODEL]


def model_size(name):
    found = re.findall(
        r"(\d+(?:\.\d+)?)b",
        name.lower(),
    )

    if not found:
        return 0.0

    try:
        return float(found[-1])
    except Exception:
        return 0.0


def choose_model(role, models):

    env_names = {
        "fast": "UNREAL_AGENT_FAST_MODEL",
        "reasoning": "UNREAL_AGENT_REASONING_MODEL",
        "coder": "UNREAL_AGENT_CODER_MODEL",
    }

    override = os.getenv(env_names[role])

    if override and override in models:
        return override

    def score(name):

        n = name.lower()
        size = model_size(name)

        if role == "fast":

            s = 0

            if any(
                x in n
                for x in (
                    "mini",
                    "small",
                    "phi",
                    "gemma",
                    "3b",
                    "4b",
                    "7b",
                    "8b",
                )
            ):
                s += 100

            if "coder" not in n:
                s += 10

            if size:
                s += max(0, 30 - size)

            return s

        if role == "reasoning":

            s = size

            if any(
                x in n
                for x in (
                    "deepseek-r1",
                    "qwq",
                    "reason",
                    "qwen3",
                )
            ):
                s += 150

            return s

        # coder
        s = size

        if any(
            x in n
            for x in (
                "coder",
                "codestral",
                "devstral",
                "code",
            )
        ):
            s += 150

        return s

    if not models:
        return DEFAULT_MODEL

    return max(models, key=score)


AVAILABLE_MODELS = discover_models()

FAST_MODEL = choose_model(
    "fast",
    AVAILABLE_MODELS,
)

REASONING_MODEL = choose_model(
    "reasoning",
    AVAILABLE_MODELS,
)

CODER_MODEL = choose_model(
    "coder",
    AVAILABLE_MODELS,
)

# Backward compatibility.
MODEL = CODER_MODEL


# ============================================================
# MASTER PERSONALITY
# ============================================================

SYSTEM = """
You are UnrealAgent.

You are not merely a tool runner.

You are an adaptive senior Unreal Engine engineering agent,
technical director, software engineer, game-development planner,
debugger and conversational assistant.

You understand both Persian and English.

You support three modes:

CHAT
Normal questions, explanations, brainstorming and consultation.

PLAN
Architecture, game planning, production planning,
technical roadmaps and implementation strategy.

EXECUTE
Real inspection, coding, Unreal Engine work and project modification.

The user should never need to manually select a mode.
You decide automatically.

Never pretend that a real-world action occurred
unless actual tool output proves it.
"""


# ============================================================
# SESSION MEMORY
# ============================================================

def load_session():

    if not SESSION_FILE.exists():
        return [
            {
                "role": "system",
                "content": SYSTEM,
            }
        ]

    try:

        messages = json.loads(
            SESSION_FILE.read_text(
                encoding="utf-8-sig",
            )
        )

        if not isinstance(messages, list):
            raise ValueError(
                "conversation memory is not a list"
            )

        if (
            messages
            and messages[0].get("role") == "system"
        ):
            messages[0]["content"] = SYSTEM

        else:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": SYSTEM,
                },
            )

        return messages

    except Exception as exc:

        print(
            "WARNING: conversation memory reset:",
            exc,
        )

        return [
            {
                "role": "system",
                "content": SYSTEM,
            }
        ]


def save_session(messages):

    SESSION_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    normal_messages = [
        m
        for m in messages
        if m.get("role") != "system"
    ]

    # Prevent unlimited context growth.
    normal_messages = normal_messages[-80:]

    payload = [
        {
            "role": "system",
            "content": SYSTEM,
        }
    ] + normal_messages

    SESSION_FILE.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_state(data):

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    STATE_FILE.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


# ============================================================
# LLM
# ============================================================

def trim_text(value, limit=12000):

    text = str(value)

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "\n...[context truncated]..."
    )


def compact_messages(messages, keep=28):

    if not messages:
        return []

    converted = []

    for message in messages:

        m = dict(message)

        m["content"] = trim_text(
            m.get("content", ""),
            12000,
        )

        converted.append(m)

    system = [
        m
        for m in converted
        if m.get("role") == "system"
    ][:1]

    rest = [
        m
        for m in converted
        if m.get("role") != "system"
    ][-keep:]

    return system + rest


def call_model(
    messages,
    model=None,
    json_mode=True,
    temperature=0.1,
    num_ctx=32768,
    timeout=600,
):

    payload = {
        "model": model or MODEL,
        "messages": compact_messages(messages),
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    if json_mode:
        payload["format"] = "json"

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()[
        "message"
    ]["content"]


# ============================================================
# INTENT ROUTER
# ============================================================

def classify_intent(task):

    prompt = """
You are the request router for an Unreal engineering agent.

Classify the request into ONE mode.

CHAT:
Conversation, explanation, brainstorming,
simple questions or advice.
No real environment action required.

PLAN:
The user asks for a roadmap, plan, design,
architecture or strategy but does NOT ask
you to execute it yet.

EXECUTE:
The user asks to inspect, build, create,
modify, fix, code, run, save, open,
compile or otherwise act on the real
project/files/Unreal environment.

If they ask to plan AND then execute,
choose EXECUTE.

Understand Persian and English.

Return JSON only:

{
  "mode": "chat|plan|execute",
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
                    "content": task,
                },
            ],
            model=FAST_MODEL,
            json_mode=True,
            temperature=0,
            num_ctx=4096,
            timeout=120,
        )

        data = json.loads(raw)

        mode = str(
            data.get("mode", "")
        ).lower()

        if mode in {
            "chat",
            "plan",
            "execute",
        }:
            return mode

    except Exception:
        pass

    # Safe fallback.
    text = task.lower()

    if any(
        x in text
        for x in (
            "plan",
            "roadmap",
            "architecture",
            "پلن",
            "برنامه ریزی",
            "برنامه‌ریزی",
            "نقشه راه",
        )
    ):
        return "plan"

    return "chat"


# ============================================================
# CHAT MODE
# ============================================================

def run_chat(task, messages):

    chat_system = """
You are the conversational brain of UnrealAgent.

Answer naturally in the user's language.

You can discuss:
- Unreal Engine
- game design
- game production
- programming
- architecture
- debugging
- graphics
- performance
- AI systems
- ordinary questions related to the user's work

Do not output tool-call JSON.
Do not pretend to perform actions.

For simple questions be fast.
For difficult questions be thoughtful.
"""

    context = [
        {
            "role": "system",
            "content": chat_system,
        }
    ]

    context += [
        m
        for m in messages
        if m.get("role") != "system"
    ][-14:]

    return call_model(
        context,
        model=FAST_MODEL,
        json_mode=False,
        temperature=0.45,
        num_ctx=16384,
        timeout=300,
    )


# ============================================================
# PLAN MODE
# ============================================================

def run_plan(task, messages):

    plan_system = """
You are the senior planning brain of UnrealAgent.

Think like:
- a senior Unreal Engine developer
- technical director
- gameplay engineer
- tools engineer
- software architect
- AAA production planner

The user is asking for planning,
not real execution yet.

Produce a practical plan with:
- goal
- architecture
- implementation stages
- dependencies
- risks
- verification
- fallback strategy

Do NOT output tool JSON.
Do NOT pretend that anything was executed.

Answer in the user's language.
"""

    context = [
        {
            "role": "system",
            "content": plan_system,
        }
    ]

    context += [
        m
        for m in messages
        if m.get("role") != "system"
    ][-12:]

    return call_model(
        context,
        model=REASONING_MODEL,
        json_mode=False,
        temperature=0.2,
        num_ctx=32768,
        timeout=600,
    )


# ============================================================
# EXECUTION PLANNER
# ============================================================

def create_execution_plan(task):

    planner = f"""
You are the planning brain of an autonomous
Unreal Engine engineering agent.

USER TASK:

{task}

REAL AVAILABLE TOOL NAMES:

{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

Create an execution strategy.

Important:

- Never invent a tool.
- A Level/Map is NOT a Blueprint.
- Blueprint compile tools must never receive
  Level/Map paths.
- Large creative tasks require many steps.
- Do not stop after performing one tiny action.
- Inspect real state first when appropriate.
- Every mutation must later be independently verified.
- Recover from failed tool calls.
- Prefer an alternate valid approach instead of
  repeating the exact same failed call.

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
    }


# ============================================================
# EXECUTOR PROMPT
# ============================================================

def build_executor_system(plan):

    return f"""
You are the EXECUTION BRAIN of UnrealAgent.

You are an autonomous local Unreal Engine
engineering agent.

CURRENT PLAN:

{json.dumps(plan, ensure_ascii=False, indent=2)}

OPERATING LOOP:

1. Inspect actual state.
2. Decide the next smallest useful action.
3. Call EXACTLY ONE tool.
4. Read the REAL tool output.
5. Detect failure.
6. Recover intelligently.
7. Verify all mutations independently.
8. Continue until the actual user goal is complete.

CORE RULES:

- Never fake execution.
- Never invent tools.
- Never invent arguments.
- Use ONLY the schemas below.
- Failed tool output means failure.
- Do not repeatedly call the same failed
  tool with identical arguments.
- Inspect the error and change strategy.

UNREAL TYPE SAFETY:

A Level/Map is NOT a Blueprint.

Never use:
compile_blueprint
or other Blueprint-only operations
on a Level/Map.

Treat these as map indicators:
- path contains /Maps/
- .umap
- name begins LVL_
- name begins Level_

For level construction use:
actor/level tools and save_level.

For Blueprint work use Blueprint tools.

ACTOR SAFETY:

If Unreal reports:
"Ambiguous actor label"

do not mutate the ambiguous reference.

Use exact internal actor names
or inspect first.

MUTATION VERIFICATION:

After spawn/move/rotate/scale/delete/save/
Blueprint edits or other mutations,
perform an independent read-only verification.

Examples:
get_actor
list_level_actors
get_asset_info
list_assets
list_graph_nodes
list_node_pins
is_level_dirty
or another relevant inspection tool.

LARGE TASKS:

Do NOT stop after one small successful call
when the user requested a whole room,
level, gameplay system or larger feature.

Continue through the necessary steps.

If a premium asset is unavailable,
use an appropriate available fallback
and keep going.

SYSTEM SAFETY:

Never:
- format disks
- modify boot configuration
- change credentials
- modify firewall/security settings
- blindly execute downloaded scripts
- delete whole project directories

AVAILABLE TOOLS:

{tool_prompt(REGISTRY)}

OUTPUT:

Return ONLY one JSON object.

TOOL CALL:

{{
  "action": "exact_tool_name",
  "args": {{
  }},
  "reason": "short reason"
}}

ONLY WHEN REALLY COMPLETE:

{{
  "action": "final",
  "args": {{}},
  "reason": "short reason",
  "final": "what was actually completed and verified"
}}
"""


# ============================================================
# GUARDRAILS
# ============================================================

def all_strings(value):

    if isinstance(value, str):

        yield value

    elif isinstance(value, dict):

        for item in value.values():
            yield from all_strings(item)

    elif isinstance(
        value,
        (list, tuple),
    ):

        for item in value:
            yield from all_strings(item)


def looks_like_map(value):

    v = value.replace(
        "\\",
        "/",
    ).lower()

    base = v.rsplit(
        "/",
        1,
    )[-1]

    return (
        v.endswith(".umap")
        or "/maps/" in v
        or base.startswith("lvl_")
        or base.startswith("level_")
    )


def guard_tool_call(
    task,
    action,
    args,
):

    lower_action = action.lower()

    # Prevent the exact class of error we saw:
    # trying to compile a Level as a Blueprint.
    if "blueprint" in lower_action:

        for value in all_strings(args):

            if looks_like_map(value):

                return (
                    False,
                    (
                        "Blocked invalid operation. "
                        f"{action} is Blueprint-oriented, "
                        f"but '{value}' looks like a Level/Map."
                    ),
                )

    # Project/asset deletion must be explicitly requested.
    if (
        "delete" in lower_action
        or "remove" in lower_action
    ):

        t = task.lower()

        if not any(
            word in t
            for word in (
                "delete",
                "remove",
                "حذف",
                "پاک کن",
            )
        ):

            return (
                False,
                "Deletion was not explicitly requested.",
            )

    # Block clearly dangerous shell patterns.
    if lower_action == "run_powershell":

        joined = " ".join(
            all_strings(args)
        ).lower()

        forbidden = (
            "format-disk",
            "clear-disk",
            "bcdedit",
            "reg delete",
            "cipher /w",
            "shutdown /",
            "remove-item -recurse c:\\",
        )

        for token in forbidden:

            if token in joined:

                return (
                    False,
                    "Blocked dangerous command: "
                    + token,
                )

    return True, ""


def result_ok(result):

    if result is False:
        return False

    if result is None:
        return False

    if isinstance(result, dict):

        if result.get("ok") is False:
            return False

        nested = result.get("result")

        if (
            isinstance(nested, dict)
            and nested.get("ok") is False
        ):
            return False

    return True


def is_verifier(action, spec):

    if getattr(
        spec,
        "destructive",
        False,
    ):
        return False

    a = action.lower()

    return (
        a.startswith("get_")
        or a.startswith("list_")
        or a.startswith("inspect_")
        or a.startswith("find_")
        or a.startswith("is_")
        or a.startswith("discover_")
        or "status" in a
        or a == "unreal_ping"
    )


def trace_summary(
    trace,
    count=15,
):

    clean = []

    for item in trace[-count:]:

        clean.append(
            {
                "step": item["step"],
                "action": item["action"],
                "args": item["args"],
                "ok": item["ok"],
                "result": trim_text(
                    item["result"],
                    3000,
                ),
            }
        )

    return json.dumps(
        clean,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


# ============================================================
# RECOVERY REVIEWER
# ============================================================

def recovery_review(
    task,
    plan,
    trace,
):

    prompt = f"""
You are the recovery reviewer for an autonomous
Unreal Engine agent.

USER TASK:
{task}

PLAN:
{json.dumps(plan, ensure_ascii=False)}

RECENT REAL TOOL RESULTS:
{trace_summary(trace, 10)}

The last approach failed.

Give the executor a SHORT recovery instruction.

Rules:

- Trust actual tool output.
- Do not claim success.
- Do not repeat the exact same failed call.
- Suggest inspection or a different valid tool/strategy.
- Remember that Levels are not Blueprints.
"""

    try:

        return call_model(
            [
                {
                    "role": "system",
                    "content": prompt,
                }
            ],
            model=REASONING_MODEL,
            json_mode=False,
            temperature=0.1,
            num_ctx=12000,
            timeout=300,
        )

    except Exception:

        return (
            "Inspect the real error and use "
            "a different valid approach."
        )


# ============================================================
# FINAL REVIEWER
# ============================================================

def review_completion(
    task,
    plan,
    trace,
    proposed_final,
):

    prompt = f"""
You are the strict QA reviewer for an autonomous
Unreal Engine engineering agent.

USER TASK:
{task}

PLAN:
{json.dumps(plan, ensure_ascii=False)}

REAL TOOL TRACE:
{trace_summary(trace, 20)}

PROPOSED FINAL:
{proposed_final}

Judge completion ONLY from actual tool evidence.

Reject completion when:

- a required operation failed
- a mutation was not independently verified
- the user requested a large feature/scene but
  only a tiny partial action was performed
- required save/verification is missing

Return JSON only:

{{
  "complete": true,
  "missing": [],
  "instruction": "what executor must do next"
}}
"""

    try:

        raw = call_model(
            [
                {
                    "role": "system",
                    "content": prompt,
                }
            ],
            model=REASONING_MODEL,
            json_mode=True,
            temperature=0,
            num_ctx=16384,
            timeout=600,
        )

        result = json.loads(raw)

        if isinstance(result, dict):
            return result

    except Exception:
        pass

    return {
        "complete": True,
        "missing": [],
        "instruction": "",
    }


# ============================================================
# EXECUTION ENGINE
# ============================================================

def run_execution(task):

    plan = create_execution_plan(task)

    print()
    print("=== EXECUTION PLAN ===")
    print(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False,
        )
    )

    messages = [
        {
            "role": "system",
            "content": build_executor_system(
                plan
            ),
        },
        {
            "role": "user",
            "content": task,
        },
    ]

    trace = []

    failed_calls = {}

    verification_pending = False

    successful_calls = 0

    final_rejections = 0

    save_state(
        {
            "mode": "execute",
            "task": task,
            "plan": plan,
            "started_at": time.time(),
        }
    )

    for step in range(80):

        try:

            raw = call_model(
                messages,
                model=CODER_MODEL,
                json_mode=True,
                temperature=0.08,
                num_ctx=32768,
                timeout=600,
            )

        except Exception as exc:

            return (
                "Model request failed: "
                f"{type(exc).__name__}: {exc}"
            )

        try:

            decision = json.loads(raw)

        except Exception as exc:

            messages.append(
                {
                    "role": "assistant",
                    "content": raw,
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "INVALID JSON RESPONSE. "
                        "Return one valid JSON object only. "
                        f"Error: {exc}"
                    ),
                }
            )

            continue

        action = str(
            decision.get("action")
            or ""
        ).strip()

        args = decision.get("args") or {}

        # ---------------- FINAL ----------------

        if action == "final":

            proposed = str(
                decision.get("final")
                or ""
            )

            if verification_pending:

                messages.append(
                    {
                        "role": "assistant",
                        "content": raw,
                    }
                )

                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "FINAL REJECTED. "
                            "A mutation still requires an "
                            "independent read-only verification."
                        ),
                    }
                )

                continue

            if successful_calls == 0:

                messages.append(
                    {
                        "role": "assistant",
                        "content": raw,
                    }
                )

                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "FINAL REJECTED. "
                            "EXECUTE mode requires real tool evidence."
                        ),
                    }
                )

                continue

            review = review_completion(
                task,
                plan,
                trace,
                proposed,
            )

            if (
                not review.get(
                    "complete",
                    False,
                )
                and final_rejections < 3
            ):

                final_rejections += 1

                messages.append(
                    {
                        "role": "assistant",
                        "content": raw,
                    }
                )

                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "QA REVIEW REJECTED COMPLETION.\n"
                            "Missing:\n"
                            + json.dumps(
                                review.get(
                                    "missing",
                                    [],
                                ),
                                ensure_ascii=False,
                            )
                            + "\nInstruction:\n"
                            + str(
                                review.get(
                                    "instruction",
                                    "",
                                )
                            )
                            + "\nContinue executing."
                        ),
                    }
                )

                continue

            save_state(
                {
                    "mode": "execute",
                    "task": task,
                    "plan": plan,
                    "trace": trace[-30:],
                    "completed": True,
                    "final": proposed,
                    "finished_at": time.time(),
                }
            )

            return proposed

        # ---------------- TOOL EXISTS ----------------

        if action not in REGISTRY:

            messages.append(
                {
                    "role": "assistant",
                    "content": raw,
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"ERROR: Unknown tool '{action}'. "
                        "Use ONLY exact AVAILABLE TOOLS."
                    ),
                }
            )

            continue

        spec = REGISTRY[action]

        # ---------------- SCHEMA ----------------

        valid, error = validate_args(
            spec,
            args,
        )

        if not valid:

            messages.append(
                {
                    "role": "assistant",
                    "content": raw,
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"TOOL SCHEMA ERROR for {action}: "
                        f"{error}. "
                        f"Required schema: {spec.args}"
                    ),
                }
            )

            continue

        # ---------------- HARD GUARD ----------------

        allowed, guard_error = (
            guard_tool_call(
                task,
                action,
                args,
            )
        )

        if not allowed:

            result = {
                "ok": False,
                "error": guard_error,
                "blocked_by_guard": True,
            }

        else:

            print()
            print(
                f"=== STEP {step + 1} ==="
            )

            print(
                "TOOL:",
                action,
            )

            print(
                "REASON:",
                decision.get(
                    "reason",
                    "",
                ),
            )

            print(
                "ARGS:",
                args,
            )

            try:

                result = spec.func(
                    **args
                )

            except Exception as exc:

                result = {
                    "ok": False,
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                }

        ok = result_ok(result)

        if ok:
            successful_calls += 1

        # ---------------- VERIFY WRITE ----------------

        if (
            getattr(
                spec,
                "destructive",
                False,
            )
            and ok
        ):

            verification_pending = True

        elif (
            verification_pending
            and ok
            and is_verifier(
                action,
                spec,
            )
        ):

            verification_pending = False

        # ---------------- TRACE ----------------

        item = {
            "step": step + 1,
            "action": action,
            "args": args,
            "ok": ok,
            "result": result,
        }

        trace.append(item)

        print(
            "RESULT:",
            result,
        )

        messages.append(
            {
                "role": "assistant",
                "content": raw,
            }
        )

        messages.append(
            {
                "role": "user",
                "content": (
                    "ACTUAL TOOL RESULT:\n"
                    + json.dumps(
                        result,
                        ensure_ascii=False,
                        default=str,
                    )
                ),
            }
        )

        # ---------------- FAILURE RECOVERY ----------------

        signature = json.dumps(
            {
                "action": action,
                "args": args,
            },
            sort_keys=True,
            default=str,
        )

        if not ok:

            failed_calls[signature] = (
                failed_calls.get(
                    signature,
                    0,
                )
                + 1
            )

            instruction = (
                "The tool failed. "
                "Treat the error as real evidence. "
                "Inspect or choose a different valid strategy."
            )

            if (
                failed_calls[
                    signature
                ]
                >= 2
            ):

                reviewer = recovery_review(
                    task,
                    plan,
                    trace,
                )

                instruction += (
                    "\nDO NOT repeat the exact "
                    "same tool and arguments again."
                    "\nRecovery reviewer:\n"
                    + reviewer
                )

            messages.append(
                {
                    "role": "user",
                    "content": instruction,
                }
            )

        save_state(
            {
                "mode": "execute",
                "task": task,
                "plan": plan,
                "trace": trace[-30:],
                "verification_pending": (
                    verification_pending
                ),
                "updated_at": time.time(),
            }
        )

    # ---------------- STEP LIMIT ----------------

    return (
        "Execution reached the 80-step safety limit. "
        "Verified work was preserved in "
        "memory/agent_state.json."
    )


# ============================================================
# MAIN ROUTER
# ============================================================

def run_agent(
    task,
    messages=None,
):

    if messages is None:

        messages = [
            {
                "role": "system",
                "content": SYSTEM,
            }
        ]

    messages.append(
        {
            "role": "user",
            "content": task,
        }
    )

    mode = classify_intent(task)

    print()
    print(
        "[ROUTER]",
        "mode=" + mode,
    )

    print(
        "[MODELS]",
        "fast=" + FAST_MODEL,
        "| reasoning=" + REASONING_MODEL,
        "| coder=" + CODER_MODEL,
    )

    if mode == "chat":

        answer = run_chat(
            task,
            messages,
        )

    elif mode == "plan":

        answer = run_plan(
            task,
            messages,
        )

    else:

        answer = run_execution(
            task
        )

    messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )

    print()
    print(
        "=== AGENT RESULT ==="
    )
    print()
    print(answer)

    return messages


# ============================================================
# CLI
# ============================================================

def runtime_info():

    return {
        "version": "Adaptive Runtime v2",
        "available_models": AVAILABLE_MODELS,
        "fast_model": FAST_MODEL,
        "reasoning_model": REASONING_MODEL,
        "coder_model": CODER_MODEL,
        "tool_count": len(REGISTRY),
    }

# >>> HEAVY_SPECIALIST_WRAPPER_V3 >>>

HEAVY_MODEL = os.getenv(
    "UNREAL_AGENT_HEAVY_MODEL",
    "unreal-coder:latest",
)

HEAVY_MODEL_AVAILABLE = HEAVY_MODEL in AVAILABLE_MODELS

_create_execution_plan_v2 = create_execution_plan
_recovery_review_v2 = recovery_review
_runtime_info_v2 = runtime_info


def should_use_heavy(task):
    text = str(task).lower()

    strong_terms = (
        "access violation",
        "memory corruption",
        "memory leak",
        "race condition",
        "thread safety",
        "multithread",
        "engine source",
        "unrealbuildtool",
        "build.cs",
        "target.cs",
        "linker error",
        "link error",
        "shader compiler",
        "shader",
        "hlsl",
        "usf",
        "ush",
        "rendering pipeline",
        "rhi",
        "plugin architecture",
        "module architecture",
        "large refactor",
        "performance profiling",
        "replication architecture",
        "network prediction",
        "gameplay ability system",
        "mass entity",
        "complex c++",
        "crash debugging",
        "کرش",
        "پلاگین",
        "شیدر",
        "لینکر",
        "مموری لیک",
        "رفکتور سنگین",
        "سی پلاس پلاس پیچیده",
    )

    if any(term in text for term in strong_terms):
        return True

    router_prompt = """
You are the Heavy-model router for an Unreal Engine engineering agent.

Use the HEAVY model only for genuinely difficult engineering:
complex Unreal C++, plugins/modules, crashes, build/linker failures,
shaders/rendering, memory/threading, deep performance debugging,
network architecture, or major technical refactors.

Do NOT use Heavy for normal conversation, normal planning,
routine Blueprint work, level editing, actor operations,
simple Python, or ordinary Unreal automation.

Return JSON only:
{
  "heavy": true,
  "reason": "short reason"
}
"""

    try:
        raw = call_model(
            [
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": str(task)},
            ],
            model=FAST_MODEL,
            json_mode=True,
            temperature=0,
            num_ctx=4096,
            timeout=120,
        )
        data = json.loads(raw)
        return bool(data.get("heavy", False))
    except Exception:
        return False


def create_execution_plan(task):
    base_plan = _create_execution_plan_v2(task)

    if not isinstance(base_plan, dict):
        base_plan = {
            "goal": str(task),
            "steps": ["Inspect", "Execute", "Verify"],
            "success_criteria": ["Actual tool evidence confirms completion"],
            "risks": [],
        }

    use_heavy = HEAVY_MODEL_AVAILABLE and should_use_heavy(task)

    if not use_heavy:
        base_plan["_routing"] = {
            "planner": REASONING_MODEL,
            "heavy_used": False,
            "heavy_model": None,
        }
        return base_plan

    heavy_prompt = f"""
You are the senior HEAVY Unreal Engine engineering specialist.

USER TASK:
{task}

BASE PLAN:
{json.dumps(base_plan, ensure_ascii=False, indent=2)}

AVAILABLE TOOL NAMES:
{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

Act as a senior technical advisor, not the executor.
Give concise but deep Unreal Engine 5.8 guidance covering:
- architecture and implementation order
- C++ / engine constraints
- likely failure modes
- build/runtime risks
- verification strategy
- recovery alternatives

Never pretend execution occurred.
Never invent available tools.
A Level/Map is NOT a Blueprint.
Keep the advice under 900 words.
"""

    try:
        advice = call_model(
            [{"role": "system", "content": heavy_prompt}],
            model=HEAVY_MODEL,
            json_mode=False,
            temperature=0.05,
            num_ctx=8192,
            timeout=900,
        )

        base_plan["_heavy_advice"] = str(advice)[:12000]
        base_plan["_routing"] = {
            "planner": REASONING_MODEL,
            "heavy_used": True,
            "heavy_model": HEAVY_MODEL,
        }
    except Exception as exc:
        base_plan["_routing"] = {
            "planner": REASONING_MODEL,
            "heavy_used": False,
            "heavy_model": HEAVY_MODEL,
            "heavy_fallback": f"{type(exc).__name__}: {exc}",
        }

    return base_plan


def recovery_review(task, plan, trace):
    recent_failures = sum(
        1 for item in trace[-6:]
        if not item.get("ok", False)
    )

    use_heavy = (
        HEAVY_MODEL_AVAILABLE
        and (
            should_use_heavy(task)
            or recent_failures >= 2
        )
    )

    if not use_heavy:
        return _recovery_review_v2(task, plan, trace)

    heavy_recovery_prompt = f"""
You are the senior Unreal Engine recovery specialist.

USER TASK:
{task}

PLAN:
{json.dumps(plan, ensure_ascii=False)}

RECENT REAL TOOL TRACE:
{trace_summary(trace, 10)}

AVAILABLE TOOL NAMES:
{json.dumps(sorted(REGISTRY.keys()), ensure_ascii=False)}

The agent is stuck or a tool failed.
Give a concise technical recovery instruction.

Rules:
- Trust actual tool results.
- Never claim a failed operation succeeded.
- Do not repeat the identical failed call.
- Never invent a tool.
- Prefer another valid strategy.
- Inspect state when necessary.
- A Level/Map is not a Blueprint.
"""

    try:
        return call_model(
            [{"role": "system", "content": heavy_recovery_prompt}],
            model=HEAVY_MODEL,
            json_mode=False,
            temperature=0.05,
            num_ctx=8192,
            timeout=900,
        )
    except Exception:
        return _recovery_review_v2(task, plan, trace)


def runtime_info():
    info = _runtime_info_v2()
    info["version"] = "Adaptive Runtime v3"
    info["heavy_model"] = HEAVY_MODEL if HEAVY_MODEL_AVAILABLE else None
    info["heavy_model_available"] = HEAVY_MODEL_AVAILABLE
    return info

# <<< HEAVY_SPECIALIST_WRAPPER_V3 <<<

if __name__ == "__main__":

    print(
        "================================"
    )
    print(
        " UnrealAgent Adaptive Runtime v2"
    )
    print(
        "================================"
    )

    print(
        json.dumps(
            runtime_info(),
            indent=2,
            ensure_ascii=False,
        )
    )

    print()

    messages = load_session()

    while True:

        task = input(
            "Task > "
        ).strip()

        if task.lower() in {
            "exit",
            "quit",
        }:
            break

        if task == "/models":

            print(
                json.dumps(
                    runtime_info(),
                    indent=2,
                    ensure_ascii=False,
                )
            )

            continue

        if task == "/reset":

            messages = [
                {
                    "role": "system",
                    "content": SYSTEM,
                }
            ]

            save_session(
                messages
            )

            print(
                "Conversation memory reset."
            )

            continue

        if task:

            messages = run_agent(
                task,
                messages,
            )

            save_session(
                messages
            )