/* Aivido Test UI — camera / proof frontend integration.
 *
 * Modern backend endpoints only (legacy /api/ua/* is gone — it 404s on
 * the served backend, so no polling of it happens here):
 *   GET  {base}/api/status                   health + execution state
 *   POST {base}/api/unreal/frame-and-proof   frame + fresh proof in one call
 *   GET  {base}/api/proof/status             proof metadata (fallback)
 *   GET  {base}/api/proof/latest             proof PNG (cache-busted)
 *
 * States: IDLE / WORKING / DONE / ERROR. Base URL is configurable and
 * persisted so the page works from another machine (e.g. the Mac) against
 * the tailnet/funnel URL. Proof refreshes are cache-busted with a
 * timestamp query param, and a completed frame-and-proof auto-refreshes
 * the image.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const LS_KEY = "aivido_test_base_url";

  const el = {
    dot: $("stateDot"), backendState: $("backendState"),
    baseUrl: $("baseUrl"), baseUrlSave: $("baseUrlSave"),
    baseUrlNote: $("baseUrlNote"),
    actorName: $("actorName"), location: $("location"),
    runBtn: $("runBtn"), hint: $("hint"), stateLabel: $("stateLabel"),
    resultDetail: $("resultDetail"),
    pvProof: $("pvProof"), pvEmpty: $("pvEmpty"),
    pvProofMeta: $("pvProofMeta"),
    pvAuto: $("pvAuto"), pvRefresh: $("pvRefresh"),
    footStatus: $("footStatus"),
  };

  let BASE = (localStorage.getItem(LS_KEY) || "").replace(/\/+$/, "");
  let backendOnline = false;
  let backendBusy = false;
  let badge = "IDLE";      // IDLE | WORKING | DONE | ERROR
  let taskRunning = false;

  const u = (path) => BASE + path;

  /* ---------------- helpers ---------------- */
  async function api(path, opts) {
    const r = await fetch(u(path), opts);
    let data = null;
    try { data = await r.json(); } catch (_) { /* empty body */ }
    if (!r.ok) {
      const detail = (data && (data.detail || data.error)) || r.statusText;
      const msg = typeof detail === "string" ? detail
        : detail ? JSON.stringify(detail) : "";
      const e = new Error("HTTP " + r.status + (msg ? " — " + msg : ""));
      e.status = r.status;
      e.detail = data && data.detail !== undefined ? data.detail : data;
      throw e;
    }
    return data;
  }

  function setBadge(st, label) {
    badge = st;
    el.stateLabel.dataset.state = st;
    el.stateLabel.className = "state-label "
      + (st === "DONE" ? "ready" : st === "ERROR" ? "bad"
        : st === "WORKING" ? "busy" : "");
    el.stateLabel.textContent = label || st;
  }

  function setHint(text, isError) {
    el.hint.textContent = text;
    el.hint.style.color = isError ? "#f26d6d" : "";
  }

  function backendDot() {
    el.dot.className = "dot " + (!backendOnline ? "bad"
      : backendBusy ? "busy" : "ready");
    el.backendState.textContent = !backendOnline ? "Offline"
      : backendBusy ? "Busy — agent working" : "Online";
    el.footStatus.textContent = "Backend: " + (BASE || "same origin")
      + " · " + el.backendState.textContent;
  }

  /* ---------------- health / execution state (#2) ---------------- */
  async function pollHealth() {
    try {
      const s = await api("/api/status");
      backendOnline = true;
      backendBusy = !!(s && s.execution_active);
      if (!taskRunning) {
        if (backendBusy && badge === "IDLE") setBadge("WORKING", "WORKING · backend busy");
        else if (!backendBusy && badge === "WORKING") setBadge("IDLE", "IDLE");
      }
    } catch (_) {
      backendOnline = false;
      backendBusy = false;
      if (badge === "IDLE" || badge === "WORKING") setBadge("ERROR", "ERROR · backend offline");
    }
    backendDot();
  }

  /* ---------------- frame & proof (#3, #4) ---------------- */
  function parseLocation(text) {
    if (!text) return null;
    const cleaned = String(text).replace(/[\[\]()]/g, "").trim();
    if (!cleaned) return null;
    const parts = cleaned.split(/[,\s]+/).map(Number);
    if (parts.length === 3 && parts.every((n) => isFinite(n))) return parts;
    return null;
  }

  async function frameAndProof() {
    if (taskRunning) return;
    const actor = el.actorName.value.trim();
    const locText = el.location.value.trim();
    const body = {};
    if (actor) {
      body.actor_name = actor;
    } else if (locText) {
      const loc = parseLocation(locText);
      if (!loc) {
        setBadge("ERROR", "ERROR");
        setHint("Location must be three numbers, e.g. [0, 0, 200].", true);
        return;
      }
      body.location = loc;
    } else {
      setBadge("ERROR", "ERROR");
      setHint("Provide an actor name or a location (e.g. [0, 0, 200]).", true);
      return;
    }

    taskRunning = true;
    setBadge("WORKING", "WORKING");
    setHint(actor
      ? "Framing \u201C" + actor + "\u201D and capturing fresh proof\u2026"
      : "Framing location [" + body.location.join(", ") + "] and capturing fresh proof\u2026");
    el.runBtn.disabled = true;
    el.resultDetail.innerHTML = "";

    try {
      const res = await api("/api/unreal/frame-and-proof", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      taskRunning = false;
      setBadge("DONE", "DONE");
      setHint("Frame & proof complete. Fresh proof loaded below.");
      renderResult(res);
      refreshProof(); // auto-refresh on completion (#4) — always, cache-busted
    } catch (err) {
      taskRunning = false;
      setBadge("ERROR", "ERROR");
      setHint("Frame & proof failed — see details below.", true);
      const d = document.createElement("p");
      d.className = "reason";
      d.textContent = "Frame & proof failed: " + String(err.message || err);
      el.resultDetail.appendChild(d);
    } finally {
      el.runBtn.disabled = false;
    }
  }

  function renderResult(res) {
    el.resultDetail.innerHTML = "";
    const f = res.framing || {};
    const p = res.proof || {};
    const lines = [];
    if (f.actor && f.actor.label) {
      lines.push("Framed actor: " + f.actor.label + " (" + (f.actor.class || "") + ")");
    }
    if (f.target) {
      lines.push("Framed target: [" + f.target.map((n) => Number(n).toFixed(1)).join(", ") + "]");
    }
    if (f.distance != null) lines.push("Camera distance: " + f.distance + " u");
    if (f.look_at_error_deg != null) lines.push("Look-at error: " + f.look_at_error_deg + "\u00B0");
    if (f.viewport_changed != null) lines.push("Viewport changed: " + f.viewport_changed);
    if (p.path) lines.push("Proof file: " + p.path);
    if (p.size) lines.push("Proof size: " + p.size + " bytes");
    if (p.url) lines.push("Proof URL: " + p.url);
    const pre = document.createElement("pre");
    pre.className = "state-json";
    pre.textContent = lines.join("\n") + "\n\n" + JSON.stringify(res, null, 2);
    el.resultDetail.appendChild(pre);
  }

  /* ---------------- proof refresh (#3, #5) ---------------- */
  function refreshProof() {
    const img = el.pvProof;
    const src = u("/api/proof/latest?t=" + Date.now()); // cache-bust
    img.onload = function () {
      el.pvEmpty.hidden = true;
      img.hidden = false;
      el.pvProofMeta.textContent = "Fresh proof \u00B7 "
        + new Date().toLocaleTimeString() + " \u00B7 " + img.naturalWidth
        + "\u00D7" + img.naturalHeight;
    };
    img.onerror = function () {
      img.hidden = true;
      api("/api/proof/status").then(function (st) {
        if (st && st.ok && st.path) {
          el.pvEmpty.hidden = true;
          img.hidden = false;
          img.onload = null;
          img.src = u("/api/proof/latest?t=" + Date.now());
          el.pvProofMeta.textContent = "Proof: " + st.path + " \u00B7 "
            + (st.size || 0) + " bytes";
        } else {
          el.pvEmpty.hidden = false;
          el.pvEmpty.textContent = "No proof yet — run Frame & Proof or press Refresh Proof.";
          el.pvProofMeta.textContent = "\u2014";
        }
      }).catch(function () {
        el.pvEmpty.hidden = false;
        el.pvEmpty.textContent = backendOnline
          ? "No proof available."
          : "Backend offline — cannot fetch proof.";
        el.pvProofMeta.textContent = "\u2014";
      });
    };
    img.src = src;
  }

  /* ---------------- base URL support (#7) ---------------- */
  function saveBase() {
    const v = el.baseUrl.value.trim().replace(/\/+$/, "");
    if (v) {
      BASE = v;
      localStorage.setItem(LS_KEY, v);
    } else {
      BASE = "";
      localStorage.removeItem(LS_KEY);
    }
    el.baseUrl.value = BASE;
    el.baseUrlNote.textContent = BASE
      ? "Saved. Requests go to " + BASE + "."
      : "Empty uses the page origin. Saved in this browser.";
    setHint("Base URL updated.", false);
    pollHealth();
    refreshProof();
  }

  /* ---------------- wire up ---------------- */
  el.baseUrl.value = BASE;
  el.baseUrlSave.addEventListener("click", saveBase);
  el.runBtn.addEventListener("click", frameAndProof);
  el.pvRefresh.addEventListener("click", refreshProof);
  el.actorName.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") frameAndProof();
  });
  el.location.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") frameAndProof();
  });

  pollHealth();
  setInterval(pollHealth, 5000);
  refreshProof();
  setInterval(() => { if (el.pvAuto.checked) refreshProof(); }, 5000);
})();