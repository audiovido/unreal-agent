// ============================================================================
// FREEBUFF → UNREAL AGENT THIN-CLIENT ROUTER
// ----------------------------------------------------------------------------
// Makes Freebuff a pure UI/transport layer for the already-running Unreal
// Agent API. When the current workspace is the Unreal-Agent project, a user
// message is POSTed to the Unreal Agent API (127.0.0.1:8765), its execution
// events are streamed back through Freebuff's normal turn machinery, and the
// final verdict (PASS / FAIL / BLOCKED) plus proof is displayed.
//
// Rules honored by this module:
//   * Freebuff's selected LLM is NEVER used for Unreal work.
//   * No Freebuff model session is consumed for Unreal execution.
//   * Unreal Agent owns model routing (Ollama) and execution.
//   * Ollama is never called from Freebuff.
//   * "/freebuff" prefix escapes routing back to the normal Freebuff agent.
//   * If the Unreal backend (8765) is down, the Unreal-Agent launcher is
//     started and /api/status is polled before the request is resumed.
//   * Bridge (6766) recovery is left entirely to Unreal Agent.
//
// This file is a faithful copy of the block injected into
// %LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\resources\orchestrator\
// orchestrator.js (kept here for review, testing, and re-application after
// Freebuff app updates).
// ============================================================================

// --- minimal node builtins via import.meta.require (Bun) --------------------
function fbNodeRequire(name) {
  try {
    return import.meta.require(name);
  } catch (err) {
    try {
      // eslint-disable-next-line no-undef
      return require(name);
    } catch (err2) {
      throw new Error("freebuff-unreal-router: cannot load " + name);
    }
  }
}

const fbPath = fbNodeRequire("node:path");
const fbFs = fbNodeRequire("node:fs");

// --- identity + endpoints ----------------------------------------------------
const FB_UNREAL_PROJECT_ID = "6fe61644-8996-412b-9994-3ca13bdee06a";
const FB_UNREAL_BASE = "http://127.0.0.1:8765";
const FB_UNREAL_ACTION_URL = FB_UNREAL_BASE + "/api/action";
const FB_UNREAL_STATUS_URL = FB_UNREAL_BASE + "/api/status";
const FB_UNREAL_PROOF_URL = FB_UNREAL_BASE + "/api/proof/latest";

const FB_UNREAL_PHASE_ICONS = {
  UNDERSTAND: "🔎 Understanding",
  UNDERSTANDING: "🔎 Understanding",
  PLAN: "🧭 Planning",
  PLANNING: "🧭 Planning",
  EDIT: "✏️ Editing",
  EDITING: "✏️ Editing",
  BUILD: "🛠️ Building",
  BUILDING: "🛠️ Building",
  VALIDATE: "🧪 Validating",
  VALIDATING: "🧪 Validating",
  FIX: "🔧 Fixing",
  FIXING: "🔧 Fixing",
  TEST: "🧪 Testing",
  TESTING: "🧪 Testing",
  VERIFY: "🧪 Validating",
  COMPLETE: "✅ Complete",
  COMPLETED: "✅ Complete",
  CLEANUP: "🧹 Cleanup",
};

function fbIsUnrealAgentProject(engine) {
  try {
    const root = engine && engine.root;
    if (typeof root !== "string" || !root) return false;
    // Primary marker: Freebuff's own project identity for this workspace.
    try {
      const pid = fbFs.readFileSync(fbPath.join(root, ".freebuff", "project-id"), "utf8").trim();
      if (pid === FB_UNREAL_PROJECT_ID) return true;
    } catch (err) {}
    // Structural marker: the Unreal-Agent backend lives in this folder.
    try {
      if (
        fbFs.existsSync(fbPath.join(root, "run_agent.py")) &&
        fbFs.existsSync(fbPath.join(root, "app", "served.py")) &&
        fbFs.existsSync(fbPath.join(root, "unreal"))
      ) {
        return true;
      }
    } catch (err) {}
  } catch (err) {}
  return false;
}

// --- backend health / recovery -------------------------------------------------
async function fbUnrealStatus(timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || 4000);
  try {
    const res = await fetch(FB_UNREAL_STATUS_URL, { signal: ctrl.signal });
    if (!res.ok) return { ok: false, error: "HTTP " + res.status };
    const data = await res.json();
    return { ok: !!data.ok, status: data };
  } catch (err) {
    return { ok: false, error: (err && err.message) || String(err) };
  } finally {
    clearTimeout(timer);
  }
}

function fbStartUnrealBackend(root) {
  try {
    const python = fbPath.join(root, ".venv", "Scripts", "python.exe");
    const script = fbPath.join(root, "run_agent.py");
    if (typeof Bun !== "undefined" && Bun.spawn) {
      const proc = Bun.spawn([python, script], {
        cwd: root,
        stdout: "ignore",
        stderr: "ignore",
        stdin: "ignore",
      });
      if (proc && typeof proc.unref === "function") proc.unref();
    } else {
      const { spawn } = fbNodeRequire("node:child_process");
      const child = spawn(python, [script], { cwd: root, detached: true, stdio: "ignore" });
      if (child && typeof child.unref === "function") child.unref();
    }
    return true;
  } catch (err) {
    return false;
  }
}

async function fbEnsureUnrealBackend(root, emit, maxWaitMs) {
  const first = await fbUnrealStatus(4000);
  if (first.ok) return { ok: true, status: first.status, recovered: false };
  emit({
    type: "text",
    text:
      "\n\n> 🔌 Unreal Agent backend (127.0.0.1:8765) is not responding — " +
      "starting it with the Unreal-Agent launcher…\n",
  });
  fbStartUnrealBackend(root);
  const deadline = Date.now() + (maxWaitMs || 120000);
  let last = first;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    last = await fbUnrealStatus(4000);
    if (last.ok) return { ok: true, status: last.status, recovered: true };
  }
  return { ok: false, error: last.error || "backend did not come up in time" };
}

// --- event translation ---------------------------------------------------------
function fbCompact(value, max) {
  if (value === undefined || value === null) return "";
  let s;
  if (typeof value === "string") s = value;
  else {
    try {
      s = JSON.stringify(value);
    } catch (err) {
      s = String(value);
    }
  }
  s = s.replace(/\s+/g, " ").trim();
  return s.length > (max || 400) ? s.slice(0, max || 400) + "…" : s;
}

function fbPlanSummary(plan) {
  try {
    const steps = (plan && Array.isArray(plan.steps) && plan.steps) || [];
    if (!steps.length) return "";
    const phases = [];
    for (const step of steps) {
      const phase = String(step && step.phase || step && step.intent || "").toUpperCase();
      const icon = FB_UNREAL_PHASE_ICONS[phase] || phase.toLowerCase();
      if (phases.indexOf(icon) < 0) phases.push(icon);
    }
    return phases.length ? " — " + phases.slice(0, 8).join(" → ") : "";
  } catch (err) {
    return "";
  }
}

function fbUnrealEventText(ev, state) {
  const type = ev && ev.type;
  const title = (ev && ev.title) || "";
  const status = (ev && ev.status) || "info";
  const detail = ev && ev.detail;
  switch (type) {
    case "user":
      return null; // the user's own message is already in the transcript
    case "planning": {
      const plan = detail && typeof detail === "object" ? detail : null;
      const summary = plan ? fbPlanSummary(plan) : "";
      return "\n\n### 🧭 Planning\n" + title + summary;
    }
    case "thinking":
      return "\n> 💭 " + title;
    case "tool":
      if (state) state.tools.push({ name: title, ok: null });
      return "\n\n### 🔧 " + title;
    case "tool_result": {
      const okFlag = detail && typeof detail === "object" && detail.ok === true;
      const ok = status === "success" || okFlag;
      let extra = "";
      if (detail && typeof detail === "object") {
        if (detail.error) extra = " — " + fbCompact(detail.error, 220);
        else if (detail.message) extra = " — " + fbCompact(detail.message, 220);
        else if (detail.value !== undefined && detail.value !== null)
          extra = " — " + fbCompact(detail.value, 220);
      }
      if (state && state.tools.length) {
        const last = state.tools[state.tools.length - 1];
        if (last && last.name === title && last.ok === null) last.ok = ok;
      }
      return "\n- " + (ok ? "✅" : "❌") + " " + title + extra;
    }
    case "complete":
      return status === "success" ? "\n\n### ✅ " + title : "\n- " + title;
    case "error":
      return (
        "\n\n### ❌ " +
        title +
        (detail ? "\n" + fbCompact(detail, 500) : "")
      );
    case "final":
      return fbUnrealFinalText(ev);
    default:
      return title ? "\n- " + title : null;
  }
}

function fbUnrealFinalText(ev) {
  const status = (ev && ev.status) || "info";
  const title = (ev && ev.title) || "";
  const detail = ev && ev.detail;
  const message = detail && typeof detail === "object" ? detail.message || detail : detail || title;
  if (status === "complete") {
    return (
      "\n\n---\n" +
      "## ✅ PASS — Unreal Agent completed the task\n\n" +
      fbCompact(message, 1400) +
      "\n\n**Proof:** " +
      FB_UNREAL_PROOF_URL +
      " (viewport capture captured by Unreal Agent)\n"
    );
  }
  if (status === "failed") {
    return (
      "\n\n---\n" +
      "## ❌ FAIL — Unreal Agent reported failure\n\n" +
      fbCompact(message, 1400)
    );
  }
  return "\n\n---\n## ⚠️ " + title + "\n" + fbCompact(message, 800);
}

function fbUnrealTerminal(ev) {
  if (!ev) return null;
  if (ev.type === "final")
    return {
      kind: ev.status === "complete" ? "pass" : ev.status === "failed" ? "fail" : "blocked",
      event: ev,
    };
  if (ev.type === "error") return { kind: "fail", event: ev };
  return null;
}

// --- SSE streaming --------------------------------------------------------------
async function fbStreamUnrealTask(taskId, emit, signal) {
  const streamCtrl = new AbortController();
  const onAbort = () => {
    try {
      streamCtrl.abort();
    } catch (err) {}
  };
  signal.addEventListener("abort", onAbort);
  const state = { tools: [] };
  let res;
  try {
    res = await fetch(FB_UNREAL_BASE + "/api/events/stream/" + encodeURIComponent(taskId), {
      signal: streamCtrl.signal,
    });
  } catch (err) {
    signal.removeEventListener("abort", onAbort);
    return { terminal: null, error: "stream connect failed: " + ((err && err.message) || err) };
  }
  if (!res.ok || !res.body) {
    signal.removeEventListener("abort", onAbort);
    return { terminal: null, error: "SSE HTTP " + res.status };
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let lastDataAt = Date.now();
  let sawComplete = false;
  let finalSeen = null;

  // Watchdog: if Unreal Agent pauses for approval (non-terminal) the stream
  // goes silent. Detect it via /api/status and report BLOCKED.
  let watchdog = null;
  let watchdogStopped = false;
  const startWatchdog = () => {
    const check = async () => {
      if (watchdogStopped) return;
      const idleMs = Date.now() - lastDataAt;
      if (idleMs < 90000) {
        watchdog = setTimeout(check, 30000);
        return;
      }
      const st = await fbUnrealStatus(4000);
      if (watchdogStopped) return;
      if (st.ok && st.status && st.status.pending_approvals > 0) {
        emit({
          type: "text",
          text:
            "\n\n## ⛔ BLOCKED — Unreal Agent is waiting for approval\n\n" +
            "Open the Unreal Agent UI (http://127.0.0.1:8765) to approve or reject the guarded " +
            "operation, then send your request again.",
        });
        watchdogStopped = true;
        try {
          streamCtrl.abort();
        } catch (err) {}
        return;
      }
      if (st.ok && st.status && st.status.execution_active === false && !finalSeen) {
        // Task may have ended without a terminal event on this stream.
        const evs = await fbUnrealPollTerminal(taskId, 10000);
        if (watchdogStopped) return;
        if (evs) {
          finalSeen = evs;
          try {
            streamCtrl.abort();
          } catch (err) {}
          return;
        }
        emit({
          type: "text",
          text: "\n\n## ⚠️ Unreal Agent went quiet — no terminal event received. Ending turn.",
        });
        watchdogStopped = true;
        try {
          streamCtrl.abort();
        } catch (err) {}
        return;
      }
      watchdog = setTimeout(check, 30000);
    };
    watchdog = setTimeout(check, 90000);
  };
  startWatchdog();

  try {
    for (;;) {
      let chunk;
      try {
        const read = await reader.read();
        chunk = read;
      } catch (err) {
        if (signal.aborted || streamCtrl.signal.aborted) break;
        break;
      }
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          let ev;
          try {
            ev = JSON.parse(line.slice(6));
          } catch (err) {
            continue;
          }
          lastDataAt = Date.now();
          const text = fbUnrealEventText(ev, state);
          if (text) emit({ type: "text", text });
          if (ev.type === "complete" && ev.status === "success") sawComplete = true;
          const term = fbUnrealTerminal(ev);
          if (term) {
            finalSeen = term;
            watchdogStopped = true;
            return { terminal: term, state, error: null };
          }
        }
      }
    }
  } catch (err) {
    watchdogStopped = true;
    return { terminal: finalSeen, state, error: ((err && err.message) || String(err)) };
  } finally {
    watchdogStopped = true;
    if (watchdog) clearTimeout(watchdog);
    signal.removeEventListener("abort", onAbort);
  }
  watchdogStopped = true;
  if (finalSeen) return { terminal: finalSeen, state, error: null };
  return { terminal: null, state, error: "stream ended without a terminal event" };
}

async function fbUnrealPollTerminal(taskId, timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 10000);
  while (Date.now() < deadline) {
    try {
      const res = await fetch(FB_UNREAL_BASE + "/api/events", { signal: AbortSignal.timeout(4000) });
      if (res.ok) {
        const data = await res.json();
        const events = (data && data.events) || [];
        for (let i = events.length - 1; i >= 0; i--) {
          const ev = events[i];
          if (ev && ev.task_id === taskId) {
            const term = fbUnrealTerminal(ev);
            if (term) return term;
          }
        }
      }
    } catch (err) {}
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  return null;
}

// --- the routed turn -------------------------------------------------------------
async function fbRunUnrealTurn(engine, thread, input, aborter) {
  const { deps, ledger, liveTurns } = engine;
  const threadId = thread.id;
  const startedAt = Date.now();
  const chatText = engine.inputChatText(input);
  if (!ledger.claim(input.id, { parts: [{ kind: "text", text: chatText }], attachments: input.attachments }, startedAt)) {
    return null;
  }
  engine.markOutcome(threadId, null);
  engine.emitThread(threadId);
  const live = { parts: [], seq: 0, changes: () => [] };
  liveTurns.set(threadId, live);
  let partId = 0;
  const newId = () => "p" + ++partId + "-" + String(input.id).slice(0, 8);
  const emit = (ev) => {
    live.parts = foldAgentEvent(live.parts, ev, newId);
    live.seq += 1;
    deps.bus.publish({ type: "agent", threadId, seq: live.seq, event: ev });
  };

  let outcome = "completed";
  let terminal = null;
  let state = { tools: [] };
  try {
    // 1. Backend health + recovery
    const ready = await fbEnsureUnrealBackend(engine.root, emit, 120000);
    if (!ready.ok) {
      emit({
        type: "text",
        text:
          "\n\n## ⛔ BLOCKED — Unreal Agent backend unreachable\n\n" +
          fbCompact(ready.error, 400) +
          "\n\nStart it from the Unreal-Agent folder (START_AGENT.bat) and send the request again.",
      });
      outcome = "error";
      terminal = { kind: "blocked" };
    } else {
      // Surface bridge status if Unreal Agent reports it unhealthy — recovery
      // is owned by Unreal Agent itself.
      const unreal = ready.status && ready.status.unreal;
      if (unreal && unreal.ok === false) {
        emit({
          type: "text",
          text:
            "\n\n> ⚠️ Unreal Bridge (6766) not ready: " +
            fbCompact(unreal.message || unreal.error || "unavailable", 200) +
            ". Unreal Agent will recover it.\n",
        });
      }
      // 2. Submit the exact user message
      emit({
        type: "text",
        text: "\n> ⏳ Unreal Agent is preparing the request (planning with its own local models)…\n",
      });
      const taskId = await fbSubmitUnrealPrompt(input.prompt, emit, aborter.signal);
      if (taskId) {
        emit({
          type: "text",
          text: "\n> 🔗 Routed to **Unreal Agent** · task `" + taskId + "`\n",
        });
        // 3. Stream execution events
        const streamed = await fbStreamUnrealTask(taskId, emit, aborter.signal);
        state = streamed.state || state;
        terminal = streamed.terminal;
        if (streamed.error && !terminal) {
          emit({
            type: "text",
            text: "\n\n> ⚠️ " + fbCompact(streamed.error, 400),
          });
        }
      }
    }
  } catch (err) {
    if (aborter.signal.aborted) {
      outcome = "stopped";
    } else {
      outcome = "error";
      emit({ type: "text", text: "\n\n⚠️ " + fbCompact((err && err.message) || String(err), 500) });
    }
  }

  // Final summary (if not already written by the terminal event)
  if (terminal && terminal.kind && !terminal.event) {
    emit({ type: "text", text: fbUnrealVerdictText(terminal.kind, state) });
  } else if (!terminal && outcome === "completed") {
    outcome = "error";
    emit({
      type: "text",
      text: "\n\n## ❌ FAIL — Unreal Agent task ended without a terminal event",
    });
  }

  emit({ type: "finish" });
  const finishedAt = Date.now();
  engine.completeTurn(threadId, input.id, live.parts, live.metrics, finishedAt, finishedAt, undefined, outcome);
  liveTurns.delete(threadId);
  engine.previews.onTurnSettled(threadId);
  engine.deliveries.onTurnSettled(threadId).catch(() => {});
  engine.emitThread(threadId);
  return outcome;
}

function fbUnrealVerdictText(kind, state) {
  const tools = (state && state.tools) || [];
  const okCount = tools.filter((t) => t.ok === true).length;
  const badCount = tools.filter((t) => t.ok === false).length;
  const line =
    tools.length
      ? "\n\n**Tool execution:** " + tools.length + " tool(s) — " + okCount + " ok" + (badCount ? ", " + badCount + " failed" : "")
      : "";
  if (kind === "pass")
    return "\n\n---\n## ✅ PASS — Unreal Agent completed the task" + line + "\n\n**Proof:** " + FB_UNREAL_PROOF_URL + "\n";
  if (kind === "fail")
    return "\n\n---\n## ❌ FAIL — Unreal Agent reported failure" + line;
  return "\n\n---\n## ⛔ BLOCKED — Unreal Agent could not complete the task" + line;
}

async function fbSubmitUnrealPrompt(message, emit, signal) {
  // The Unreal Agent generates the execution plan synchronously inside the
  // submit handler (its own Ollama call), so the POST can legitimately take
  // well over a minute. Give it a generous budget and let the turn aborter
  // still stop it. Network-level failures get one retry.
  const timeoutMs = 180000;
  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, 2000));
    let res;
    try {
      const ctrl = new AbortController();
      const onAbort = () => ctrl.abort();
      if (signal && typeof signal.addEventListener === "function") signal.addEventListener("abort", onAbort);
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        res = await fetch(FB_UNREAL_ACTION_URL, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action: "prompt", payload: { message: String(message) } }),
          signal: ctrl.signal,
        });
      } finally {
        clearTimeout(timer);
        if (signal && typeof signal.removeEventListener === "function") signal.removeEventListener("abort", onAbort);
      }
    } catch (err) {
      lastErr = (err && err.message) || String(err);
      if (signal && signal.aborted) {
        emit({ type: "text", text: "\n\n> ⏹️ Unreal Agent submit stopped by user.\n" });
        return null;
      }
      continue; // retry network-level failure once
    }
    let data;
    try {
      data = await res.json();
    } catch (err) {
      data = null;
    }
    if (!res.ok || !data || data.ok !== true) {
      const msg = (data && (data.detail || data.message || data.error)) || "HTTP " + res.status;
      const blocked = res.status === 409 || /another task is already active/i.test(String(msg));
      emit({
        type: "text",
        text:
          (blocked
            ? "\n\n## ⛔ BLOCKED — another task is already active in Unreal Agent\n\n"
            : "\n\n### ❌ Unreal Agent rejected the request\n\n") +
          fbCompact(msg, 400),
      });
      return null;
    }
    return data.task_id || (data.data && data.data.task_id) || null;
  }
  emit({
    type: "text",
    text: "\n\n### ❌ Unreal Agent submit failed\n" + fbCompact(lastErr || "unknown error", 300),
  });
  return null;
}

// --- dispatcher -------------------------------------------------------------------
async function runTurnOrRoute(engine, thread, input, aborter) {
  if (fbIsUnrealAgentProject(engine)) {
    // Only route user-initiated messages. Freebuff-internal inputs (skills,
    // missions / autorun) stay on the normal Freebuff agent.
    const source = input && input.source;
    const userInitiated = !source || source === "user" || source === "queue";
    if (userInitiated) {
      const prompt = input && typeof input.prompt === "string" ? input.prompt : "";
      const trimmed = prompt.trim();
      if (trimmed.startsWith("/freebuff")) {
        // Escape hatch: hand the message to the normal Freebuff agent, with the
        // prefix stripped so it does not pollute the request.
        const input2 = Object.assign({}, input, { prompt: trimmed.replace(/^\/freebuff\s*/, "") });
        return runTurn(engine, thread, input2, aborter);
      }
      return fbRunUnrealTurn(engine, thread, input, aborter);
    }
  }
  return runTurn(engine, thread, input, aborter);
}

// ----------------------------------------------------------------------------
// Standalone-test exports. Harmless when this block is spliced into the
// orchestrator bundle (there `module` is undefined in the ESM scope).
// ----------------------------------------------------------------------------
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    FB_UNREAL_BASE,
    fbIsUnrealAgentProject,
    fbUnrealStatus,
    fbStartUnrealBackend,
    fbEnsureUnrealBackend,
    fbUnrealEventText,
    fbUnrealTerminal,
    fbStreamUnrealTask,
    fbSubmitUnrealPrompt,
    fbRunUnrealTurn,
    fbUnrealVerdictText,
    fbUnrealPollTerminal,
    runTurnOrRoute,
  };
}
