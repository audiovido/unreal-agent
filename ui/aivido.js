/* ============================================================
   AIVIDO — Director's Booth · UI/UX Phase 1
   Vanilla JS SPA: shell, navigation, agent room + crew states,
   mission driver, choice cards, proof vault, quests, finance,
   profile, settings. Talks to the existing engine where reachable;
   otherwise falls back to a self-contained simulation so every
   screen stays clickable. No backend behavior is modified.
   ============================================================ */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const LS = "aivido_phase1_v1";
  const FAST = /[?&]fast=1/.test(location.search); // test harness: skip the cinematic sting

  /* ---------------- state ---------------- */
  const DEFAULT = {
    name: "Director",
    base: "",
    autoProof: true,
    cinematic: true,
    idle: true,
    sound: true,
    workspace: "AvaLive Living City",
    balance: 120,
    spent: [4, 2, 7, 3, 5, 2, 6],
    achievements: { firstCube: true, goldenHour: true, nightPass: false, fullCrew: true, cleanRun: false, vault5: true },
    missions: [
      { id: "m1", title: "Frontier Garage Showcase", ws: "AvaLive Living City", status: "ACTIVE", progress: 0.55,
        stages: ["Interpret", "Plan", "Assign", "Build", "Verify", "Proof"], cur: 3, verdict: null,
        crew: ["Mason", "Volt", "Ember"], evidence: [] },
      { id: "m2", title: "Living City — Night Pass", ws: "AvaLive Living City", status: "ACTIVE", progress: 0.2,
        stages: ["Interpret", "Plan", "Assign", "Build", "Verify", "Proof"], cur: 1, verdict: null,
        crew: ["Reel", "Veil", "Stride"], evidence: [] },
      { id: "m3", title: "Graduation Showcase", ws: "UA_GradAudit", status: "COMPLETE", progress: 1,
        stages: ["Interpret", "Plan", "Assign", "Build", "Verify", "Proof"], cur: 6, verdict: "PASS",
        crew: ["Mason", "Reel", "Volt", "Ember", "Veil", "Stride", "Patina"], evidence: ["graduation_proof.png"] },
      { id: "m4", title: "Showcase2 — Accent Pass", ws: "ASSET_Showcase2", status: "QUEUED", progress: 0,
        stages: ["Interpret", "Plan", "Assign", "Build", "Verify", "Proof"], cur: 0, verdict: null,
        crew: ["Patina", "Ember"], evidence: [] },
    ],
    quests: [
      { id: "q1", title: "The Long Road — Graduate Showcase", active: true, steps: [
          { t: "Frame the hero garage", done: true }, { t: "Light for golden hour", done: true },
          { t: "Crew of four on one shot", done: true }, { t: "Final proof at ≥ 8.5", done: false }],
        reward: "150 credits · Director Badge" },
      { id: "q2", title: "Daily — First Light", active: true, steps: [
          { t: "Capture one fresh proof", done: true }, { t: "Dispatch the crew once", done: false }],
        reward: "20 credits" },
      { id: "q3", title: "Rite of Passage — First Cube", active: false, steps: [
          { t: "Spawn your first actor", done: true }, { t: "Proof it", done: true }], reward: "Badge · First Cube" },
      { id: "q4", title: "Golden Hour", active: false, steps: [
          { t: "Score a shot ≥ 8.5", done: true }, { t: "No blocking defects", done: true }], reward: "Badge · Golden Hour" },
    ],
    gallery: [],
  };

  function loadState() {
    // safe localStorage recovery: corrupted/unreadable store must never crash the booth
    try {
      const raw = JSON.parse(localStorage.getItem(LS) || "null");
      if (raw && typeof raw === "object") {
        return Object.assign({}, JSON.parse(JSON.stringify(DEFAULT)), raw);
      }
    } catch (_) { /* fall through to fresh defaults */ }
    return JSON.parse(JSON.stringify(DEFAULT));
  }
  let S = loadState();

  /* ---------------- crew ---------------- */
  const WORKERS = [
    { id: "mason", name: "Mason", role: "Environment", color: "#a96b42", ic: "⌂" },
    { id: "patina", name: "Patina", role: "Materials", color: "#8a6f35", ic: "▦" },
    { id: "reel", name: "Reel", role: "Cinematics", color: "#c46a3a", ic: "◉" },
    { id: "volt", name: "Volt", role: "Blueprint", color: "#4f8cff", ic: "⚡" },
    { id: "ember", name: "Ember", role: "VFX", color: "#e2703a", ic: "✸" },
    { id: "veil", name: "Veil", role: "Metahuman", color: "#b98ae0", ic: "♜" },
    { id: "stride", name: "Stride", role: "Animation", color: "#3d9a6b", ic: "➶" },
  ];

  // station tool glyphs — ready-made props, no bespoke modeling
  const TOOLS = { mason: "🧱", patina: "🎨", reel: "🎥", volt: "🔌", ember: "✨", veil: "🪞", stride: "🎞" };

  // worker state: IDLE ASSIGNED THINKING WORKING WAITING ERROR DONE
  let W = WORKERS.map((w) => ({ ...w, state: "IDLE", task: null, err: null, bubble: null, speaking: false }));

  const FOREMAN_LINES = {
    greet: "Welcome back. Crew's been patient — good crew, patient crew.",
    idle: "They ain't idle, they're restin' the wrist. Big job's the real work.",
    dispatch: "Alright! Hands up — we got work. Mason, light the forge. Volt, mind the wiring.",
    thinking: "Think it through. I'd rather you think slow and strike true.",
    working: "There it is. Hear that? That's a crew earnin' its keep.",
    waiting: "Hold steady. Gate's slow, not shut. Waiting's part of the trade.",
    error: "Hold up! Something's burnin' and it ain't the coffee. Let's talk.",
    done: "Clean work. That's how we leave a town — better than we found it.",
    choice: "Your call, boss. Every road pays, but they don't all pay the same.",
    low: "I seen this before — shot's got no bones. We add bones.",
    proof: "That frame's the honest truth. Look close; it don't lie.",
    worker: (n, st) => ({ IDLE: n + "? Sharp eyes, soft hands. Ready when you are.",
      ASSIGNED: n + " knows the job. Just point at the wall.",
      THINKING: "Don't rush " + n + " — that's a plan cookin', not a nap.",
      WORKING: n + "'s got the bit between their teeth now.",
      WAITING: n + " is waitin' on the gate. Patience is a tool too.",
      ERROR: "Talk to " + n + ". Somethin' went sideways and they ain't one to hide it.",
      DONE: n + " finished clean. Check the proof — it'll show." }[st] || n + "'s at the station."),
  };

  /* ---------------- dom refs ---------------- */
  const el = {};
  const REFS = ["app","sting","letterbox","modalRoot","toastRoot","rail","hudScreen","hudWorkspace","hudMode","hudCredits","hudClock","hudSnd","hudAvatar",
    "homeName","homeEnterRoom","homeNewMission","homeCrew","homeCrewState","homeQuote","homeProof","homeMissionPill","homeMission","ledgerFree","ledgerCredits","ledgerQuests",
    "wsGrid","wsNew","mcList","mcDetail","mcNew","roomStage","workersRow","roomDispatch","roomReset","roomSub","roomModePill",
    "foreman","foremanBar","fbLine","fbName","pvStage","pvViewport","pvImg","pvEmpty","pvVerdict","pvScore","pvTime","pvSource","pvDefects","pvGallery","pvCapture","pvAuto",
    "questActive","questDone","finBalance","finPacks","finChart","finLedger",
    "profAvatar","profName","profXpFill","profXpTxt","stMissions","stSuccess","stHours","profSkills","profAch",
    "setBase","setName","setSave","setSaved","setAutoProof","setCinematic","setIdle","setSound","setVersion","railDot","railBackendTxt","homeEnterRoom",
    "holoData","pvPrev","pvNext","pvFull","pvIdx","pvBadge","pvAge","pvApprove","pvChange","liEngine","liCode","liWb","liClickup",
    "ssEngine","ssBridge","ssMap","ssProof","ssExec","dlPrompt","dlDispatch","dlPlan","dlWarn","castGrid","cuStatus","cuDetail"];
  REFS.forEach((r) => (el[r] = $(r)));

  /* ---------------- helpers ---------------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const stClass = (s) => ({ IDLE: "IDLE", ASSIGNED: "ASSIGNED", THINKING: "THINKING", WORKING: "WORKING", WAITING: "WAITING", ERROR: "ERROR", DONE: "DONE" }[s] || "IDLE");
  const workerById = (id) => W.find((w) => w.id === id);
  const persist = () => { try { localStorage.setItem(LS, JSON.stringify(S)); } catch (_) { /* storage full/unavailable → state stays session-local */ } };

  /* request safety: no overlapping pollers, bounded in-flight ops, stale-response tokens */
  const _inflight = { health: false, live: false };
  let _proofReq = 0;        // monotonically increasing — only the latest proof op may render
  let _capturing = false;   // duplicate-click guard for the capture button
  let _dispatchBusy = false; // duplicate-click guard for the dispatch lane

  /* ---------------- sound (lightweight WebAudio, no assets) ---------------- */
  const SFX = (() => {
    let ctx = null, enabled = true;
    function ac() {
      if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (_) {} }
      if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
      return ctx;
    }
    function tone(f, dur = .08, type = "sine", vol = .04, slide = 0) {
      if (!enabled) return;
      const c = ac(); if (!c) return;
      try {
        const o = c.createOscillator(), g = c.createGain();
        o.type = type;
        o.frequency.setValueAtTime(f, c.currentTime);
        if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, f + slide), c.currentTime + dur);
        g.gain.setValueAtTime(vol, c.currentTime);
        g.gain.exponentialRampToValueAtTime(.0001, c.currentTime + dur);
        o.connect(g).connect(c.destination);
        o.start(); o.stop(c.currentTime + dur + .02);
      } catch (_) {}
    }
    return {
      set(v) { enabled = v; },
      on() { ac(); },
      click() { tone(520, .05, "triangle", .028); },
      hover() { tone(760, .04, "sine", .01); },
      confirm() { tone(392, .1, "triangle", .035); setTimeout(() => tone(587, .12, "triangle", .035), 90); },
      error() { tone(220, .18, "sawtooth", .026, -60); },
      success() { tone(523, .09, "triangle", .035); setTimeout(() => tone(659, .09, "triangle", .035), 80); setTimeout(() => tone(784, .14, "triangle", .035), 160); },
      open() { tone(330, .12, "sine", .028, 120); },
      capture() { tone(880, .07, "sine", .03); setTimeout(() => tone(660, .1, "sine", .028, -120), 60); },
    };
  })();

  function toast(title, msg, kind = "info") {
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.innerHTML = `<div class="t-title">${esc(title)}</div>${msg ? `<div>${esc(msg)}</div>` : ""}`;
    el.toastRoot.appendChild(t);
    ({ good: SFX.success, bad: SFX.error, info: SFX.open }[kind] || SFX.click)();
    setTimeout(() => { t.style.transition = "opacity .4s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 420); }, 3800);
  }

  /* ---------------- router ---------------- */
  const SCREENS = { home: "scr-home", workspaces: "scr-workspaces", mission: "scr-mission", room: "scr-room", proof: "scr-proof", quests: "scr-quests", finance: "scr-finance", profile: "scr-profile", settings: "scr-settings" };
  const TITLES = { home: "BOOTH", workspaces: "WORKSPACES", mission: "MISSION CONTROL", room: "AGENT ROOM", proof: "PROOF VAULT", quests: "QUESTS", finance: "FINANCE", profile: "CREATOR PROFILE", settings: "SETTINGS" };

  function route() {
    const nav = (location.hash || "#/home").replace(/^#\/?/, "").split("?")[0];
    return SCREENS[nav] ? nav : "home";
  }

  function show(nav, opts = {}) {
    SFX.click();
    const cur = route();
    Object.keys(SCREENS).forEach((k) => $(SCREENS[k]).classList.remove("on"));
    document.querySelectorAll(".rail-item, .mn-item[data-nav]").forEach((b) => b.classList.toggle("active", b.dataset.nav === nav));
    $(SCREENS[nav]).classList.add("on");
    closeMore();
    el.hudScreen.textContent = TITLES[nav];
    if (nav === "room" && opts.zoom) {
      el.roomStage.classList.remove("room-zoom");
      void el.roomStage.offsetWidth;
      el.roomStage.classList.add("room-zoom");
    }
    render(nav);
    if (location.hash !== "#/" + nav) history.replaceState(null, "", "#/" + nav);
    if (nav !== cur) window.scrollTo && $(SCREENS[nav]).scrollTo && $(SCREENS[nav]).scrollTo(0, 0);
  }

  function navWithCinematic(nav) {
    if (nav === "room" && S.cinematic) {
      el.letterbox.classList.remove("hidden");
      requestAnimationFrame(() => requestAnimationFrame(() => el.letterbox.classList.add("on")));
      setTimeout(() => { show(nav, { zoom: true }); setTimeout(() => { el.letterbox.classList.remove("on"); setTimeout(() => el.letterbox.classList.add("hidden"), 600); }, 420); }, 560);
    } else {
      show(nav);
    }
  }

  /* ---------------- backend ---------------- */
  const apiBase = () => S.base.replace(/\/+$/, "");
  let backend = { online: false, busy: false, mode: "SIMULATION", last: null };
  let live = { session: null, ws: null, tasks: [], wb: null, missions: [], tools: [], proofAge: null };

  async function api(path, opts = {}) {
    // bounded request timeout — no unbounded fetch that can hang a poll forever
    const timeout = opts.timeout || 8000;
    let ctl = null, timer = null;
    if (typeof AbortController !== "undefined") {
      ctl = new AbortController();
      timer = setTimeout(() => ctl.abort(), timeout);
    }
    try {
      const r = await fetch(apiBase() + path, { headers: { "Content-Type": "application/json" }, ...opts, signal: ctl ? ctl.signal : undefined });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const ct = r.headers.get("content-type") || "";
      return ct.includes("json") ? r.json() : r;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async function pollHealth() {
    if (_inflight.health) return; // no overlapping pollers
    _inflight.health = true;
    try {
      const s = await api("/api/status");
      backend.online = true;
      backend.busy = !!s.execution_active;
      backend.mode = "LIVE";
      backend.last = s;
    } catch (_) {
      backend.online = false;
      backend.busy = false;
      backend.mode = "SIMULATION";
    } finally {
      _inflight.health = false;
    }
    const dot = el.railDot, txt = el.railBackendTxt, mode = el.hudMode;
    dot.className = "dot-sm " + (backend.online ? (backend.busy ? "busy" : "ready") : "bad");
    txt.textContent = backend.online ? (backend.busy ? "engine busy" : "engine linked") : "simulation mode";
    mode.textContent = backend.mode;
    mode.className = "hud-mode pill-sm " + (backend.mode === "LIVE" ? "live" : "sim");
    el.roomModePill.textContent = backend.mode === "LIVE" ? "LIVE ENGINE" : "SIMULATION";
    el.roomModePill.style.cssText = backend.mode === "LIVE" ? "color:var(--ok);border-color:rgba(110,207,142,.4)" : "";
    if (backend.online) refreshBackendProof(false);
    if (backend.online) pollLive();
    if (backend.online && !live.tools.length) detectClickUp();
    renderSysStrip();
  }

  /* ---------------- live engine data (read-only) ---------------- */
  async function pollLive() {
    if (!backend.online) return;
    if (_inflight.live) return; // no overlapping pollers
    _inflight.live = true;
    try {
      try { const r = await api("/api/unreal-coder/session"); live.session = (r && r.session) || null; } catch (_) {}
      try { live.ws = await api("/api/workspace"); } catch (_) {}
      try { const r = await api("/api/code/tasks"); live.tasks = (r && r.tasks) || []; } catch (_) {}
      try { const r = await api("/api/workboard/state"); live.wb = (r && r.data) || null; } catch (_) {}
    } finally {
      _inflight.live = false;
    }
    if (route() === "room") renderHoloData();
    if (route() === "mission") renderMission();
    if (route() === "workspaces") renderWorkspaces();
    if (route() === "settings") renderLiveIntegrations();
  }

  function renderHoloData() {
    const d = el.holoData; if (!d) return;
    if (backend.online && live.session) {
      d.innerHTML = `${esc(live.session.project_name || "—")}<br>${esc(live.session.active_map || "no map loaded")}<br>UE ${esc(String(live.session.engine_version || "").split("+")[0])}`;
    } else if (backend.online) {
      d.innerHTML = `ENGINE LINKED<br>SESSION …<br>AWAITING MAP`;
    } else {
      d.innerHTML = `SIMULATION<br>NO ENGINE LINK<br>CREW AT REST`;
    }
  }

  function renderLiveIntegrations() {
    const set = (id, txt, cls) => { const e = $(id); if (e) { e.textContent = txt; e.className = "li-v " + cls; } };
    set("liEngine", backend.online ? (backend.busy ? "LIVE · engine busy" : "LIVE · engine ready") : "SIMULATION · offline", backend.online ? "ok" : "off");
    const nCode = live.tasks.length;
    set("liCode", backend.online ? (nCode ? nCode + " real task" + (nCode > 1 ? "s" : "") + " on file" : "LIVE · empty store") : "offline", backend.online ? (nCode ? "ok" : "warn") : "off");
    const wb = live.wb; const nWb = wb ? (wb.tasks || []).length + (wb.sprints || []).length : 0;
    set("liWb", backend.online ? (nWb ? nWb + " workboard entries" : "LIVE · empty board") : "offline", backend.online ? (nWb ? "ok" : "warn") : "off");
    set("liClickup", "blocked — no API credentials in this environment", "blocked");
  }

  /* ---------------- modals: focus management ---------------- */
  let _lastFocus = null;
  function focusables(root) {
    return [...(root || document).querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.disabled && x.offsetParent !== null);
  }
  function openModal() {
    _lastFocus = document.activeElement;
    el.modalRoot.classList.remove("hidden");
    const f = focusables(el.modalRoot)[0];
    if (f) f.focus();
  }
  function closeModal() {
    el.modalRoot.classList.add("hidden");
    if (_lastFocus && _lastFocus.focus) { try { _lastFocus.focus(); } catch (_) {} }
  }
  function trapFocus(e) {
    if (e.key !== "Tab" || el.modalRoot.classList.contains("hidden")) return;
    const f = focusables(el.modalRoot);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || !el.modalRoot.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !el.modalRoot.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  }
  function closeMore() { const m = $("moreSheet"); if (m && !m.classList.contains("hidden")) m.classList.add("hidden"); }

  /* ---------------- workspace scaffold (local, truthful CONCEPT) ---------------- */
  const WSLS = "aivido_workspaces_v1";
  function wsStore() { let w = { version: 1, created: [] }; try { w = Object.assign(w, JSON.parse(localStorage.getItem(WSLS) || "{}")); } catch (_) {} return w; }
  function wsPersist(w) { try { localStorage.setItem(WSLS, JSON.stringify(w)); } catch (_) {} return w; }

  function openWsCreate() {
    el.modalRoot.innerHTML = "";
    const d = document.createElement("div");
    d.className = "choice-modal dossier";
    d.innerHTML = `<div class="dos-head"><div class="dos-ic">▦</div><div><p class="choice-eyebrow">NEW WORKSPACE · LOCAL SCAFFOLD</p><h2>Scaffold a fresh world</h2></div></div>
      <p class="dos-state">Creates a <b>local Booth entry only</b> — opening a real project in the engine is the engine lane's job.</p>
      <div class="field"><label for="wsName">Workspace name</label><input id="wsName" class="textinput" placeholder="e.g. Canyon Foundry" maxlength="48" autocomplete="off"></div>
      <div class="field"><label for="wsTpl">Starting template</label><select id="wsTpl" class="textinput">
        <option value="Blank map (UE 5.8)">Blank map (UE 5.8)</option>
        <option value="Showcase arena">Showcase arena</option>
        <option value="Graduation audit rig">Graduation audit rig</option>
      </select></div>
      <p class="muted" style="font-size:11px">Label: <b>CONCEPT</b> until an engine session actually opens it. Nothing is created outside the Booth.</p>
      <div class="row" style="justify-content:flex-end"><button class="btn small ghost" data-c-close>Cancel</button><button class="btn small primary" data-c-ok>Create entry</button></div>`;
    el.modalRoot.appendChild(d);
    openModal();
    d.querySelector("[data-c-close]").onclick = () => { closeModal(); SFX.click(); };
    d.querySelector("[data-c-ok]").onclick = () => {
      const name = d.querySelector("#wsName").value.trim();
      if (!name) return toast("Name required", "Give the workspace a name.", "bad");
      const tpl = d.querySelector("#wsTpl").value;
      const st = wsStore();
      st.created = [{ id: "ws_" + Date.now().toString(36), name: name, template: tpl, status: "CONCEPT", source: "LOCAL", meta: tpl + " · scaffolded " + new Date().toLocaleDateString() + " · CONCEPT", art: "linear-gradient(135deg,#3a2f1c,#16100a)", created: new Date().toISOString() }, ...(st.created || [])];
      wsPersist(st);
      closeModal(); SFX.confirm();
      toast("Workspace scaffolded", name + " added to the Booth as CONCEPT — open it in the engine to go LIVE.", "good");
      renderWorkspaces();
    };
    SFX.open();
    d.querySelector("#wsName").focus();
  }

  function openWsDetail(w) {
    el.modalRoot.innerHTML = "";
    const d = document.createElement("div");
    d.className = "choice-modal dossier";
    d.innerHTML = `<div class="dos-head"><div class="dos-ic">▦</div><div><p class="choice-eyebrow">PROJECT DETAIL</p><h2>${esc(w.name)}</h2></div></div>
      <div class="dos-slot"><b>Source:</b> ${esc(w.source || "DEMO")}<br>
        <b>Status:</b> ${esc(w.status || "—")}<br>
        <b>Engine:</b> UE 5.8 · ${esc(w.up || "not linked to a running session")}<br>
        <b>Meta:</b> ${esc(w.meta || "—")}</div>
      <p class="muted" style="font-size:11px">Project detail reflects what the Booth knows. The engine lane owns the actual project files.</p>
      <div class="row" style="justify-content:flex-end"><button class="btn small ghost" data-c-close>Close</button><button class="btn small primary" data-c-select>Select workspace</button></div>`;
    el.modalRoot.appendChild(d);
    openModal();
    d.querySelector("[data-c-close]").onclick = () => { closeModal(); SFX.click(); };
    d.querySelector("[data-c-select]").onclick = () => { S.workspace = w.name; persist(); el.hudWorkspace.textContent = w.name; closeModal(); SFX.confirm(); toast("Workspace selected", w.name, "good"); };
    SFX.open();
  }

  /* ---------------- proof ---------------- */
  function demoCapture(name = "demo") {
    const c = document.createElement("canvas");
    c.width = 1280; c.height = 720;
    const x = c.getContext("2d");
    // dusk sky
    const g = x.createLinearGradient(0, 0, 0, 720);
    g.addColorStop(0, "#3d2a1a"); g.addColorStop(.45, "#e8895a"); g.addColorStop(.75, "#ffb46b"); g.addColorStop(1, "#241609");
    x.fillStyle = g; x.fillRect(0, 0, 1280, 720);
    // sun
    x.fillStyle = "rgba(255,240,210,.95)";
    x.beginPath(); x.arc(940, 190, 70, 0, 7); x.fill();
    x.fillStyle = "rgba(255,217,160,.25)";
    x.beginPath(); x.arc(940, 190, 120, 0, 7); x.fill();
    // mesas
    x.fillStyle = "#2a1c10"; x.beginPath();
    x.moveTo(0, 460); x.lineTo(160, 260); x.lineTo(330, 430); x.lineTo(560, 190); x.lineTo(760, 440); x.lineTo(980, 240); x.lineTo(1280, 420); x.lineTo(1280, 720); x.lineTo(0, 720); x.fill();
    x.fillStyle = "#1c1208"; x.beginPath();
    x.moveTo(0, 560); x.lineTo(240, 360); x.lineTo(480, 540); x.lineTo(760, 330); x.lineTo(1280, 520); x.lineTo(1280, 720); x.lineTo(0, 720); x.fill();
    // garage cabin
    x.fillStyle = "#3a2813"; x.fillRect(150, 400, 260, 200);
    x.fillStyle = "#2a1c10"; x.beginPath(); x.moveTo(120, 400); x.lineTo(280, 300); x.lineTo(440, 400); x.fill();
    x.fillStyle = "#ffb76b"; x.fillRect(250, 440, 60, 60);
    x.fillStyle = "#241609"; x.fillRect(170, 470, 60, 90); x.fillRect(330, 470, 60, 90);
    // score HUD
    x.fillStyle = "rgba(10,7,4,.72)"; x.fillRect(0, 0, 1280, 64);
    x.font = "600 22px Inter, sans-serif"; x.fillStyle = "#e8c878";
    x.fillText("◈ AIVIDO · FRESH PROOF", 24, 40);
    x.font = "600 18px JetBrains Mono, monospace"; x.fillStyle = "#6ecf8e";
    x.fillText("SCORE 8.7 / 10", 1010, 40);
    x.font = "14px JetBrains Mono, monospace"; x.fillStyle = "rgba(242,233,216,.75)";
    x.fillText("no blocking defects · subject coverage 41% · " + new Date().toLocaleTimeString(), 24, 706);
    return c.toDataURL("image/png");
  }

  function pushGallery(entry) {
    S.gallery = [entry, ...S.gallery].slice(0, 6);
    persist();
    renderGallery();
  }

  async function captureProof() {
    if (_capturing) return toast("Capture already running", "One frame at a time — the viewport is busy.", "info");
    _capturing = true;
    const my = ++_proofReq;
    toast("Capture started", "Framing the shot and pulling a fresh frame…", "info");
    const start = Date.now();
    let entry;
    try {
      const res = await api("/api/unreal/frame-and-proof", {
        method: "POST", body: JSON.stringify({ location: [0, 0, 200] }), timeout: 20000,
      });
      const img = new Image();
      await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = apiBase() + (res.url || "/api/proof/latest") + "?t=" + Date.now(); });
      const d = res.framing || res.proof || {};
      entry = { src: img.src, verdict: "PASS", score: d.score != null ? Number(d.score).toFixed(1) : "—", at: new Date().toISOString(), source: "LIVE", defects: d.defects || [], meta: (d.path || d.url || "live frame") + " · " + (d.size || img.naturalWidth + "×" + img.naturalHeight) + " bytes" };
    } catch (_) {
      // engine unreachable → simulation capture so the UX stays functional
      await new Promise((r) => setTimeout(r, 1100));
      const d = demoCapture();
      entry = { src: d, verdict: "PASS", score: "8.7", at: new Date().toISOString(), source: "DEMO", defects: [], meta: "1280×720 · simulation frame · engine offline" };
      toast("Demo capture", "Engine unreachable — captured a simulation frame instead.", "info");
    } finally {
      _capturing = false;
    }
    if (my !== _proofReq) return; // stale response — a newer capture/refresh already won
    const ms = Date.now() - start;
    questTick("capture"); ledgerAdd("capture", "Proof capture (" + entry.source + ")", 0);
    pushGallery(entry);
    showProofEntry(entry);
    foremanSay(FOREMAN_LINES.proof, 5200);
    toast("Proof minted", entry.source + " frame in " + (ms / 1000).toFixed(1) + "s · score " + entry.score, "good");
  }

  async function refreshBackendProof(force) {
    if (!backend.online) return;
    const my = ++_proofReq;
    try {
      const st = await api("/api/proof/status");
      if (my !== _proofReq) return; // stale response — a newer op superseded this one
      if (st && st.ok && st.path) {
        live.proofAge = Math.max(0, (Date.now() / 1000) - (st.mtime || Date.now() / 1000));
        renderSysStrip();
        const entry = { src: apiBase() + "/api/proof/latest?t=" + Date.now(), verdict: st.verdict || "—", score: st.score != null ? Number(st.score).toFixed(1) : "—", at: new Date().toISOString(), source: "LIVE", defects: st.defects || [], meta: st.path };
        showProofEntry(entry);
      }      } catch (_) { /* engine proof not ready yet */ }
  }

  function showProofEntry(entry, idx) {
    if (idx != null) { S._pvIdx = idx; }
    else if (S.gallery.length) {
      const found = S.gallery.indexOf(entry);
      S._pvIdx = found >= 0 ? found : 0;
    }
    const img = el.pvImg;
    img.classList.remove("loaded"); // re-trigger the reveal transition
    img.onload = () => { el.pvEmpty.hidden = true; img.hidden = false; img.classList.add("loaded"); };
    img.src = entry.src;
    el.pvVerdict.textContent = entry.verdict || "—";
    el.pvVerdict.className = "pv-v " + String(entry.verdict || "").toLowerCase();
    el.pvScore.textContent = entry.score || "—";
    el.pvTime.textContent = entry.at ? new Date(entry.at).toLocaleTimeString() : "—";
    el.pvSource.textContent = (entry.source || "—") + (entry.approved ? " · approved ✓" : "");
    el.pvDefects.innerHTML = (entry.defects && entry.defects.length)
      ? "<b>Notes:</b> " + entry.defects.map(esc).join(" · ") : "<i>No blocking defects.</i>";
    const isLive = entry.source === "LIVE";
    el.pvBadge.textContent = isLive ? "LIVE FRAME" : "DEMO FRAME";
    el.pvBadge.className = "pv-badge " + (isLive ? "live" : "demo");
    el.pvIdx.textContent = S.gallery.length ? (S._pvIdx + 1) + " / " + S.gallery.length : "";
    if (el.pvAge) {
      if (isLive && live.proofAge != null) {
        const mins = Math.floor(live.proofAge / 60);
        el.pvAge.textContent = live.proofAge < 90 ? "fresh · " + Math.max(1, Math.round(live.proofAge)) + "s" : "fresh · " + mins + "m old";
        el.pvAge.className = "pv-age " + (live.proofAge < 900 ? "fresh" : "stale");
      } else if (isLive) {
        el.pvAge.textContent = "freshness unknown";
        el.pvAge.className = "pv-age";
      } else {
        el.pvAge.textContent = "simulation frame";
        el.pvAge.className = "pv-age";
      }
    }
  }

  function proofStep(dir) {
    if (!S.gallery.length) return;
    const n = S.gallery.length;
    const i = ((S._pvIdx == null ? 0 : S._pvIdx) + dir + n) % n;
    showProofEntry(S.gallery[i], i);
    SFX.click();
  }

  function approveProof() {
    const i = S._pvIdx == null ? 0 : S._pvIdx;
    const e = S.gallery[i];
    if (!e) return;
    e.approved = true;
    persist(); renderGallery(); showProofEntry(e, i);
    toast("Proof approved", "Reviewed and kept for the record.", "good");
  }

  function requestChange() {
    const i = S._pvIdx == null ? 0 : S._pvIdx;
    const e = S.gallery[i];
    if (!e) return;
    e.approved = false;
    persist(); renderGallery(); showProofEntry(e, i);
    toast("Change requested", "Rework flag set — noted on the mission board.", "info");
  }

  function renderGallery() {
    el.pvGallery.innerHTML = "";
    if (!S.gallery.length) {
      const d = document.createElement("div");
      d.className = "pv-thumb pv-thumb-add"; d.textContent = "＋";
      d.title = "Capture your first proof";
      d.onclick = captureProof;
      el.pvGallery.appendChild(d);
      return;
    }
    S.gallery.forEach((g, i) => {
      const t = document.createElement("div");
      t.className = "pv-thumb" + (i === 0 ? " sel" : "");
      t.innerHTML = `<img src="${g.src}" alt="proof ${i + 1}"><div class="pv-cap">${g.approved ? "✓ " : ""}${esc(g.source)} · ${esc(g.score)}</div>`;
      t.onclick = () => { showProofEntry(g, i); document.querySelectorAll(".pv-thumb").forEach((x) => x.classList.remove("sel")); t.classList.add("sel"); };
      el.pvGallery.appendChild(t);
    });
    const add = document.createElement("div");
    add.className = "pv-thumb pv-thumb-add"; add.textContent = "＋"; add.title = "Capture fresh proof";
    add.onclick = captureProof;
    el.pvGallery.appendChild(add);
  }

  /* ---------------- room / crew ---------------- */
  function foremanSay(line, ms = 4200) {
    const f = el.foreman;
    el.fbLine.textContent = line;
    f.classList.add("speaking");
    const bb = f.querySelector(".person-bubble");
    if (bb) bb.textContent = line.length > 46 ? line.slice(0, 44) + "…" : line;
    clearTimeout(foremanSay._t);
    foremanSay._t = setTimeout(() => f.classList.remove("speaking"), ms);
  }

  function renderRoom() {
    el.workersRow.innerHTML = "";
    W.forEach((w) => {
      const st = stClass(w.state);
      const stn = document.createElement("div");
      stn.className = "worker-station wk p-" + w.id + " " + st + (st === "WORKING" ? " striking" : "");
      stn.id = "wk-" + w.id;
      stn.style.setProperty("--wk-c", w.color);
      stn.innerHTML = `
        <div class="person wk">
          ${st === "THINKING" ? '<div class="wk-think">···</div>' : ""}
          ${st === "WAITING" ? '<div class="wk-wait">⧗</div>' : ""}
          ${st === "ERROR" ? '<div class="wk-alert">!</div>' : ""}
          ${st === "DONE" ? '<div class="wk-done">✓</div>' : ""}
          ${st === "WORKING" ? '<div class="wk-spark">✦</div>' : ""}
          <div class="head"></div>
          <div class="wk-hair"></div>
          <div class="wk-cap"></div>
          <div class="wk-band"></div>
          <div class="body"></div>
          <div class="arm a-l"></div><div class="arm a-r"></div>
          <div class="wk-tool">${TOOLS[w.id] || ""}</div>
        </div>
        <div class="worker-name"><b>${w.name}</b></div>
        <div class="worker-role">${w.role}</div>
        <span class="wk-badge">${w.state}${w.task ? " · " + w.task : ""}</span>
        <div class="worker-desk"></div>`;
      stn.onclick = () => openDossier(w);
      el.workersRow.appendChild(stn);
    });
  }

  function workerCheckIn(w) {
    const st = stClass(w.state);
    foremanSay(FOREMAN_LINES.worker(w.name, st), 4600);
    const node = document.getElementById("wk-" + w.id);
    const p = node && node.querySelector(".person");
    if (p) {
      p.classList.add("speaking");
      const bb = document.createElement("div");
      bb.className = "person-bubble";
      bb.textContent = st === "ERROR" ? "fault on my station!" : st === "DONE" ? "clean handoff." : "on it, boss.";
      p.appendChild(bb);
      setTimeout(() => { p.classList.remove("speaking"); const b = p.querySelector(".person-bubble"); if (b) b.remove(); }, 2400);
    }
    if (st === "ERROR") toast(w.name + " hit a snag", w.err || "Station fault — inspect before proceeding.", "bad");
    if (st === "DONE") toast(w.name + " finished", "Clean handoff recorded.", "good");
  }

  function setState(w, state, task, err) {
    w.state = state; w.task = task || null; w.err = err || null;
    if (state === "ERROR") SFX.error();
    if (state === "DONE") SFX.success();
    const node = document.getElementById("wk-" + w.id);
    if (node) {
      node.className = "worker-station wk p-" + w.id + " " + stClass(state) + (state === "WORKING" ? " striking" : "");
      const badge = node.querySelector(".wk-badge");
      if (badge) badge.textContent = state + (task ? " · " + task : "");
      // swap status glyphs
      const p = node.querySelector(".person");
      ["wk-think", "wk-wait", "wk-alert", "wk-done", "wk-spark"].forEach((c) => { const e = p.querySelector("." + c); if (e) e.remove(); });
      if (state === "THINKING") p.insertAdjacentHTML("beforeend", '<div class="wk-think">···</div>');
      if (state === "WAITING") p.insertAdjacentHTML("beforeend", '<div class="wk-wait">⧗</div>');
      if (state === "ERROR") p.insertAdjacentHTML("beforeend", '<div class="wk-alert">!</div>');
      if (state === "DONE") p.insertAdjacentHTML("beforeend", '<div class="wk-done">✓</div>');
      if (state === "WORKING") p.insertAdjacentHTML("beforeend", '<div class="wk-spark">✦</div>');
    }
    if (route() === "home") renderHomeCrew();
    if (route() === "mission") renderMissionList();
  }

  function renderHomeCrew() {
    if (!el.homeCrew) return;
    el.homeCrew.innerHTML = "";
    W.forEach((w) => {
      const c = document.createElement("div");
      c.className = "crew-chip";
      c.innerHTML = `<span class="st-dot ${stClass(w.state)}"></span> ${esc(w.name)} <span class="muted">${w.state}</span>`;
      el.homeCrew.appendChild(c);
    });
    const active = W.filter((w) => w.state !== "IDLE" && w.state !== "DONE").length;
    el.homeCrewState.textContent = active ? active + " of " + W.length + " busy" : "crew at rest";
    el.homeQuote.textContent = ["“Every shot is a promise. We aim to keep it.”", "“Slow is smooth, smooth is fast — same in the editor.”", "“A clean frame is worth a hundred clean excuses.”", "“The engine don't lie. The proof don't either.”"][Math.floor(Math.random() * 4)];
  }

  /* ambient idle life: workers naturally fidget, foreman mutters */
  let ambientTimer = null;
  function startAmbient() {
    stopAmbient();
    ambientTimer = setInterval(() => {
      if (route() !== "room" || !S.idle) return;
      const idle = W.filter((w) => w.state === "IDLE");
      if (idle.length && Math.random() < .5) {
        const w = idle[Math.floor(Math.random() * idle.length)];
        const f = document.getElementById("wk-" + w.id);
        const p = f && f.querySelector(".person");
        if (p) {
          p.classList.remove("speaking");
          void p.offsetWidth;
          p.classList.add("speaking");
          const bb = document.createElement("div");
          bb.className = "person-bubble";
          bb.textContent = ["…", "restin' the wrist", "hot coffee nearby", "saw a good shot yesterday", "just thinkin'"].sort(() => Math.random() - .5)[0];
          p.appendChild(bb);
          setTimeout(() => { const b = p.querySelector(".person-bubble"); if (b && !p.classList.contains("speaking")) b.remove(); }, 2600);
        }
      }
      if (Math.random() < .22) foremanSay(["…", "Crew's quiet. I like quiet.", "That lamp flicker? It's the tech breathin'.", "Proof before promises, boss.", "The gate's warm — someone's been workin'."].sort(() => Math.random() - .5)[0], 3000);
    }, 5200);
  }
  function stopAmbient() { if (ambientTimer) { clearInterval(ambientTimer); ambientTimer = null; } }

  /* ---------------- mission driver ---------------- */
  let missionTimer = null;
  const MISSION_STAGES = ["Interpret", "Plan", "Assign", "Build", "Verify", "Proof", "Complete"];
  const CHOICES = [
    { title: "Steady Hand", rarity: "common", ic: "🛠", desc: "Refine the lighting pass first. Slow, safe, clean.", tags: [["risk", "LOW"], ["reward", "SAFE"]], path: "safe" },
    { title: "Bold Play", rarity: "rare", ic: "⚔", desc: "Rebuild the hero prop with the full crew. Bigger swing, bigger payoff.", tags: [["risk", "HIGH"], ["reward", "EPIC"]], path: "bold" },
    { title: "Delegate", rarity: "epic", ic: "☩", desc: "Split the work across specialist stations and run parallel.", tags: [["risk", "MED"], ["reward", "FAME"]], path: "split" },
  ];

  function startDemoMission(mId = "m1") {
    if (missionTimer) return toast("Mission running", "The crew is already at work — check Mission Control.", "info");
    const m = S.missions.find((x) => x.id === mId) || S.missions.find((x) => x.id === "m1");
    m.cur = 2; m.status = "ACTIVE"; m.progress = 0.28;
    foremanSay(FOREMAN_LINES.dispatch, 5200);
    toast("Crew dispatched", "Frontier Garage Showcase is underway.", "good");
    // assign crew
    questTick("dispatch"); ledgerAdd("dispatch", "Crew dispatch (simulation)", 0);
    const crew = W.filter((w) => ["mason", "volt", "ember"].includes(w.id));
    crew.forEach((w, i) => setTimeout(() => setState(w, "ASSIGNED", "intake", null), 300 * i));
    setTimeout(() => crew.forEach((w) => setState(w, "THINKING", "plan", null)), 1400);
    foremanSay(FOREMAN_LINES.thinking, 4800);
    setTimeout(() => crew.forEach((w) => setState(w, "WORKING", "build", null)), 3000);
    foremanSay(FOREMAN_LINES.working, 5000);
    m.cur = 3; m.progress = 0.55; renderMissionList();
    // choice moment at plan review
    missionTimer = setTimeout(() => { openChoices(); missionTimer = null; }, 5600);
  }

  function openChoices() {
    const tpl = document.getElementById("tplChoice");
    const frag = tpl.content.cloneNode(true);
    const grid = frag.querySelector('[data-c="grid"]');
    CHOICES.forEach((c) => {
      const b = document.createElement("button");
      b.className = "choice-card rarity-" + c.rarity;
      b.innerHTML = `<span class="cc-rarity">${c.rarity.toUpperCase()}</span><div class="cc-ic">${c.ic}</div><h3>${esc(c.title)}</h3><p>${esc(c.desc)}</p><div class="cc-tags">${c.tags.map(([k, v]) => `<span class="${k}">${v}</span>`).join("")}</div>`;
      b.onclick = () => resolveChoice(c);
      grid.appendChild(b);
    });
    el.modalRoot.innerHTML = "";
    el.modalRoot.appendChild(frag);
    openModal();
    foremanSay(FOREMAN_LINES.choice, 5000);
  }

  function resolveChoice(c) {
    closeModal();
    const m = S.missions.find((x) => x.id === "m1");
    toast("Plan locked — " + c.title, c.rarity.toUpperCase() + " play. Crew adjusts.", c.rarity === "common" ? "info" : "good");
    if (c.path === "bold") {
      // high risk: ember blows a fuse, recovers
      const ember = workerById("ember");
      setState(ember, "ERROR", "VFX", "Niagara burst overflowed the budget — gate caught it.");
      foremanSay(FOREMAN_LINES.error, 4600);
      toast("Station fault", "Ember flagged a VFX overflow. The gate held.", "bad");
      setTimeout(() => { setState(ember, "WAITING", "retry", null); setState(workerById("volt"), "WAITING", "verify", null); foremanSay("Breathe, crew. Volt, walk it back. We retry clean.", 4400); }, 2600);
      setTimeout(() => { setState(ember, "WORKING", "rework", null); setState(workerById("volt"), "WORKING", "verify", null); }, 5200);
    } else if (c.path === "split") {
      const extra = W.filter((w) => ["patina", "reel"].includes(w.id));
      extra.forEach((w) => setState(w, "ASSIGNED", "parallel", null));
      setTimeout(() => extra.forEach((w) => setState(w, "WORKING", "build", null)), 900);
      foremanSay("Parallel hands! Watch the seams — two artists, one shot.", 4600);
    } else {
      const mason = workerById("mason");
      setState(mason, "WAITING", "lighting gate", null);
      foremanSay("Steady it is. Mason, hold that key light where I can see it.", 4400);
      setTimeout(() => setState(mason, "WORKING", "light pass", null), 2400);
    }
    // advance to verify
    setTimeout(() => {
      W.forEach((w) => { if (["WORKING", "ASSIGNED", "THINKING"].includes(w.state)) setState(w, "WAITING", "verify gate", null); });
      foremanSay("Build's in. Gate's turnin'. Let the machine look at it.", 4400);
      m.cur = 4; m.progress = 0.8; renderMissionList();
      setTimeout(() => {
        W.forEach((w) => { if (w.state === "WAITING") setState(w, "DONE", null, null); });
        m.cur = 6; m.progress = 1; m.status = "COMPLETE"; m.verdict = "PASS";
        m.evidence = ["frontier_garage_proof.png"];
        renderMissionList(); renderHome();
        foremanSay(FOREMAN_LINES.done, 5200);
        toast("Mission complete", "Frontier Garage Showcase · PASS · proof minted to the vault.", "good");
        S.balance += 40; S.achievements.cleanRun = true; persist();
        ledgerAdd("reward", "Mission reward — Frontier Garage (demo)", +40);
        setTimeout(() => captureProof(), 900);
      }, 3600);
    }, 5600);
  }

  /* ---------------- screen renders ---------------- */
  function render(nav) {
    ({ home: renderHome, workspaces: renderWorkspaces, mission: renderMission, room: renderRoomScreen, proof: renderProofScreen, quests: renderQuests, finance: renderFinance, profile: renderProfile, settings: renderSettings }[nav] || (() => {}))();
  }

  function renderHome() {
    el.homeName.textContent = S.name;
    renderHomeCrew();
    el.homeMissionPill.textContent = (S.missions.find((m) => m.status === "ACTIVE") ? "RUNNING" : "STANDBY");
    const active = S.missions.find((m) => m.status === "ACTIVE");
    el.homeMission.textContent = active ? active.title + " — stage " + active.stages[Math.max(0, active.cur - 1)] + " · " + Math.round(active.progress * 100) + "%" : "No mission running. The crew awaits orders.";
    el.ledgerFree.textContent = "∞";
    el.ledgerCredits.textContent = S.balance;
    el.ledgerQuests.textContent = S.quests.filter((q) => q.active).length;
    const latest = S.gallery[0];
    if (latest) {
      el.homeProof.innerHTML = `<img src="${latest.src}" alt="latest proof">`;
    } else {
      el.homeProof.innerHTML = '<div class="proof-thumb-empty">No capture yet — run a mission to mint fresh proof.</div>';
    }
  }

  function renderWorkspaces() {
    const WS = [
      { name: "AvaLive Living City", art: "linear-gradient(135deg,#3a2412,#140e08)", meta: "UE 5.8 · last open 12m ago · DEMO", status: "ACTIVE", up: "C:/Users/Shadow/Desktop/AvaLive/AvaLive.uproject" },
      { name: "ASSET_Showcase2", art: "linear-gradient(135deg,#241c10,#0e0a06)", meta: "UE 5.8 · last open 2h ago · DEMO", status: "READY", up: "ASSET_Showcase2" },
      { name: "UA_GradAudit", art: "linear-gradient(135deg,#331f10,#120c06)", meta: "UE 5.8 · graduation rig · DEMO", status: "READY", up: "UA_GradAudit" },
      { name: "Desert Studio (scratch)", art: "linear-gradient(135deg,#4a2e18,#1a1008)", meta: "Blank · not opened yet · DEMO", status: "NEW", up: "" },
    ];
    el.wsGrid.innerHTML = "";
    if (backend.online && live.ws) {
      const lc = document.createElement("div");
      lc.className = "ws-card live";
      const proj = (live.session && live.session.project_name) || live.ws.project || "Engine project";
      const branch = live.ws.branch || "";
      const commit = String(live.ws.commit || "").slice(0, 7);
      const eng = live.session && live.session.engine_version ? "UE " + String(live.session.engine_version).split("+")[0] : "";
      const map = live.session && live.session.active_map ? " · " + live.session.active_map : "";
      lc.innerHTML = `<div class="ws-art" style="background:linear-gradient(135deg,#12302c,#0a1a17)"></div>
        <div class="ws-body"><h3>${esc(proj)} <span class="mc-tag live">LIVE</span></h3>
        <div class="ws-meta">${esc(branch)} · ${esc(commit)}${eng ? " · " + esc(eng) : ""}${esc(map)}</div>
        <div class="ws-foot"><span class="pill-sm">ENGINE-LINKED</span><button class="btn small primary">Active Now</button></div></div>`;
      lc.querySelector(".btn").onclick = (e) => { e.stopPropagation(); toast("Engine project", proj + " is already selected in the running session.", "info"); };
      lc.onclick = () => { S.workspace = proj; persist(); el.hudWorkspace.textContent = proj; toast("Workspace selected", proj + " (live engine project)", "good"); };
      el.wsGrid.appendChild(lc);
    }
    WS.forEach((w) => {
      const c = document.createElement("div");
      c.className = "ws-card";
      c.innerHTML = `<div class="ws-art" style="background:${w.art}"></div>
        <div class="ws-body"><h3>${esc(w.name)}</h3>
        <div class="ws-meta">${esc(w.meta)}</div>
        <div class="ws-foot"><span class="pill-sm">${w.status}</span><button class="btn small primary">Open</button></div></div>`;
      c.querySelector(".btn").onclick = (e) => { e.stopPropagation(); S.workspace = w.name; persist(); toast("Workspace set", w.name + " is now the active world.", "good"); el.hudWorkspace.textContent = w.name; };
      c.onclick = () => openWsDetail({ name: w.name, meta: w.meta, status: w.status, up: w.up, source: "DEMO" });
      el.wsGrid.appendChild(c);
    });
    // local scaffolds created inside the Booth (truthful CONCEPT until opened in the engine)
    (wsStore().created || []).forEach((w) => {
      const c = document.createElement("div");
      c.className = "ws-card created";
      c.innerHTML = `<div class="ws-art" style="background:${w.art}"></div>
        <div class="ws-body"><h3>${esc(w.name)} <span class="mc-tag demo">CONCEPT</span></h3>
        <div class="ws-meta">${esc(w.meta)}</div>
        <div class="ws-foot"><span class="pill-sm">LOCAL</span><button class="btn small primary">Select</button></div></div>`;
      c.querySelector(".btn").onclick = (e) => { e.stopPropagation(); S.workspace = w.name; persist(); toast("Workspace set", w.name + " (local concept) is now the active world.", "good"); el.hudWorkspace.textContent = w.name; };
      c.onclick = () => openWsDetail({ name: w.name, meta: w.meta, status: w.status, up: "", source: w.source });
      el.wsGrid.appendChild(c);
    });
    const n = document.createElement("div");
    n.className = "ws-card ws-new";
    n.innerHTML = '<span class="plus">＋</span><span>New Workspace</span><span class="muted" style="font-size:11px">Scaffold a fresh Unreal world</span>';
    n.onclick = openWsCreate;
    el.wsGrid.appendChild(n);
    renderCast();
  }

  function renderMission() {
    renderMissionList();
    const liveTasks = backend.online ? live.tasks.filter((t) => t && t.id) : [];
    const wbTasks = (live.wb && live.wb.tasks) || [];
    const lt = liveTasks.find((t) => t.id === S._selLive) || wbTasks.find((t) => t.id === S._selLive);
    if (lt) { renderLiveDetail(lt); return; }
    const um = live.missions.find((m) => m.id === S._selLive);
    if (um) { startMissionPolling(um.id); return; }
    const sel = S.missions.find((m) => m.id === S._selMission) || S.missions.find((m) => m.id === "m1");
    renderMissionDetail(sel);
  }

  function renderMissionList() {
    el.mcList.innerHTML = "";
    const laneH = (t) => { const h = document.createElement("div"); h.className = "mc-lane-h"; h.textContent = t; return h; };
    const liveTasks = backend.online ? live.tasks.filter((t) => t && t.id) : [];
    const wbTasks = ((live.wb && live.wb.tasks) || []).map((t) => ({ ...t, _wb: true }));
    const umTasks = live.missions.map((m) => ({ id: m.id, title: String(m.prompt || "unreal mission").slice(0, 48), routing: "unreal", status: m.status || "accepted", _um: true }));
    const allLive = [...liveTasks, ...wbTasks, ...umTasks];
    if (allLive.length) {
      el.mcList.appendChild(laneH("Live engine lane"));
      allLive.forEach((t) => {
        const it = document.createElement("div");
        it.className = "mc-item live" + (S._selLive === t.id ? " sel" : "");
        const pct = t.status === "passed" || t.verdict === "PASS" ? 100 : t.status === "running" ? 45 : 12;
        it.innerHTML = `<div class="mc-t"><h3>${esc(t.title)}</h3><span class="mc-tag live">LIVE</span></div>
          <div class="mc-d">${esc(t._um ? "unreal mission" : t._wb ? "workboard" : t.routing || "engine")} · ${esc(t.status || "—")}${t.verdict ? " · " + esc(t.verdict) : ""}${t.priority != null ? " · p" + t.priority : ""}</div>
          <div class="mc-bar"><i style="width:${pct}%"></i></div>`;
        it.onclick = () => { S._selLive = t.id; S._selMission = null; renderMissionList(); renderLiveDetail(t); };
        el.mcList.appendChild(it);
      });
    }
    el.mcList.appendChild(laneH("Demo lane · simulation"));
    S.missions.forEach((m) => {
      const it = document.createElement("div");
      it.className = "mc-item demo" + (S._selMission === m.id && !S._selLive ? " sel" : "");
      it.innerHTML = `<div class="mc-t"><h3>${esc(m.title)}</h3><span class="mc-tag demo">DEMO</span></div>
        <div class="mc-d">${esc(m.ws)} · crew ${m.crew.length} · ${m.verdict ? "verdict " + m.verdict : "stage " + m.stages[Math.max(0, m.cur - 1)]}</div>
        <div class="mc-bar"><i style="width:${Math.round(m.progress * 100)}%"></i></div>`;
      it.onclick = () => { S._selLive = null; S._selMission = m.id; renderMissionList(); renderMissionDetail(m); };
      el.mcList.appendChild(it);
    });
  }

  async function renderLiveDetail(t) {
    el.mcDetail.innerHTML = "";
    const h = document.createElement("div");
    h.className = "mc-head";
    h.innerHTML = `<div><h2>${esc(t.title)}</h2><div class="ws-meta">LIVE · ${esc(t.routing || "engine")} task ${esc(t.id)}${t.priority != null ? " · priority " + t.priority : ""}</div></div>
      <span class="pill-sm">${esc(t.status || "—")}</span>`;
    el.mcDetail.appendChild(h);
    const stage = CT_STAGE[t.status] || { label: String(t.status || "—").toUpperCase(), cls: "planned" };
    const chip = document.createElement("div");
    chip.className = "mc-live-chip " + stage.cls;
    chip.innerHTML = `<i class="dot-sm ${stage.cls === "running" || stage.cls === "validating" ? "busy" : stage.cls === "complete" ? "ready" : stage.cls === "planned" ? "ready" : "bad"}"></i> ${stage.label}`;
    el.mcDetail.appendChild(chip);
    if (t.verdict) {
      const v = document.createElement("div");
      v.className = "mc-verdict " + String(t.verdict).toLowerCase();
      v.textContent = "VERDICT " + t.verdict;
      el.mcDetail.appendChild(v);
    }
    if (t.prompt) { const p = document.createElement("p"); p.className = "mc-prompt"; p.textContent = t.prompt; el.mcDetail.appendChild(p); }
    if (t.steps && t.steps.length) {
      const st = document.createElement("div"); st.className = "mc-steps";
      t.steps.forEach((s) => {
        const d = document.createElement("div"); d.className = "mc-step";
        d.innerHTML = `<span class="st-ic">✓</span><span>${esc(s.op || "")}${s.path ? " " + esc(s.path) : ""}</span>`;
        st.appendChild(d);
      });
      el.mcDetail.appendChild(st);
    }
    const ev = document.createElement("div"); ev.className = "mc-evidence";
    if (t.status === "passed" || t.verdict === "PASS") {
      ev.innerHTML = `<b>Evidence</b>${t.result && t.result.commit ? " — commit <span class=\"mono\">" + esc(String(t.result.commit).slice(0, 12)) + "</span>" : ""}${t.result && t.result.branch ? " · branch " + esc(t.result.branch) : ""}`;
    } else {
      ev.innerHTML = "<b>No completed evidence on file yet.</b>";
    }
    el.mcDetail.appendChild(ev);
    try {
      const e = await api("/api/code/tasks/" + t.id + "/evidence");
      const ef = e && e.evidence && e.evidence.evidence_files;
      if (ef && ef.length) {
        const l = document.createElement("div");
        l.className = "mc-evidence";
        l.innerHTML = "<b>Evidence files</b><ul>" + ef.map((f) => `<li>${esc(String(f).split(/[\\/]/).pop())}</li>`).join("") + "</ul>";
        el.mcDetail.appendChild(l);
      }
    } catch (_) {}
    const ctl = document.createElement("div"); ctl.className = "mc-ctl";
    if (["queued", "running"].includes(t.status)) {
      const c = document.createElement("button"); c.className = "btn small ghost"; c.textContent = "Cancel task";
      c.onclick = async () => { try { await api("/api/code/tasks/" + t.id + "/cancel"); toast("Cancelled", t.id + " cancelled by request.", "info"); pollLive(); } catch (e) { toast("Cancel failed", String(e && e.message || e), "bad"); } };
      ctl.appendChild(c);
    }
    if (["failed", "blocked", "cancelled"].includes(t.status)) {
      const r = document.createElement("button"); r.className = "btn small"; r.textContent = "Retry task";
      r.onclick = async () => { try { await api("/api/code/tasks/" + t.id + "/retry"); toast("Retrying", t.id + " re-queued through the code worker.", "info"); pollLive(); } catch (e) { toast("Retry failed", String(e && e.message || e), "bad"); } };
      ctl.appendChild(r);
    }
    if (ctl.children.length) el.mcDetail.appendChild(ctl);
    const note = document.createElement("p");
    note.className = "muted mc-note";
    note.textContent = "Real data from the live task store — rendered verbatim, no frontend scoring.";
    el.mcDetail.appendChild(note);
  }

  /* ---------------- mission inspector: unreal-coder lane ---------------- */
  const CT_STAGE = { queued: { label: "QUEUED", cls: "planned" }, running: { label: "RUNNING", cls: "running" }, passed: { label: "COMPLETE", cls: "complete" }, failed: { label: "FAILED", cls: "failed" }, blocked: { label: "BLOCKED", cls: "blocked" }, cancelled: { label: "CANCELLED", cls: "blocked" } };
  const MIS_STAGE = {
    interpreting: { label: "QUEUED", cls: "planned" }, planning: { label: "PLANNING", cls: "planned" },
    executing: { label: "RUNNING", cls: "running" }, validating: { label: "VALIDATING", cls: "validating" },
    repairing: { label: "FIXING", cls: "validating" }, complete: { label: "COMPLETE", cls: "complete" },
    failed: { label: "FAILED", cls: "failed" }, blocked: { label: "BLOCKED", cls: "blocked" },
  };
  let missionPollTimer = null;
  function stopMissionPolling() { if (missionPollTimer) { clearTimeout(missionPollTimer); missionPollTimer = null; } }
  function startMissionPolling(id) {
    stopMissionPolling();
    const tick = async () => {
      const m = live.missions.find((x) => x.id === id);
      if (!m) return stopMissionPolling();
      try {
        const r = await api("/api/unreal-coder/mission/" + encodeURIComponent(id));
        m.status = r.status; m.verdict = r.verdict;
        if (route() === "mission" && S._selLive === id) renderLiveDetailMission(r);
        const done = ["complete", "failed", "blocked", "cancelled"].includes(r.status);
        if (done) {
          stopMissionPolling();
          renderSysStrip();
          toast("Mission " + r.status, (r.verdict || "—") + (r.why ? " · " + String(r.why).slice(0, 140) : ""), r.status === "complete" ? "good" : "bad");
          SFX.success();
        } else {
          missionPollTimer = setTimeout(tick, 3000);
        }
      } catch (_) { missionPollTimer = setTimeout(tick, 5000); }
    };
    tick();
  }

  async function renderLiveDetailMission(r) {
    el.mcDetail.innerHTML = "";
    const h = document.createElement("div");
    h.className = "mc-head";
    h.innerHTML = `<div><h2>${esc(r.mission_id)}</h2><div class="ws-meta">LIVE · unreal mission · ${esc((r.interpretation && r.interpretation.primary_domain) || "general")}</div></div><span class="mc-tag live">LIVE</span>`;
    el.mcDetail.appendChild(h);
    const stage = MIS_STAGE[r.status] || { label: String(r.status || "—").toUpperCase(), cls: "planned" };
    const chip = document.createElement("div");
    chip.className = "mc-live-chip " + stage.cls;
    chip.innerHTML = `<i class="dot-sm ${stage.cls === "running" || stage.cls === "validating" ? "busy" : stage.cls === "complete" ? "ready" : stage.cls === "planned" ? "ready" : "bad"}"></i> ${stage.label}`;
    el.mcDetail.appendChild(chip);
    if (r.verdict) {
      const v = document.createElement("div");
      v.className = "mc-verdict chip " + String(r.verdict).toLowerCase();
      v.textContent = "VERDICT " + r.verdict;
      el.mcDetail.appendChild(v);
    }
    if (r.why) { const p = document.createElement("p"); p.className = "mc-prompt"; p.textContent = r.why; el.mcDetail.appendChild(p); }
    const cw = r.completed_work || {};
    const total = cw.steps_total || 0, doneN = cw.steps_completed || 0;
    if (total) {
      const bar = document.createElement("div");
      bar.className = "mc-bar"; bar.style.marginTop = "14px";
      bar.innerHTML = `<i style="width:${Math.round(100 * doneN / total)}%"></i>`;
      el.mcDetail.appendChild(bar);
      const t = document.createElement("p"); t.className = "muted"; t.style.fontSize = "11px"; t.style.margin = "6px 0 0";
      t.textContent = doneN + " / " + total + " steps completed";
      el.mcDetail.appendChild(t);
    }
    const phases = (r.plan && r.plan.phases) || [];
    if (phases.length) {
      const ph = document.createElement("div"); ph.className = "mc-phases";
      ph.innerHTML = "<b>Plan phases</b>";
      phases.forEach((p) => {
        const d = document.createElement("div"); d.className = "mc-phase";
        d.innerHTML = `<span class="ph-name">${esc(p.phase || "")}</span><span class="ph-obj">${esc(p.objective || p.stop_condition || "")}</span>`;
        ph.appendChild(d);
      });
      el.mcDetail.appendChild(ph);
    }
    const ev = r.evidence || [];
    if (ev.length) {
      const l = document.createElement("div");
      l.className = "mc-evidence";
      l.innerHTML = "<b>Evidence</b><ul class=\"mc-evlist\">" + ev.map((f) => `<li>${esc(String(f))}</li>`).join("") + "</ul>";
      el.mcDetail.appendChild(l);
    }
    if ((r.warnings || []).length) {
      const l = document.createElement("div"); l.className = "mc-evidence";
      l.innerHTML = "<b>Warnings</b><ul class=\"mc-warn\">" + r.warnings.map((w) => `<li>${esc(String(w))}</li>`).join("") + "</ul>";
      el.mcDetail.appendChild(l);
    }
    if ((r.remaining_issues || []).length) {
      const l = document.createElement("div"); l.className = "mc-evidence";
      l.innerHTML = "<b>Remaining issues</b><ul class=\"mc-issue\">" + r.remaining_issues.map((w) => `<li>${esc(String(w))}</li>`).join("") + "</ul>";
      el.mcDetail.appendChild(l);
    }
    const arts = r.artifacts || [];
    if (arts.length) {
      const a = document.createElement("div"); a.className = "mc-evidence";
      a.innerHTML = "<b>Artifacts</b>" + arts.map((x) => `<div class="mc-artifact"><span>${esc(x.resource_path || x.path || "")}</span></div>`).join("");
      el.mcDetail.appendChild(a);
    }
    const ctl = document.createElement("div"); ctl.className = "mc-ctl";
    if (["interpreting", "planning", "executing", "validating", "repairing"].includes(r.status)) {
      const c = document.createElement("button"); c.className = "btn small ghost"; c.textContent = "Cancel mission";
      c.onclick = async () => { try { await api("/api/unreal-coder/mission/" + encodeURIComponent(r.mission_id) + "/cancel"); toast("Cancelling", r.mission_id + " — backend finalizes as CANCELLED, never SUCCESS.", "info"); startMissionPolling(r.mission_id); } catch (e) { toast("Cancel failed", String(e && e.message || e), "bad"); } };
      ctl.appendChild(c);
    }
    if (["complete", "failed", "blocked", "cancelled"].includes(r.status)) {
      const v = document.createElement("button"); v.className = "btn small"; v.textContent = "Run validation";
      v.onclick = async () => { try { await api("/api/unreal-coder/mission/" + encodeURIComponent(r.mission_id) + "/validate"); toast("Validation requested", "Backend re-runs the real technical + visual gate.", "info"); startMissionPolling(r.mission_id); } catch (e) { toast("Validate failed", String(e && e.message || e), "bad"); } };
      ctl.appendChild(v);
      if (r.resumable) {
        const z = document.createElement("button"); z.className = "btn small ghost"; z.textContent = "Resume mission";
        z.onclick = async () => { try { await api("/api/unreal-coder/mission/" + encodeURIComponent(r.mission_id) + "/resume"); toast("Resumed", "Retry through the real engine — completed steps are skipped from the checkpoint.", "info"); startMissionPolling(r.mission_id); } catch (e) { toast("Resume failed", String(e && e.message || e), "bad"); } };
        ctl.appendChild(z);
      }
    }
    if (ctl.children.length) el.mcDetail.appendChild(ctl);
    if (r.mission_log) { const p = document.createElement("p"); p.className = "muted mc-note"; p.textContent = "mission log: " + r.mission_log; el.mcDetail.appendChild(p); }
    const note = document.createElement("p");
    note.className = "muted mc-note";
    note.textContent = "Rendered verbatim from the backend checkpoint (" + r.status + ") — no frontend scoring, no fabricated completion.";
    el.mcDetail.appendChild(note);
  }

  /* ---------------- dispatch (canonical execution paths) ---------------- */
  async function dispatchCodeTask() {
    const prompt = el.dlPrompt.value.trim() || "add a small phase-2 proof module with a greeting function and its test";
    if (!backend.online) return toast("Engine offline", "No engine gateway — dispatch unavailable.", "bad");
    const slug = "phase2_" + Date.now().toString(36).slice(-5);
    const mod = "app/code_task_" + slug + ".py";
    const test = "tests/test_code_task_" + slug + ".py";
    try {
      const r = await api("/api/code/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: "Phase-2 proof: " + slug, prompt: prompt, routing: "code",
          steps: [
            { op: "create_file", path: mod, content: "def greeting(name=\"Aivido\"):\n    return f\"hello {name} from the phase-2 crew\"\n" },
            { op: "create_file", path: test, content: "from app.code_task_" + slug + " import greeting\n\ndef test_greeting():\n    assert \"phase-2\" in greeting()\n" },
          ],
          tests: ["pytest " + test, "py_compile " + mod],
          acceptance: ["exists " + mod, "exists " + test],
          scope: [mod, test],
        }),
      });
      const t = r.task;
      questTick("dispatch"); ledgerAdd("dispatch", "Code task " + t.id + " (isolated worktree)", 0);
      toast("Code task queued", t.id + " — runs in an isolated worktree branch; never touches the live checkout.", "good");
      el.mcDispatch.classList.remove("pulse-ok"); void el.mcDispatch.offsetWidth; el.mcDispatch.classList.add("pulse-ok");
      S._selLive = t.id; S._selMission = null;
      pollLive().then(() => { renderMissionList(); renderMission(); });
      SFX.confirm();
    } catch (e) { toast("Dispatch failed", String(e && e.message || e), "bad"); }
  }

  async function dispatchUnreal() {
    const prompt = el.dlPrompt.value.trim();
    if (!prompt) return toast("Prompt required", "Describe the mission for the crew.", "bad");
    if (!backend.online) return toast("Engine offline", "No engine gateway — dispatch unavailable.", "bad");
    try {
      const r = await api("/api/unreal-coder/async", {
        method: "POST",
        body: JSON.stringify({ prompt: prompt, quality: "fast", project: (live.ws && live.ws.project) || undefined }),
      });
      const m = { id: r.mission_id, prompt: prompt, status: r.status || "accepted" };
      live.missions = [m, ...live.missions].slice(0, 12);
      questTick("dispatch"); ledgerAdd("dispatch", "Unreal mission " + m.id, 0);
      toast("Mission accepted", m.id + " — real lifecycle is polled from the backend checkpoint.", "good");
      el.mcDispatch.classList.remove("pulse-ok"); void el.mcDispatch.offsetWidth; el.mcDispatch.classList.add("pulse-ok");
      S._selLive = m.id; S._selMission = null;
      renderMissionList(); renderMission();
      SFX.confirm();
    } catch (e) { toast("Dispatch failed", String(e && e.message || e), "bad"); }
  }

  async function planPreview() {
    const prompt = el.dlPrompt.value.trim();
    if (!prompt) return toast("Prompt required", "Type a mission description to preview its plan.", "bad");
    if (!backend.online) return toast("Engine offline", "No engine gateway to plan against.", "bad");
    toast("Planning (dry-run)", "The real planner builds the plan — nothing executes.", "info");
    try {
      const r = await api("/api/unreal-coder", { method: "POST", body: JSON.stringify({ prompt: prompt, quality: "fast", dry_run: true }) });
      showPlanModal(r);
    } catch (e) { toast("Plan failed", String(e && e.message || e), "bad"); }
  }

  function showPlanModal(r) {
    el.modalRoot.innerHTML = "";
    const d = document.createElement("div"); d.className = "choice-modal dossier";
    const phases = ((r.plan || {}).phases || []).map((p) => `<div class="mc-phase"><span class="ph-name">${esc(p.phase || "")}</span><span class="ph-obj">${esc(p.objective || p.stop_condition || "")}</span></div>`).join("");
    const caps = ((r.plan || {}).selected_capabilities || []).join(" · ");
    const vg = (r.plan || {}).visual_gate;
    d.innerHTML = `<div class="dos-head"><div class="dos-ic">☩</div><div><p class="choice-eyebrow">PLAN PREVIEW · DRY RUN</p><h2>Real planner output</h2></div></div>
      <p class="dos-state">Status: <b>${esc(r.status || "planning")}</b> · nothing executed</p>
      <div class="dos-slot"><b>Capabilities:</b> ${esc(caps || "—")}<br>${vg ? "<b>Visual gate:</b> " + esc(JSON.stringify(vg)) : "<b>Visual gate:</b> advisory"}</div>
      <div class="mc-phases"><b>Phases</b>${phases || "<div class='mc-phase'><span class='ph-obj'>no phases reported</span></div>"}</div>
      <p class="muted" style="font-size:11px">Plan summary comes straight from the backend pipeline. Full step listing lives in the mission checkpoint (mission log).</p>
      <div class="row" style="justify-content:flex-end"><button class="btn small ghost" data-c-close>Close</button></div>`;
    el.modalRoot.appendChild(d);
    openModal();
    d.querySelector("[data-c-close]").onclick = () => { closeModal(); SFX.click(); };
    SFX.open();
  }

  /* ---------------- cast & assets (real integration contract) ---------------- */
  function renderCast() {
    const grid = el.castGrid; if (!grid) return;
    grid.innerHTML = "";
    const charTools = (live.tools || []).filter((t) => /character|meta|animation/i.test(String(t)));
    const contract = charTools.length ? charTools.map(esc).join(" · ") : "registry unreachable — retry with the engine linked";
    WORKERS.forEach((w) => {
      const d = document.createElement("div"); d.className = "cast-slot";
      d.innerHTML = `<div class="cs-head"><div class="cs-ic" style="color:${w.color}">${TOOLS[w.id] || w.ic}</div><div><h3>${esc(w.name)}</h3><div class="cs-role">${esc(w.role)}</div></div></div>
        <div class="cs-slot">MetaHuman slot · ${w.id}.${esc(w.role.replace(/\s+/g, "").toLowerCase())}</div>
        <span class="cs-state missing">ASSET MISSING · CSS FALLBACK</span>
        <div class="cs-tools"><b>Import contract (real tools):</b> ${contract}</div>`;
      grid.appendChild(d);
    });
  }

  function openDossier(w) {
    const st = stClass(w.state);
    const charTools = (live.tools || []).filter((t) => /character|meta|animation/i.test(String(t))).join(" · ") || "registry unreachable";
    el.modalRoot.innerHTML = "";
    const d = document.createElement("div"); d.className = "choice-modal dossier";
    d.innerHTML = `<div class="dos-head"><div class="dos-ic" style="color:${w.color}">${TOOLS[w.id] || w.ic}</div><div>
        <p class="choice-eyebrow">CREW DOSSIER</p><h2>${esc(w.name)}</h2><div class="cs-role">${esc(w.role)} specialist</div></div></div>
      <p class="dos-state">Current state: <b>${st}</b>${w.task ? " · " + esc(w.task) : ""}</p>
      <p class="muted">${esc(FOREMAN_LINES.worker(w.name, st))}</p>
      <div class="dos-slot"><b>MetaHuman slot:</b> ${w.id}.${esc(w.role.replace(/\s+/g, "").toLowerCase())}<br>
        <b>Status:</b> ASSET MISSING — CSS figure fallback active<br>
        <b>Import contract:</b> ${esc(charTools)}<br>
        <b>Phase-2 path:</b> install MetaHuman preset → wardrobe pass → live portrait capture</div>
      <div class="row" style="justify-content:flex-end"><button class="btn small ghost" data-c-close>Close</button><button class="btn small primary" data-c-check>Check in with ${esc(w.name)}</button></div>`;
    el.modalRoot.appendChild(d);
    openModal();
    d.querySelector("[data-c-close]").onclick = () => { closeModal(); SFX.click(); };
    d.querySelector("[data-c-check]").onclick = () => { workerCheckIn(w); closeModal(); SFX.confirm(); };
    SFX.open();
  }

  /* ---------------- truthful system strip ---------------- */
  function renderSysStrip() {
    const chip = (id, txt, cls) => { const e = $(id); if (e) { e.innerHTML = txt; e.className = "ss-chip " + cls; } };
    chip("ssEngine", `<i class="dot-sm ${backend.online ? (backend.busy ? "busy" : "ready") : "bad"}"></i> engine ${backend.online ? (backend.busy ? "busy" : "linked") : "offline"}`, backend.online ? (backend.busy ? "warn" : "ok") : "bad");
    chip("ssBridge", "bridge " + (live.session ? "ready" : backend.online ? "no session" : "unavailable"), live.session ? "ok" : (backend.online ? "warn" : "bad"));
    chip("ssMap", "map " + (live.session && live.session.active_map ? esc(String(live.session.active_map).split(".").pop()) : "—"), live.session ? "ok" : "warn");
    const pAge = live.proofAge;
    chip("ssProof", "proof " + (pAge == null ? "—" : pAge < 900 ? "fresh" : "STALE"), pAge == null ? "" : pAge < 900 ? "ok" : "warn");
    chip("ssExec", backend.busy ? "execution active" : "no execution", backend.busy ? "warn" : "");
  }

  /* ---------------- durable local stores (quests / finance) ---------------- */
  const QLS = "aivido_quests_v1", LLS = "aivido_ledger_v1";
  function questStore() { let q = { version: 1, source: "LOCAL", updated_at: null, ticks: {} }; try { q = Object.assign(q, JSON.parse(localStorage.getItem(QLS) || "{}")); } catch (_) {} return q; }
  function questTick(key) {
    const q = questStore(); q.ticks[key] = (q.ticks[key] || 0) + 1; q.updated_at = new Date().toISOString();
    localStorage.setItem(QLS, JSON.stringify(q)); return q.ticks[key];
  }
  function ledgerStore() { let l = { version: 1, rows: [] }; try { l = Object.assign(l, JSON.parse(localStorage.getItem(LLS) || "{}")); } catch (_) {} return l; }
  function ledgerAdd(kind, label, delta) {
    const l = ledgerStore();
    l.rows = [{ kind: kind, label: label, delta: delta, source: "LOCAL", at: new Date().toISOString() }, ...l.rows].slice(0, 40);
    localStorage.setItem(LLS, JSON.stringify(l)); return l.rows;
  }

  /* ---------------- clickup detection (truthful BLOCKED) ---------------- */
  async function detectClickUp() {
    if (!backend.online) return;
    try {
      const r = await api("/api/action", { method: "POST", body: JSON.stringify({ action: "tools_list", payload: {}, context: {} }) });
      const tools = (r.data && r.data.tools) || [];
      live.tools = tools;
      const has = tools.some((t) => String(t).toLowerCase().includes("clickup"));
      const cu = document.getElementById("cuStatus"), cd = document.getElementById("cuDetail");
      if (cu) { cu.textContent = has ? "AVAILABLE" : "BLOCKED"; cu.className = "card-sub " + (has ? "ok" : "bad"); }
      if (cd) cd.textContent = has
        ? "ClickUp tool detected on the gateway — sync can be enabled."
        : "No ClickUp tool or credentials found (registry: " + tools.length + " tools, none ClickUp). Sync stays BLOCKED — nothing is faked.";
    } catch (_) {}
  }

  function renderMissionDetail(m) {
    el.mcDetail.innerHTML = "";
    const h = document.createElement("div");
    h.className = "mc-head";
    h.innerHTML = `<div><h2>${esc(m.title)}</h2><div class="ws-meta">${esc(m.ws)} · ${m.verdict ? "verdict " + m.verdict : m.status}</div></div>
      <span class="pill-sm">${Math.round(m.progress * 100)}%</span>`;
    el.mcDetail.appendChild(h);
    const stages = document.createElement("div");
    stages.className = "mc-stages";
    m.stages.forEach((s, i) => {
      const done = i < m.cur, run = i === m.cur - 1 && m.status === "ACTIVE";
      const d = document.createElement("div");
      d.className = "mc-stage" + (done ? " done" : "") + (run ? " running" : "");
      d.innerHTML = `<span class="st-ic">${done ? "✓" : run ? "◉" : "○"}</span><span class="st-name">${esc(s)}</span>${done ? "" : run ? '<span class="muted" style="font-size:11px">in progress</span>' : ""}`;
      stages.appendChild(d);
    });
    el.mcDetail.appendChild(stages);
    const crew = document.createElement("div");
    crew.className = "mc-crew";
    m.crew.forEach((c) => crew.appendChild(Object.assign(document.createElement("span"), { className: "mc-chip", textContent: c })));
    el.mcDetail.appendChild(crew);
    if (m.evidence.length) {
      const ev = document.createElement("div");
      ev.className = "mc-evidence";
      ev.innerHTML = "evidence: " + m.evidence.map(esc).join(", ");
      el.mcDetail.appendChild(ev);
    }
    if (m.status !== "COMPLETE") {
      const btn = document.createElement("button");
      btn.className = "btn primary"; btn.style.marginTop = "16px";
      btn.textContent = m.status === "QUEUED" ? "Dispatch now" : "Advance mission";
      btn.onclick = () => { startDemoMission(m.id); renderMissionList(); };
      el.mcDetail.appendChild(btn);
    }
  }

  function renderRoomScreen() {
    renderRoom();
    renderHoloData();
    const eng = live.session && live.session.project_name ? " · " + live.session.project_name : "";
    el.roomSub.textContent = backend.mode === "LIVE" ? "prestige western workshop · live engine linked" + eng : "prestige western workshop · simulation mode";
    el.hudWorkspace.textContent = S.workspace;
    if (!ambientTimer) startAmbient();
  }

  function renderProofScreen() {
    renderGallery();
    if (S.gallery[0]) showProofEntry(S.gallery[0], S._pvIdx != null && S._pvIdx < S.gallery.length ? S._pvIdx : 0);
    el.pvAuto.checked = S.autoProof;
    el.pvCapture.onclick = captureProof;
    if (backend.online) refreshBackendProof(true);
  }

  function renderQuests() {
    const qs = questStore();
    el.questActive.innerHTML = "";
    el.questDone.innerHTML = "";
    S.quests.forEach((q) => {
      const steps = q.steps.map((s) => ({ ...s }));
      if (q.id === "q2") {
        if ((qs.ticks.capture || 0) >= 1) steps[0].done = true;
        if ((qs.ticks.dispatch || 0) >= 1) steps[1].done = true;
      }
      if (q.id === "q1") {
        // truthful: only ticks when a LIVE proof with score >= 8.5 actually exists
        const livePass = S.gallery.some((g) => g.source === "LIVE" && g.score !== "—" && Number(g.score) >= 8.5);
        if (livePass) steps[3].done = true;
      }
      const doneSteps = steps.filter((s) => s.done).length;
      const pct = Math.round(100 * doneSteps / steps.length);
      const c = document.createElement("div");
      c.className = "quest-card" + (!q.active ? " done" : "");
      c.innerHTML = `<div class="q-top"><h3>${esc(q.title)}<span class="q-src">LOCAL</span></h3><span class="q-reward">◈ ${esc(q.reward)}</span></div>
        <p class="q-desc">${pct}% complete · ${doneSteps}/${steps.length} steps · durable local store</p>
        <ul class="q-steps">${steps.map((s) => `<li class="${s.done ? "done" : ""}">${esc(s.t)}</li>`).join("")}</ul>
        <div class="q-bar"><i style="width:${pct}%"></i></div>`;
      (q.active ? el.questActive : el.questDone).appendChild(c);
    });
  }

  function renderFinance() {
    el.finBalance.innerHTML = `<div><div class="fb-big">◈ ${S.balance}</div><div class="fb-sub">credits · session-local · no billing wired</div></div>
      <div><div class="fb-big" style="font-size:22px">∞</div><div class="fb-sub">local free · always on, always yours</div></div>`;
    const finNote = document.createElement("p");
    finNote.className = "muted"; finNote.style.cssText = "font-size:11px;margin:10px 0 0;";
    finNote.textContent = "Billing backend: FUTURE — not wired. Credits are session-local; the ledger below records real actions only.";
    el.finBalance.insertAdjacentElement("afterend", finNote);
    const PACKS = [
      { name: "Local Free", amt: "∞", price: "$0", tag: "ALWAYS", cls: "free", d: "Unlimited local engine time on your own machine. No cloud needed for solo work.", buy: null },
      { name: "Starter Spark", amt: "50", price: "$9", tag: "", cls: "", d: "For one heavy showcase run with the full crew.", buy: 50 },
      { name: "Workshop Fire", amt: "300", price: "$49", tag: "BEST VALUE", cls: "best", d: "A full production week of cloud muscle.", buy: 300 },
      { name: "Foundry", amt: "1000", price: "$129", tag: "", cls: "", d: "For studios running parallel crews.", buy: 1000 },
    ];
    el.finPacks.innerHTML = "";
    PACKS.forEach((p) => {
      const c = document.createElement("div");
      c.className = "fin-pack " + p.cls;
      c.innerHTML = (p.tag ? `<span class="fp-tag">${p.tag}</span>` : "") + `<h3>${esc(p.name)}</h3><div class="fp-amt">◈ ${p.amt}</div><div class="fp-d">${esc(p.d)}</div>`;
      const b = document.createElement("button");
      b.className = "btn " + (p.buy ? "primary" : "ghost");
      b.textContent = p.buy ? "Buy · " + p.price : "Active";
      b.onclick = () => { if (!p.buy) return; S.balance += p.buy; persist(); toast("Purchase complete", p.name + " · +" + p.buy + " credits", "good"); renderFinance(); };
      c.appendChild(b);
      el.finPacks.appendChild(c);
    });
    el.finChart.innerHTML = "";
    const days = ["M", "T", "W", "T", "F", "S", "S"];
    S.spent.forEach((v, i) => {
      const b = document.createElement("div");
      b.className = "fc-bar"; b.style.height = Math.max(12, Math.round(v * 13)) + "px";
      b.innerHTML = `<span>${days[i]}</span>`;
      el.finChart.appendChild(b);
    });
    const lrows = (ledgerStore().rows || []).slice(0, 8);
    const demoRows = [
      { label: "Graduation run — cloud compute", delta: -80 },
      { label: "Night Pass — cloud compute", delta: -25 },
    ];
    el.finLedger.innerHTML =
      `<span class="fin-src">LOCAL LEDGER · real actions this session</span>` +
      (lrows.length ? lrows.map((r) => `<div class="fl-row"><span>${esc(r.label)} <span class="fl-src">${esc(r.source || "LOCAL")}</span></span><b class="${r.delta > 0 ? "plus" : "minus"}">${r.delta > 0 ? "+" : ""}${r.delta}</b></div>`).join("") : `<div class="muted" style="font-size:11px">No real activity recorded yet this session.</div>`) +
      `<span class="fin-src" style="margin-top:10px">DEMO SEED · fiction</span>` +
      demoRows.map((r) => `<div class="fl-row"><span>${esc(r.label)} <span class="fl-src">DEMO</span></span><b class="minus">${r.delta}</b></div>`).join("");
  }

  function renderProfile() {
    el.profName.textContent = S.name;
    el.profAvatar.textContent = (S.name || "D")[0].toUpperCase();
    el.profXpFill.style.width = "71%";
    el.profXpTxt.textContent = "Level 7 · 640 / 900 XP";
    el.stMissions.textContent = S.missions.length + 3;
    el.stSuccess.textContent = "92%";
    el.stHours.textContent = "41";
    const SKILLS = [["Environment", 82], ["Lighting", 88], ["Cinematics", 76], ["Blueprint", 70], ["VFX", 66], ["Direction", 91]];
    el.profSkills.innerHTML = "";
    SKILLS.forEach(([n, v]) => {
      const r = document.createElement("div");
      r.className = "skill-row";
      r.innerHTML = `<span class="sk-name">${n}</span><div class="sk-bar"><i style="width:${v}%"></i></div><span class="sk-v">${v}</span>`;
      el.profSkills.appendChild(r);
    });
    const ACH = [
      ["🎖", "First Cube", "spawn + proof your first actor", "firstCube"],
      ["🌇", "Golden Hour", "score a shot ≥ 8.5", "goldenHour"],
      ["🌃", "Night Pass", "complete the night lighting quest", "nightPass"],
      ["☩", "Full Crew", "dispatch all seven specialists", "fullCrew"],
      ["🏁", "Clean Run", "finish a mission with zero faults", "cleanRun"],
      ["▣", "Vault Five", "hold five proofs in the vault", "vault5"],
    ];
    el.profAch.innerHTML = "";
    ACH.forEach(([ic, t, d, key]) => {
      const on = S.achievements[key];
      const a = document.createElement("div");
      a.className = "ach" + (on ? "" : " locked");
      a.innerHTML = `<div class="a-ic">${ic}</div><div class="a-t">${t}</div><div class="muted" style="font-size:9px">${d}</div>`;
      a.title = d;
      el.profAch.appendChild(a);
    });
  }

  function renderSettings() {
    el.setBase.value = S.base;
    el.setName.value = S.name;
    el.setAutoProof.checked = S.autoProof;
    el.setCinematic.checked = S.cinematic;
    el.setIdle.checked = S.idle;
    el.setSound.checked = S.sound;
    el.setVersion.textContent = "aivido-worker4-game-ui · game-grade UI final";
    renderLiveIntegrations();
  }

  /* ---------------- wire up ---------------- */
  function boot() {
    el.hudWorkspace.textContent = S.workspace;
    el.hudCredits.textContent = "◈ " + S.balance;
    el.hudAvatar.textContent = (S.name || "D")[0].toUpperCase();

    el.hudAvatar.addEventListener("click", () => show("profile"));
    document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => navWithCinematic(b.dataset.nav)));

    // sound
    SFX.set(S.sound);
    el.hudSnd.classList.toggle("off", !S.sound);
    el.hudSnd.addEventListener("click", () => {
      S.sound = !S.sound; SFX.set(S.sound); persist();
      el.hudSnd.classList.toggle("off", !S.sound);
      if (S.sound) SFX.confirm();
      toast("Sound " + (S.sound ? "on" : "off"), S.sound ? "Feedback rearmed." : "Booth muted — the crew keeps talkin' regardless.", "info");
    });
    el.setSound.addEventListener("change", () => { S.sound = el.setSound.checked; SFX.set(S.sound); persist(); el.hudSnd.classList.toggle("off", !S.sound); if (S.sound) SFX.confirm(); });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (["pvCapture", "pvApprove", "pvChange", "hudSnd"].includes(b.id)) return;
      if (b.closest(".choice-card")) return;
      SFX.click();
    });

    // dispatch lane (duplicate-click guard: one dispatch at a time)
    el.dlDispatch.addEventListener("click", async () => {
      if (_dispatchBusy) return toast("Dispatch in progress", "One dispatch at a time — the crew is already taking orders.", "info");
      const mode = document.querySelector('input[name="dlMode"]:checked')?.value || "code";
      if (mode === "unreal") {
        if (!window.confirm("Unreal missions run the live editor and can spawn or change actors. Preview the plan first and cancel if it looks wrong. Continue?")) return;
      }
      _dispatchBusy = true;
      el.dlDispatch.disabled = true;
      try {
        if (mode === "unreal") {
          await dispatchUnreal();
        } else {
          await dispatchCodeTask();
        }
      } finally {
        _dispatchBusy = false;
        el.dlDispatch.disabled = false;
      }
    });
    el.dlPlan.addEventListener("click", planPreview);
    document.querySelectorAll('input[name="dlMode"]').forEach((r) => r.addEventListener("change", () => {
      const unreal = r.value === "unreal" && r.checked;
      el.dlWarn.classList.toggle("hidden", !unreal);
    }));

    // proof vault controls
    el.pvPrev.addEventListener("click", () => proofStep(-1));
    el.pvNext.addEventListener("click", () => proofStep(1));
    el.pvFull.addEventListener("click", () => { el.pvStage.classList.toggle("full"); SFX.click(); });
    el.pvApprove.addEventListener("click", approveProof);
    el.pvChange.addEventListener("click", requestChange);

    // keyboard: Tab trapped inside modals, Escape closes modal/sheet, arrows walk the vault
    document.addEventListener("keydown", (e) => {
      trapFocus(e);
      if (e.key === "Escape") {
        if (!el.modalRoot.classList.contains("hidden")) { closeModal(); SFX.click(); return; }
        const m = $("moreSheet");
        if (m && !m.classList.contains("hidden")) { closeMore(); SFX.click(); return; }
      }
      if (route() === "proof" && S.gallery.length) {
        if (e.key === "ArrowLeft") { e.preventDefault(); proofStep(-1); }
        if (e.key === "ArrowRight") { e.preventDefault(); proofStep(1); }
      }
    });

    el.homeEnterRoom.addEventListener("click", () => navWithCinematic("room"));
    el.homeNewMission.addEventListener("click", () => { startDemoMission(); show("room"); });
    el.wsNew.addEventListener("click", openWsCreate);
    el.mcNew.addEventListener("click", () => { startDemoMission(); show("mission"); });
    el.roomDispatch.addEventListener("click", () => startDemoMission());
    el.roomReset.addEventListener("click", () => {
      W.forEach((w) => setState(w, "IDLE", null, null));
      foremanSay("Back to rest, crew. Good shift.", 4200);
      toast("Stations reset", "All workers returned to idle.", "info");
    });
    el.pvCapture.addEventListener("click", captureProof);
    el.pvAuto.addEventListener("change", () => { S.autoProof = el.pvAuto.checked; persist(); });
    el.setSave.addEventListener("click", () => {
      S.base = el.setBase.value.trim().replace(/\/+$/, "");
      S.name = el.setName.value.trim() || "Director";
      S.autoProof = el.setAutoProof.checked;
      S.cinematic = el.setCinematic.checked;
      S.idle = el.setIdle.checked;
      persist();
      el.hudAvatar.textContent = S.name[0].toUpperCase();
      el.hudWorkspace.textContent = S.workspace;
      el.setSaved.classList.remove("hidden");
      setTimeout(() => el.setSaved.classList.add("hidden"), 2000);
      toast("Settings saved", "Booth tuned. Engine untouched.", "good");
      pollHealth();
    });

    window.addEventListener("hashchange", () => show(route()));

    // mobile bottom-nav "More" sheet
    const mnMore = $("mnMore"), moreSheet = $("moreSheet");
    if (mnMore) mnMore.addEventListener("click", () => { moreSheet.classList.toggle("hidden"); SFX.open(); });
    if (moreSheet) {
      moreSheet.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", closeMore));
      const scrim = moreSheet.querySelector("[data-close-more]");
      if (scrim) scrim.addEventListener("click", closeMore);
    }

    // clock
    setInterval(() => { el.hudClock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }, 1000);

    // auto-proof refresh in vault (guarded by _proofReq stale protection)
    setInterval(() => { if (S.autoProof && route() === "proof") refreshBackendProof(false); }, 8000);

    // sting → app (skipped in test harness with ?fast=1)
    const startApp = () => {
      el.sting.style.display = "none";
      el.app.classList.remove("hidden");
      show(route());
      pollHealth();
      setInterval(pollHealth, 12000);
      setInterval(pollLive, 20000);
    };
    if (FAST) startApp(); else setTimeout(startApp, 3100);
  }

  document.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();
})();