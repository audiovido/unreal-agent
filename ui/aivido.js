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

  let S = Object.assign({}, JSON.parse(localStorage.getItem(LS) || "null") || JSON.parse(JSON.stringify(DEFAULT)));

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
    "holoData","pvPrev","pvNext","pvFull","pvIdx","pvBadge","pvApprove","pvChange","liEngine","liCode","liWb","liClickup"];
  REFS.forEach((r) => (el[r] = $(r)));

  /* ---------------- helpers ---------------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const stClass = (s) => ({ IDLE: "IDLE", ASSIGNED: "ASSIGNED", THINKING: "THINKING", WORKING: "WORKING", WAITING: "WAITING", ERROR: "ERROR", DONE: "DONE" }[s] || "IDLE");
  const workerById = (id) => W.find((w) => w.id === id);
  const persist = () => localStorage.setItem(LS, JSON.stringify(S));

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
    document.querySelectorAll(".rail-item").forEach((b) => b.classList.toggle("active", b.dataset.nav === nav));
    $(SCREENS[nav]).classList.add("on");
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
  let live = { session: null, ws: null, tasks: [], wb: null };

  async function api(path, opts = {}) {
    const r = await fetch(apiBase() + path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r;
  }

  async function pollHealth() {
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
  }

  /* ---------------- live engine data (read-only) ---------------- */
  async function pollLive() {
    if (!backend.online) return;
    try { const r = await api("/api/unreal-coder/session"); live.session = (r && r.session) || null; } catch (_) {}
    try { live.ws = await api("/api/workspace"); } catch (_) {}
    try { const r = await api("/api/code/tasks"); live.tasks = (r && r.tasks) || []; } catch (_) {}
    try { const r = await api("/api/workboard/state"); live.wb = (r && r.data) || null; } catch (_) {}
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
    toast("Capture started", "Framing the shot and pulling a fresh frame…", "info");
    const start = Date.now();
    let entry;
    try {
      const res = await api("/api/unreal/frame-and-proof", {
        method: "POST", body: JSON.stringify({ location: [0, 0, 200] }),
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
    }
    const ms = Date.now() - start;
    pushGallery(entry);
    showProofEntry(entry);
    foremanSay(FOREMAN_LINES.proof, 5200);
    toast("Proof minted", entry.source + " frame in " + (ms / 1000).toFixed(1) + "s · score " + entry.score, "good");
  }

  async function refreshBackendProof(force) {
    if (!backend.online) return;
    try {
      const st = await api("/api/proof/status");
      if (st && st.ok && st.path) {
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
    img.onload = () => { el.pvEmpty.hidden = true; img.hidden = false; };
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
      stn.onclick = () => workerCheckIn(w);
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
    el.modalRoot.classList.remove("hidden");
    foremanSay(FOREMAN_LINES.choice, 5000);
  }

  function resolveChoice(c) {
    el.modalRoot.classList.add("hidden");
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
      c.onclick = () => { S.workspace = w.name; persist(); el.hudWorkspace.textContent = w.name; toast("Workspace selected", w.name, "info"); };
      el.wsGrid.appendChild(c);
    });
    const n = document.createElement("div");
    n.className = "ws-card ws-new";
    n.innerHTML = '<span class="plus">＋</span><span>New Workspace</span><span class="muted" style="font-size:11px">Scaffold a fresh Unreal world</span>';
    n.onclick = () => toast("New Workspace", "Phase 1 shells this flow — the launcher lives in the engine lane.", "info");
    el.wsGrid.appendChild(n);
  }

  function renderMission() {
    renderMissionList();
    const liveTasks = backend.online ? live.tasks.filter((t) => t && t.id) : [];
    const wbTasks = (live.wb && live.wb.tasks) || [];
    const lt = liveTasks.find((t) => t.id === S._selLive) || wbTasks.find((t) => t.id === S._selLive);
    if (lt) { renderLiveDetail(lt); return; }
    const sel = S.missions.find((m) => m.id === S._selMission) || S.missions.find((m) => m.id === "m1");
    renderMissionDetail(sel);
  }

  function renderMissionList() {
    el.mcList.innerHTML = "";
    const laneH = (t) => { const h = document.createElement("div"); h.className = "mc-lane-h"; h.textContent = t; return h; };
    const liveTasks = backend.online ? live.tasks.filter((t) => t && t.id) : [];
    const wbTasks = ((live.wb && live.wb.tasks) || []).map((t) => ({ ...t, _wb: true }));
    const allLive = [...liveTasks, ...wbTasks];
    if (allLive.length) {
      el.mcList.appendChild(laneH("Live engine lane"));
      allLive.forEach((t) => {
        const it = document.createElement("div");
        it.className = "mc-item live" + (S._selLive === t.id ? " sel" : "");
        const pct = t.status === "passed" || t.verdict === "PASS" ? 100 : t.status === "running" ? 45 : 12;
        it.innerHTML = `<div class="mc-t"><h3>${esc(t.title)}</h3><span class="mc-tag live">LIVE</span></div>
          <div class="mc-d">${esc(t._wb ? "workboard" : t.routing || "engine")} · ${esc(t.status || "—")}${t.verdict ? " · " + esc(t.verdict) : ""}${t.priority != null ? " · p" + t.priority : ""}</div>
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
    const note = document.createElement("p");
    note.className = "muted mc-note";
    note.textContent = "Read-only view of the live task store. Live dispatch from this screen lands in Phase 2 — no fake success states here.";
    el.mcDetail.appendChild(note);
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
    el.questActive.innerHTML = "";
    el.questDone.innerHTML = "";
    S.quests.forEach((q) => {
      const doneSteps = q.steps.filter((s) => s.done).length;
      const pct = Math.round(100 * doneSteps / q.steps.length);
      const c = document.createElement("div");
      c.className = "quest-card" + (!q.active ? " done" : "");
      c.innerHTML = `<div class="q-top"><h3>${esc(q.title)}</h3><span class="q-reward">◈ ${esc(q.reward)}</span></div>
        <p class="q-desc">${pct}% complete · ${doneSteps}/${q.steps.length} steps</p>
        <ul class="q-steps">${q.steps.map((s) => `<li class="${s.done ? "done" : ""}">${esc(s.t)}</li>`).join("")}</ul>
        <div class="q-bar"><i style="width:${pct}%"></i></div>`;
      (q.active ? el.questActive : el.questDone).appendChild(c);
    });
  }

  function renderFinance() {
    el.finBalance.innerHTML = `<div><div class="fb-big">◈ ${S.balance}</div><div class="fb-sub">cloud credits · spendable on heavy missions</div></div>
      <div><div class="fb-big" style="font-size:22px">∞</div><div class="fb-sub">local free · always on, always yours</div></div>`;
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
    el.finLedger.innerHTML = `
      <div class="fl-row"><span>Frontier Garage Showcase — reward</span><b class="plus">+40</b></div>
      <div class="fl-row"><span>Night Pass — cloud compute</span><b class="minus">−25</b></div>
      <div class="fl-row"><span>Graduation run — cloud compute</span><b class="minus">−80</b></div>
      <div class="fl-row"><span>Daily quest — First Light</span><b class="plus">+20</b></div>`;
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
    el.setVersion.textContent = "aivido-uiux-phase1 · branch aivido-uiux-phase1";
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

    // proof vault controls
    el.pvPrev.addEventListener("click", () => proofStep(-1));
    el.pvNext.addEventListener("click", () => proofStep(1));
    el.pvFull.addEventListener("click", () => { el.pvStage.classList.toggle("full"); SFX.click(); });
    el.pvApprove.addEventListener("click", approveProof);
    el.pvChange.addEventListener("click", requestChange);

    // keyboard: Escape closes modals, arrows walk the vault
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !el.modalRoot.classList.contains("hidden")) { el.modalRoot.classList.add("hidden"); SFX.click(); }
      if (route() === "proof" && S.gallery.length) {
        if (e.key === "ArrowLeft") { e.preventDefault(); proofStep(-1); }
        if (e.key === "ArrowRight") { e.preventDefault(); proofStep(1); }
      }
    });

    el.homeEnterRoom.addEventListener("click", () => navWithCinematic("room"));
    el.homeNewMission.addEventListener("click", () => { startDemoMission(); show("room"); });
    el.wsNew.addEventListener("click", () => toast("New Workspace", "Scaffolding flow arrives with the launcher lane.", "info"));
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

    // clock
    setInterval(() => { el.hudClock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }, 1000);

    // auto-proof refresh in vault
    setInterval(() => { if (S.autoProof && route() === "proof") refreshBackendProof(false); }, 8000);

    // sting → app
    setTimeout(() => {
      el.sting.style.display = "none";
      el.app.classList.remove("hidden");
      show(route());
      pollHealth();
      setInterval(pollHealth, 12000);
      setInterval(pollLive, 20000);
    }, 3100);
  }

  document.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();
})();