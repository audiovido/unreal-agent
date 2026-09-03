/* Unreal Agent — minimal product UI client. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const el = {
    dot: $("stateDot"), projectName: $("projectName"),
    connectBtn: $("connectBtn"), reconnectBtn: $("reconnectBtn"),
    connectPanel: $("connectPanel"), projectSelect: $("projectSelect"),
    connectNote: $("connectNote"), connectGoBtn: $("connectGoBtn"),
    connectCancelBtn: $("connectCancelBtn"),
    prompt: $("prompt"), runBtn: $("runBtn"), hint: $("hint"),
    statusCard: $("statusCard"), stateLabel: $("stateLabel"),
    stageName: $("stageName"), elapsed: $("elapsed"),
    statusText: $("statusText"), meter: $("meter"),
    meterFill: $("meterFill"), stages: $("stages"),
    resultCard: $("resultCard"), verdict: $("verdict"), score: $("score"),
    resultDetail: $("resultDetail"), proof: $("proof"),
    newTaskBtn: $("newTaskBtn"),
    stateJson: $("stateJson"), copyStateBtn: $("copyStateBtn"),
    footStatus: $("footStatus"), envCheckBtn: $("envCheckBtn"),
    leaseCheckBtn: $("leaseCheckBtn"), diagResult: $("diagResult"),
  };

  const BUSY = new Set(["UNDERSTANDING_REQUEST", "PLANNING", "EXECUTING",
    "VALIDATING", "SELF_FIXING", "CONNECTING_PROJECT", "RECOVERING"]);
  const CONNECTING = new Set(["CONNECTING_PROJECT", "RECOVERING"]);
  const dotClass = {
    READY: "ready", COMPLETE: "ready", IDLE: "",
    FAILED: "bad", UNDERSTANDING_REQUEST: "busy", PLANNING: "busy",
    EXECUTING: "busy", VALIDATING: "busy", SELF_FIXING: "busy",
    CONNECTING_PROJECT: "connect", RECOVERING: "connect",
  };
  const STAGE_ICON = { ok: "ok", failed: "failed", running: "running" };

  let last = null;
  // persistent user-facing error (BUSY/conflict etc.) that survives the
  // status poll re-renders; cleared by typing or by a successful run
  let runError = null;

  /* ---------------- helpers ---------------- */
  async function api(path, opts) {
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (_) { /* empty body */ }
    if (!r.ok) {
      const detail = (data && (data.detail || data.error)) || r.statusText;
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      const e = new Error(msg);
      e.detail = data && data.detail !== undefined ? data.detail : data;
      e.status = r.status;
      throw e;
    }
    return data;
  }

  function proofUrl(p) {
    return "/api/ua/proof-file?path=" + encodeURIComponent(p);
  }

  function statusCls(s) {
    return dotClass[s] || "";
  }

  function fmtElapsed(s) {
    if (s == null) return "";
    if (s < 60) return s.toFixed(0) + "s";
    const m = Math.floor(s / 60);
    return m + "m " + Math.round(s % 60) + "s";
  }

  /* ---------------- render ---------------- */
  function render(st) {
    last = st;
    const state = st.state || "IDLE";
    const busy = BUSY.has(state);

    el.dot.className = "dot " + statusCls(state);
    el.projectName.textContent = (st.project && st.project.name) || "No project";
    el.footStatus.textContent = st.status_text || state;
    el.stateJson.textContent = JSON.stringify(st, null, 2);
    if (runError) {
      el.hint.textContent = runError;
      el.hint.style.color = "#f26d6d";
      return; // keep the persistent error visible until cleared
    }

    // connect / run affordances
    const canConnect = !busy;
    el.connectBtn.disabled = !canConnect;
    el.connectBtn.classList.toggle("hidden", busy);
    el.reconnectBtn.classList.toggle("hidden", state !== "RECOVERING");
    if (state === "RECOVERING") el.reconnectBtn.disabled = false;
    const canRun = state === "READY" || state === "COMPLETE" || state === "FAILED";
    el.runBtn.disabled = !canRun || !(el.prompt.value.trim());
    el.hint.textContent =
      state === "READY" ? "Ready — describe a change to the level."
      : state === "COMPLETE" ? "Task complete. Run another request, or start fresh."
      : state === "FAILED" ? "Task failed. See the reason below, then retry."
      : state === "IDLE" ? "Connect to a project first."
      : st.status_text || "Working…";
    if (state === "FAILED" && st.error_detail) {
      el.hint.textContent = "Task failed: " + st.error_detail;
    }

    // active task card
    if (BUSY.has(state) || state === "READY") {
      el.statusCard.classList.remove("hidden");
    } else {
      el.statusCard.classList.add("hidden");
    }
    el.stateLabel.textContent = state.replace(/_/g, " ");
    el.stateLabel.className = "state-label " + (state === "READY" ? "ready"
      : state === "FAILED" ? "bad" : busy ? "busy" : "");
    el.stageName.textContent = st.current_stage
      ? "Stage: " + st.current_stage : (st.status_text || "");
    el.statusText.textContent = st.active_issue
      ? "Active issue: " + st.active_issue : "";
    el.elapsed.textContent = fmtElapsed(st.elapsed_s);

    if (st.progress && st.progress.total) {
      el.meter.classList.remove("hidden");
      el.meterFill.style.width =
        Math.round(100 * st.progress.completed / st.progress.total) + "%";
    } else {
      el.meter.classList.add("hidden");
    }

    el.stages.innerHTML = "";
    for (const s of (st.stages || [])) {
      const li = document.createElement("li");
      li.className = STAGE_ICON[s.status] || "";
      li.textContent = (s.detail || s.name) +
        (s.status === "ok" ? " ✓" : s.status === "failed" ? " ✗" : "");
      el.stages.appendChild(li);
    }

    // result card
    const hasFinal = st.final && st.final.verdict;
    if (hasFinal) {
      el.resultCard.classList.remove("hidden");
      el.verdict.textContent = st.final.verdict;
      el.verdict.className = "verdict " + st.final.verdict;
      el.score.textContent = st.final.score != null
        ? "visual score " + Number(st.final.score).toFixed(2)
        : "";
      const defects = (st.final.defects || []).length;
      const parts = [];
      if (st.final.score != null) {
        parts.push(st.final.score >= 8.5 ? "score ≥ 8.5" : "score below gate");
      }
      parts.push(defects === 0 ? "no blocking defects" : defects + " defect(s)");
      if (st.final.world_saved) parts.push("world saved");
      if (st.final.human_corrections === 0) parts.push("0 human corrections");
      el.resultDetail.innerHTML = "";
      const p = document.createElement("p");
      if (st.final.verdict === "SUCCESS") {
        p.className = "okline";
        p.textContent = "Accepted — " + parts.join(" · ");
      } else {
        p.className = "reason";
        p.textContent = (st.final.reason || "Failed") +
          (st.final.recovery ? "  Recovery: " + st.final.recovery : "");
        if (st.error_detail) {
          const d = document.createElement("p");
          d.className = "reason";
          d.textContent = st.error_detail;
          el.resultDetail.appendChild(d);
        }
      }
      el.resultDetail.appendChild(p);
      renderProof(st);
    } else {
      el.resultCard.classList.add("hidden");
    }
  }

  function renderProof(st) {
    el.proof.innerHTML = "";
    const seen = new Set();
    const items = (st.proof || []).filter((x) => x.path);
    for (const it of items.slice(-6)) {
      if (seen.has(it.path)) continue;
      seen.add(it.path);
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.src = proofUrl(it.path);
      img.loading = "lazy";
      img.alt = it.type || "proof";
      const cap = document.createElement("figcaption");
      const label = (it.type || "").replace(/_/g, " ");
      cap.textContent = label + (it.score != null
        ? " · " + Number(it.score).toFixed(2) : "") +
        (it.defects && it.defects.length ? " · issues: " + it.defects.join(",")
         : it.defects ? " · issues: none" : "");
      fig.appendChild(img);
      fig.appendChild(cap);
      el.proof.appendChild(fig);
    }
  }

  /* ---------------- actions ---------------- */
  async function poll() {
    try {
      const st = await api("/api/ua/status");
      render(st);
    } catch (_) {
      /* server briefly down; keep last render */
    }
  }

  async function refreshProjects() {
    try {
      const d = await api("/api/ua/projects");
      const known = d.known || [];
      const lastPath = (d.last && d.last.uproject_path) || "";
      const cur = el.projectSelect.value;
      el.projectSelect.innerHTML =
        '<option value="">Auto — editor already open</option>';
      for (const k of known) {
        const o = document.createElement("option");
        o.value = k.uproject_path || "";
        o.textContent = k.name + " (" + k.uproject_path + ")";
        el.projectSelect.appendChild(o);
      }
      if (cur) el.projectSelect.value = cur;
      else if (lastPath) {
        // preselect the last-used project by default so repeat users
        // never touch a terminal or browse dialog
        el.projectSelect.value = lastPath;
      }
    } catch (_) { /* ignore */ }
  }

  function openConnect() {
    el.connectNote.textContent =
      "Choose a project, then connect. The agent reuses an already-running " +
      "editor and never launches a second one for the same project.";
    el.connectNote.style.color = "";
    el.connectPanel.classList.remove("hidden");
    refreshProjects();
  }

  async function doConnect() {
    el.connectGoBtn.disabled = true;
    el.connectNote.textContent = "Connecting…";
    try {
      await api("/api/ua/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          uproject: el.projectSelect.value || null,
          launch_if_needed: false,
        }),
      });
      el.connectPanel.classList.add("hidden");
    } catch (err) {
      el.connectNote.textContent = "Connect failed: " + err.message;
      el.connectNote.style.color = "#f26d6d";
    } finally {
      el.connectGoBtn.disabled = false;
    }
  }

  async function run() {
    const prompt = el.prompt.value.trim();
    if (!prompt) return;
    runError = null;
    el.resultCard.classList.add("hidden");
    el.runBtn.disabled = true;
    try {
      await api("/api/ua/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      el.prompt.value = "";
    } catch (err) {
      const d = err.detail && typeof err.detail === "object" ? err.detail : null;
      if (d && d.busy) {
        // Step 9 — structured BUSY/OWNED: say exactly why, prove nothing
        // changed, never auto-retry (the lease frees on its own).
        const c = d.conflict || {};
        const exp = c.expires_in_s != null
          ? " (frees in ~" + Math.max(0, Math.round(c.expires_in_s)) + "s)"
          : "";
        runError = "Project is busy — another task is working in this editor"
          + exp + ". No Unreal change was made. Retry when the current task "
          + "finishes (owner: " + (c.owner_id || "?") + ", task: "
          + (c.task_id || "?") + ").";
      } else {
        runError = "Could not start: " + err.message;
      }
      el.hint.textContent = runError;
      el.hint.style.color = "#f26d6d";
    }
  }

  /* ---------------- Step 9 developer diagnostics (read-only) ----------- */
  async function refreshDiagnostics() {
    el.diagResult.textContent = "Checking environment…";
    try {
      const d = await api("/api/ua/env");
      const doc = d.doctor || {};
      const fr = d.first_run || {};
      const lines = [
        "Environment: " + (doc.summary || ""),
        doc.user_error || "",
        "First-run: " + (fr.ready ? "READY" : "not ready") +
          "  (project: " + (fr.project || "none") + ")",
        "Config: backend " + (d.config.backend_url || "") +
          " · bridge " + (d.config.bridge_host || "127.0.0.1") + ":" +
          (d.config.bridge_port || ""),
      ];
      for (const c of (doc.checks || [])) {
        if (c.status !== "PASS") {
          lines.push("  [" + c.status + "] " + c.name + ": " + c.detail);
        }
      }
      el.diagResult.textContent = lines.join("\n");
    } catch (err) {
      el.diagResult.textContent = "Environment check failed: " + err.message;
    }
  }

  async function refreshLeases() {
    el.diagResult.textContent = "Reading ownership…";
    try {
      const d = await api("/api/ua/leases");
      const cur = d.current_project || {};
      const lines = [
        "This product owner: " + (d.owner || ""),
        "Current project lease: " +
          (cur.owned ? "OWNED by " + (cur.owner_id || "?") +
           " (task " + (cur.task_id || "?") +
           ", expires in " + (cur.expires_in_s ?? "?") + "s)"
           : "free (no mutating lease)"),
      ];
      if (!(d.leases || []).length) {
        lines.push("No leases on record.");
      }
      for (const l of d.leases || []) {
        lines.push("  lease: " + (l.identity || "?") + " by " +
          (l.owner_id || "?") + " task " + (l.task_id || "?") +
          (l.mutating ? " [mutating]" : " [read-only]"));
      }
      el.diagResult.textContent = lines.join("\n");
    } catch (err) {
      el.diagResult.textContent = "Lease check failed: " + err.message;
    }
  }

  /* ---------------- wire up ---------------- */
  el.connectBtn.addEventListener("click", openConnect);
  el.connectCancelBtn.addEventListener("click", () =>
    el.connectPanel.classList.add("hidden"));
  el.connectGoBtn.addEventListener("click", doConnect);
  el.reconnectBtn.addEventListener("click", async () => {
    el.reconnectBtn.disabled = true;
    try {
      await api("/api/ua/reconnect", { method: "POST" });
    } catch (err) {
      el.hint.textContent = "Reconnect failed: " + err.message;
    }
  });
  el.runBtn.addEventListener("click", run);
  el.prompt.addEventListener("input", () => {
    runError = null;
    el.hint.style.color = "";
    el.runBtn.disabled = !(el.prompt.value.trim()) ||
      !["READY", "COMPLETE", "FAILED"].includes((last || {}).state || "");
  });
  el.prompt.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") run();
  });
  el.newTaskBtn.addEventListener("click", () => {
    el.resultCard.classList.add("hidden");
    el.prompt.focus();
  });
  el.copyStateBtn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(el.stateJson.textContent); }
    catch (_) { /* clipboard unavailable */ }
  });
  el.envCheckBtn.addEventListener("click", refreshDiagnostics);
  el.leaseCheckBtn.addEventListener("click", refreshLeases);
  refreshDiagnostics();

  poll();
  setInterval(poll, 700);
})();
