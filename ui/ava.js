/* ============================================================
   Aivido — Ava · living AI companion
   Wired to the real backend on the same origin:
     GET  /api/status                       health + models + busy state
     POST /api/action  {action:"prompt"}    start a real agent task → task_id
     GET  /api/events/stream/{task_id}      SSE live progress
     POST /api/action  {action:"cancel"}    stop a running task
     POST /api/action  {action:"approval_approve|approval_reject"}
     GET  /api/proof/live                   AvaLive-scoped viewport proof (PiP)
   ============================================================ */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;
  // Embed mode (?embed=1): hide product chrome so other apps can iframe the
  // Chat as a self-contained widget. No frame-busting; CORS is open server-side.
  if (new URLSearchParams(location.search).get("embed") === "1") body.classList.add("embed");
  // Widget mode (?widget=1): embed variant that also hides the hero orb so the
  // chat fills a host panel. Hosts drive it via the postMessage contract in
  // ava_widget.js and receive ava:* events.
  if (new URLSearchParams(location.search).get("widget") === "1") body.classList.add("widget");
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Minimal safe inline markdown: escape first, then format. No raw HTML ever.
  var fmtMd = function (s) {
    s = esc(s);
    s = s.replace(/```([\s\S]*?)```/g, "<pre>$1</pre>");
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    return s;
  };

  var S = {
    online: false,
    busy: false,
    running: false,
    taskId: null,
    es: null,
    lastPrompt: "",
    planSteps: 0,
    doneSteps: 0,
    stageIdx: -1,
    approvals: 0,
    attached: [],
    listening: false,
    recognition: null,
    micAvailable: !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  };

  /* ============================================================
     API
     ============================================================ */
  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts);
  }

  /* ============================================================
     HOST <-> WIDGET CONTRACT
     Events are only posted when embedded (window.parent !== window).
     Contract helpers live in ava_widget.js (window.AVAWidget).
     ============================================================ */
  function widgetPost(type, payload) {
    if (!window.AVAWidget || window.parent === window) return;
    var msg = window.AVAWidget.event(type, payload);
    if (msg) window.parent.postMessage(msg, "*");
  }

  // Ava:height — the widget posts the px height it needs (content vs viewport,
  // whichever is larger) on resize and content change so hosts can size the
  // iframe. Wired at boot; ignored when not embedded.
  function widgetPostHeight() {
    if (window.parent === window) return;
    var h = Math.ceil(Math.max(document.documentElement.scrollHeight, window.innerHeight || 0));
    widgetPost("height", { height: h });
  }

  /* ============================================================
     PUBLIC UPDATE CHECK
     Compares the local ui-version.json against the canonical public
     GitHub branch. Shows an "Update available" chip only when the
     public build is NEWER (build_id compare) with a DIFFERENT content
     hash. Purely additive; every failure path stays silent. Never in
     embed/widget mode. Release tooling: scripts/ui_release.py.
     ============================================================ */
  var PUBLIC_VERSION_URL = "https://raw.githubusercontent.com/audiovido/unreal-agent/main/ui/ui-version.json";
  var PUBLIC_LATEST_URL = "https://github.com/audiovido/unreal-agent/releases/latest";

  function updateCheck() {
    if (window.parent !== window || !window.fetch) return;
    Promise.all([
      fetch("/static/ui-version.json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch(PUBLIC_VERSION_URL, { mode: "cors" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (pair) {
      var chip = $("updateChip");
      if (!chip) return;
      var local = pair[0], pub = pair[1];
      if (!local || !pub || !pub.content_hash || !local.content_hash) return;
      if (pub.content_hash === local.content_hash) return;
      if (String(pub.build_id || "").localeCompare(String(local.build_id || "")) <= 0) return;
      chip.classList.remove("hidden");
    });
  }

  function hostSend(message) {
    if (!S.online) { widgetPost("error", { text: "Companion is offline — message not sent." }); return; }
    if (S.running) { widgetPost("error", { text: "Companion is busy — message not sent." }); return; }
    var input = $("input");
    input.value = message;
    autoGrow();
    submit();
  }

  function clearConversation() {
    var msgs = $("messages");
    if (msgs) msgs.innerHTML = "";
    hideTaskCard();
    var cc = $("completionCard");
    if (cc) cc.classList.add("hidden");
    S.attached = [];
    renderAttachChips();
    if (S.es) { S.es.close(); S.es = null; }
    S.running = false; S.taskId = null;
    setMode("idle");
    setState("idle");
    widgetPost("cleared", {});
  }

  window.addEventListener("message", function (ev) {
    if (!window.AVAWidget) return;
    var cmd = window.AVAWidget.parseCommand(ev.data);
    if (!cmd) return;
    if (cmd.command === "send") hostSend(cmd.message);
    else if (cmd.command === "clear") clearConversation();
    else if (cmd.command === "focus") $("input").focus();
  });

  function toast(msg) {
    var el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.remove("show"); }, 2400);
  }

  /* ============================================================
     AVATAR STATE MACHINE
     ============================================================ */
  var STATE_LABELS = {
    idle: "Ready. What should we build?",
    listening: "Listening…",
    thinking: "Thinking…",
    speaking: "",
    working: "Working on it…",
    success: "Done.",
    error: "Something went wrong — see the message below."
  };

  function setState(st, label) {
    body.dataset.state = st;
    if (label !== undefined) $("statusLine").textContent = label;
    else if (st !== "speaking" && st !== "working" && st !== "thinking") {
      $("statusLine").textContent = STATE_LABELS[st] || "";
    }
    if (st === "success") fireBurst();
  }

  /* Richer assistant modes: an additive visual channel driven by the same
     backend stage classifier. body[data-mode] gives the CSS distinct
     PLANNING / BUILDING / CHECKING / FIXING / APPROVAL / COMPLETE / ERROR
     presentations on top of body[data-state]. Never changes backend calls. */
  function setMode(mode) {
    body.dataset.mode = mode || "idle";
  }

  function fireBurst() {
    var b = $("burst");
    b.classList.remove("fire");
    // restart animation
    void b.offsetWidth;
    b.classList.add("fire");
  }

  /* ============================================================
     WORKSPACE CONTEXT + VISUAL DIRECTOR (additive)
     Drives the context rail, mission banner plan trail, live-work
     status and director lifecycle from the SAME backend events —
     never invents data. Every access is null-guarded so older
     HTML (without these elements) keeps working untouched.
     ============================================================ */
  var ctx = { plan: [] };

  function updateMissionUI(state, title, text) {
    var card = $("ctxMission");
    if (!card) return;
    card.dataset.mc = state || "idle";
    var t = $("ctxMissionTitle"), b = $("ctxMissionText"), st = $("ctxMissionState");
    if (title != null && t) t.textContent = title;
    if (text != null && b) b.textContent = text;
    if (st) st.textContent = ({
      idle: "idle", running: "in progress", complete: "complete",
      error: "attention", cancelled: "cancelled"
    }[state] || state || "idle");
  }

  function addRecentMission(prompt) {
    var list = $("ctxRecentList");
    if (!list) return;
    var t = String(prompt || "").trim();
    if (!t) return;
    var empty = list.querySelector(".rail-empty");
    if (empty) empty.remove();
    var li = document.createElement("li");
    li.textContent = t.length > 58 ? t.slice(0, 58) + "…" : t;
    li.title = t;
    list.insertBefore(li, list.firstChild);
    while (list.children.length > 6) list.removeChild(list.lastChild);
  }

  function renderPlan(steps) {
    var trail = $("planTrail");
    if (trail) trail.innerHTML = "";
    ctx.plan = [];
    if (Array.isArray(steps)) {
      steps.forEach(function (s) {
        if (s == null) return;
        var t = (typeof s === "string") ? s : (s.title || s.step || s.name || JSON.stringify(s));
        ctx.plan.push(String(t));
      });
    }
    if (!trail) return;
    ctx.plan.slice(0, 5).forEach(function (t, i) {
      var li = document.createElement("li");
      li.textContent = t.length > 44 ? t.slice(0, 44) + "…" : t;
      li.title = t;
      if (i === 0) li.classList.add("now");
      trail.appendChild(li);
    });
  }

  function advancePlan(doneCount) {
    var trail = $("planTrail");
    if (!trail || !trail.children.length) return;
    for (var i = 0; i < Math.min(doneCount, trail.children.length); i++) {
      trail.children[i].classList.remove("now");
      trail.children[i].classList.add("done");
    }
    if (doneCount < trail.children.length) trail.children[doneCount].classList.add("now");
  }

  var REVIEW_ROWS = [["visual", "Visual"], ["composition", "Composition"], ["lighting", "Lighting"], ["materials", "Materials"], ["framing", "Framing"]];

  function renderReview(s) {
    var wrap = $("reviewMetrics");
    if (!wrap) return;
    var metrics = null;
    if (s) {
      var cand = s.metrics || s.scorecard || s.analysis || (s.vision_review && s.vision_review.metrics) || null;
      if (cand && typeof cand === "object") metrics = cand;
    }
    if (!metrics) {
      wrap.dataset.ready = "0";
      REVIEW_ROWS.forEach(function (row) {
        var k = row[0];
        var bar = $("rmBar" + k[0].toUpperCase() + k.slice(1));
        var val = $("rmVal" + k[0].toUpperCase() + k.slice(1));
        if (bar) bar.style.width = "0";
        if (val) val.textContent = "—";
      });
      return;
    }
    wrap.dataset.ready = "1";
    REVIEW_ROWS.forEach(function (row) {
      var k = row[0];
      var raw = metrics[k] != null ? metrics[k] : (metrics.overall != null ? metrics.overall : null);
      if (raw == null) return;
      var v = Math.max(0, Math.min(10, Number(raw) || 0));
      var bar = $("rmBar" + k[0].toUpperCase() + k.slice(1));
      var val = $("rmVal" + k[0].toUpperCase() + k.slice(1));
      if (bar) bar.style.width = (v * 10) + "%";
      if (val) val.textContent = v.toFixed(1);
    });
    if (s.diagnosis) { var dg = $("reviewDiagnosis"); if (dg) dg.textContent = String(s.diagnosis); }
    if (s.action) { var ac = $("reviewAction"); if (ac) ac.textContent = String(s.action); }
  }

  function applyPipFrame() {
    var pipEl = $("pip");
    if (!pipEl) return;
    var ph = $("directorStrip") ? ($("directorStrip").dataset.phase || "") : "";
    var frame = "captured";
    if (ph === "review" || ph === "repair") frame = "reviewing";
    else if (ph === "verified") frame = "complete";
    else if (ph === "failed") frame = "captured";
    else if (pip.fresh) frame = "live";
    pipEl.dataset.frame = frame;
  }

  function setDirectorPhase(phase) {
    var strip = $("directorStrip");
    if (strip) strip.dataset.phase = phase || "";
    var ph = $("reviewPhase");
    var map = { capture: "capturing", review: "reviewing", repair: "repairing", recapture: "recapturing", verified: "verified", failed: "attention" };
    if (ph) ph.textContent = map[phase] || "idle";
    var dg = $("reviewDiagnosis"), ac = $("reviewAction");
    var text = {
      capture: ["Capturing the viewport…", "recording proof from Unreal"],
      review: ["Analyzing composition, lighting and framing…", ""],
      repair: ["Diagnosing the result", "adjusting and recapturing"],
      verified: ["Visual review passed", ""],
      failed: ["Visual review failed", "see the response below"]
    };
    if (!phase) { if (dg) dg.textContent = "Awaiting capture analysis"; if (ac) ac.textContent = ""; }
    else if (text[phase]) { if (dg) dg.textContent = text[phase][0]; if (ac) ac.textContent = text[phase][1]; }
    applyPipFrame();
  }

  function setWorkStatus(text) {
    var el = $("workStatus");
    if (el) el.textContent = text || "";
  }

  function setRuntimeInfo(s) {
    if (!s) return;
    var eng = s.unreal && s.unreal.engine;
    var bridge = s.unreal && s.unreal.message;
    var ver = String(eng || "").match(/^(\d+\.\d+)/);
    if (eng) { var e = $("runtimeEngine"); if (e) e.textContent = ver ? "Unreal " + ver[1] : eng; }
    if (bridge) { var b = $("runtimeBridge"); if (b) { b.textContent = bridge === "UNREAL_BRIDGE_READY" ? "ready" : bridge; b.className = bridge === "UNREAL_BRIDGE_READY" ? "ok" : "off"; } }
    if (s.models && s.models.coder) { var m = $("runtimeModel"); if (m) m.textContent = String(s.models.coder).replace(/:latest$/, ""); }
    var dot = $("envDot");
    if (dot) dot.className = "env-dot" + (bridge === "UNREAL_BRIDGE_READY" ? "" : " off");
    var tx = $("envText");
    if (tx) tx.textContent = "Unreal " + (ver ? ver[1] : "") + " · " + (bridge === "UNREAL_BRIDGE_READY" ? "bridge ready" : "bridge offline");
  }

  /* ============================================================
     BACKGROUND: PARTICLE NETWORK
     ============================================================ */
  var canvas = $("scene"), ctx = canvas.getContext("2d");
  var particles = [], W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  var mouse = { x: -9999, y: -9999 };

  function sizeCanvas() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var target = Math.min(88, Math.max(34, Math.round((W * H) / 24000)));
    while (particles.length < target) particles.push(makeParticle(true));
    particles.length = target;
  }

  function makeParticle(anywhere) {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.22,
      vy: (Math.random() - 0.5) * 0.22 - 0.04,
      r: 0.6 + Math.random() * 1.4,
      hue: Math.random() < 0.75 ? "189" : "240",
      tw: Math.random() * Math.PI * 2
    };
  }

  var glowUp = 0;
  function drawFrame() {
    ctx.clearRect(0, 0, W, H);
    var state = body.dataset.state;
    var speed = 1;
    if (state === "thinking" || state === "working") speed = 1.9;
    else if (state === "speaking" || state === "listening") speed = 1.35;
    glowUp = Math.min(1, glowUp + (state === "success" ? 0.08 : -0.04));

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.x += p.vx * speed; p.y += p.vy * speed;
      p.tw += 0.02 * speed;
      if (p.x < -20) p.x = W + 20; if (p.x > W + 20) p.x = -20;
      if (p.y < -20) p.y = H + 20; if (p.y > H + 20) p.y = -20;
    }

    var linkDist = 110;
    for (var a = 0; a < particles.length; a++) {
      for (var b = a + 1; b < particles.length; b++) {
        var pa = particles[a], pb = particles[b];
        var dx = pa.x - pb.x, dy = pa.y - pb.y;
        var d2 = dx * dx + dy * dy;
        if (d2 < linkDist * linkDist) {
          var alpha = (1 - Math.sqrt(d2) / linkDist) * 0.16;
          ctx.strokeStyle = "rgba(110,160,255," + alpha.toFixed(3) + ")";
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
        }
      }
    }

    for (var k = 0; k < particles.length; k++) {
      var q = particles[k];
      var glow = 0.35 + Math.sin(q.tw) * 0.25 + glowUp * 0.35;
      var mdx = q.x - mouse.x, mdy = q.y - mouse.y;
      if (mdx * mdx + mdy * mdy < 160 * 160) glow = Math.min(1, glow + 0.3);
      ctx.beginPath();
      ctx.fillStyle = "hsla(" + q.hue + ",90%,70%," + glow.toFixed(2) + ")";
      ctx.arc(q.x, q.y, q.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(drawFrame);
  }

  /* ============================================================
     STATUS POLLING
     ============================================================ */
  function setOnline(online, busy, approvals) {
    S.online = online; S.busy = !!busy; S.approvals = approvals || 0;
    var dot = $("statusDot"), txt = $("statusText");
    if (!online) { dot.className = "dot off"; txt.textContent = "Offline"; }
    else if (busy) { dot.className = "dot busy"; txt.textContent = "Busy — agent working"; }
    else { dot.className = "dot ok"; txt.textContent = "Online"; }
    updateSend();
    if (S.running && approvals > 0) enterApprovalMode();
    if (!S._readySent) { S._readySent = true; widgetPost("ready", { online: online }); }
  }

  function pollStatus() {
    api("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      setOnline(true, !!(s.execution_active), (s.pending_approvals || 0));
      setRuntimeInfo(s);
    }).catch(function () {
      setOnline(false, false, 0);
    });
  }

  /* ============================================================
     LIVE METAHUMAN PICTURE-IN-PICTURE
     Polls /api/proof/live/status and shows the freshest AvaLive viewport
     capture (speaking MetaHuman during PIE runs, scene otherwise).
     ============================================================ */
  var pip = { img: null, lastM: 0, visible: false, fresh: false };

  function pipTick() {
    api("/api/proof/live/status").then(function (r) { return r.json(); }).then(function (s) {
      if (!s || s.ok !== true || !s.size || !s.mtime) {
        if (pip.visible) { pip.visible = false; $("pip").classList.add("hidden"); }
        var g0 = $("pipGhost");
        if (g0) g0.classList.remove("hidden");
        setWorkStatus("awaiting capture");
        return;
      }
      pip.visible = true;
      var ghost = $("pipGhost");
      if (ghost) ghost.classList.add("hidden");
      $("pip").classList.remove("hidden");
      var fresh = (Date.now() / 1000) - s.mtime < 6;
      pip.fresh = fresh;
      $("pipBadge").textContent = fresh ? "LIVE" : "CAPTURE";
      $("pipBadge").className = "pip-badge" + (fresh ? " live" : "");
      var cm = $("captureMeta");
      if (cm) cm.textContent = fresh ? "live · just now" : "capture on file";
      setWorkStatus(fresh ? "live capture" : "capture on file");
      applyPipFrame();
      renderReview(s);
      if (s.mtime !== pip.lastM) {
        pip.lastM = s.mtime;
        pip.img.src = "/api/proof/live?t=" + Math.round(s.mtime * 1000);
        pip.img.classList.remove("fresh");
        void pip.img.offsetWidth;
        pip.img.classList.add("fresh");
      }
    }).catch(function () {
      if (pip.visible) { pip.visible = false; $("pip").classList.add("hidden"); }
      var g = $("pipGhost");
      if (g) g.classList.remove("hidden");
      setWorkStatus("awaiting capture");
    });
  }

  /* ============================================================
     CHAT RENDERING
     ============================================================ */
  var MAX_VISIBLE = 14;

  function markOlder() {
    var msgs = $("messages").querySelectorAll(".msg");
    for (var i = 0; i < msgs.length; i++) {
      msgs[i].classList.toggle("older", i < msgs.length - MAX_VISIBLE);
    }
  }

  function addUserMsg(text) {
    var wrap = document.createElement("div");
    wrap.className = "msg user";
    var b = document.createElement("div");
    b.className = "user-bubble";
    b.textContent = text;
    wrap.appendChild(b);
    $("messages").appendChild(wrap);
    markOlder();
    scrollChat();
    return wrap;
  }

  function addAiMsg() {
    var wrap = document.createElement("div");
    wrap.className = "msg ai";
    var card = document.createElement("div");
    card.className = "ai-card";

    var mini = document.createElement("div");
    mini.className = "ai-mini";

    var bubble = document.createElement("div");
    bubble.className = "ai-bubble";
    var dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.innerHTML = "<i></i><i></i><i></i>";
    bubble.appendChild(dots);

    var actions = document.createElement("div");
    actions.className = "ai-actions";

    card.appendChild(mini); card.appendChild(bubble);
    wrap.appendChild(card);
    $("messages").appendChild(wrap);
    markOlder();
    scrollChat();

    return {
      el: wrap, mini: mini, bubble: bubble, actions: actions,
      startTyping: function () {
        mini.classList.add("speaking");
        bubble.textContent = "";
        var d = document.createElement("span");
        d.className = "typing-dots";
        d.innerHTML = "<i></i><i></i><i></i>";
        bubble.appendChild(d);
      },
      stream: function (text, done) {
        mini.classList.add("speaking");
        setState("speaking");
        bubble.textContent = "";
        var caret = document.createElement("span");
        caret.className = "caret";
        bubble.appendChild(caret);
        var i = 0, n = text.length;
        (function tick() {
          if (!S.running && i >= n) { caret.remove(); mini.classList.remove("speaking"); bubble.innerHTML = fmtMd(text); if (done) done(); return; }
          var chunk = 1 + Math.floor(Math.random() * 3);
          var node = document.createTextNode(text.slice(i, i + chunk));
          bubble.insertBefore(node, caret);
          i += chunk;
          scrollChat();
          if (i >= n) {
            caret.remove();
            mini.classList.remove("speaking");
            bubble.innerHTML = fmtMd(text);
            if (done) done();
            return;
          }
          var delay = reducedMotion ? 1 : Math.max(3, 14 - Math.floor(Math.random() * 8));
          setTimeout(tick, delay);
        })();
      },
      setPlain: function (text) {
        mini.classList.remove("speaking");
        bubble.innerHTML = fmtMd(text);
        scrollChat();
      },
      addActions: function (list) {
        var self = this;
        list.forEach(function (it) {
          var b = document.createElement("button");
          b.textContent = it.label;
          b.addEventListener("click", function (ev) { ev.stopPropagation(); it.onClick(); });
          self.actions.appendChild(b);
        });
        card.appendChild(actions);
      }
    };
  }

  function scrollChat() {
    var c = $("chat");
    if (reducedMotion) c.scrollTop = c.scrollHeight;
    else c.scrollTo({ top: c.scrollHeight, behavior: "smooth" });
  }

  function formatAnswer(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    try {
      var s = JSON.stringify(detail, null, 2);
      if (s.length <= 2400) return s;
      return s.slice(0, 2400) + "\n… (truncated)";
    } catch (e) { return String(detail); }
  }

  /* ============================================================
     HUMAN-READABLE ERRORS
     Map known structured backend codes to user-facing copy instead of
     surfacing internal workflow wording. Fallback = original text.
     ============================================================ */
  var ERROR_COPY = [
    { re: /WRONG_PROJECT_CONTEXT/, msg: "This request targeted another project and was safely rejected. Nothing was changed." },
    { re: /EXECUTION_STALLED|(^|\s)STALLED(\s|$)/, msg: "The task couldn't be completed automatically — it stopped making progress. Try asking for a smaller, more specific step." },
    { re: /PYTHON_EXECUTION_FAILED|EXECUTION_FAILED/, msg: "Unreal reported an error while running that command. Check the response details below." },
    { re: /BRIDGE_REQUEST_FAILED|ConnectionRefused|timed out/i, msg: "The editor didn't respond in time — it may still be busy. Try again in a moment." },
    { re: /BLOCKED|needs your approval|approval/i, msg: "This step needs your confirmation before it can continue." },
    { re: /Mandatory step/i, msg: "A required step failed, so the task stopped early. See the response details below." }
  ];
  function humanizeError(text) {
    var t = String(text || "");
    for (var i = 0; i < ERROR_COPY.length; i++) {
      if (ERROR_COPY[i].re.test(t)) return ERROR_COPY[i].msg;
    }
    return t;
  }

  /* ============================================================
     TASK CARD
     ============================================================ */
  var TOOL_LABELS = {
    spawn_actor: "Placing actor",
    spawn_actor_at: "Placing actor",
    create_blueprint: "Creating blueprint",
    create_actor: "Creating actor",
    set_actor_location: "Positioning actor",
    set_material: "Applying material",
    save_level: "Saving level",
    compile_blueprint: "Compiling blueprint",
    get_actor: "Verifying actor",
    get_blueprint: "Verifying blueprint",
    list_level_actors: "Scanning level",
    inspect_actor: "Inspecting actor",
    capture_viewport: "Capturing viewport",
    capture_pie_viewport: "Capturing viewport",
    open_project: "Opening project",
    load_level: "Loading level",
    delete_actor: "Removing actor",
    set_actor_scale: "Scaling actor",
    set_actor_rotation: "Rotating actor",
    write_text_file: "Writing file",
    run_powershell: "Running command",
    import_asset: "Importing asset",
    execute_python: "Running script"
  };

  function humanTool(tool) {
    if (!tool) return "Working…";
    return TOOL_LABELS[tool] || String(tool).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function showTaskCard() {
    body.dataset.tc = "on";
    body.classList.add("work-open");
    $("taskCard").classList.remove("hidden");
  }
  function hideTaskCard() {
    body.dataset.tc = "off";
    $("taskCard").classList.add("hidden");
  }

  function setTaskCard(opts) {
    opts = opts || {};
    var card = $("taskCard");
    card.dataset.tc = opts.tc || "working";
    if (opts.title) $("tcTitle").textContent = opts.title;
    $("tcBadge").textContent = opts.badge || opts.tc || "working";
    if (opts.pct != null) {
      $("tcBar").style.width = Math.max(2, Math.min(100, opts.pct)) + "%";
      $("tcPct").textContent = Math.round(opts.pct) + "%";
    }
    if (opts.step) $("tcStep").textContent = opts.step;

    var isApproval = card.dataset.tc === "approval";
    $("tcApprove").classList.toggle("hidden", !isApproval);
    $("tcReject").classList.toggle("hidden", !isApproval);
    $("tcExpand").classList.toggle("hidden", isApproval);
    $("tcCancel").classList.toggle("hidden", isApproval);
    $("tcDismiss").classList.toggle("hidden", card.dataset.tc !== "success" && card.dataset.tc !== "error");
    if (isApproval) $("tcStep").textContent = "The agent needs your confirmation to continue.";
  }

  function enterApprovalMode() {
    if (!S.running) return;
    setMode("approval");
    setState("idle", "Waiting for your confirmation…");
    setTaskCard({
      tc: "approval",
      badge: "confirmation",
      title: S.lastPrompt ? S.lastPrompt.slice(0, 60) : "Aivido",
      pct: 100,
      step: "The agent needs your confirmation to continue."
    });
    showTaskCard();
  }

  /* ============================================================
     STAGE / PROGRESS MAPPING
     ============================================================ */
  var STAGES = [
    { key: "understand", keys: ["understanding"], label: "Reading your request" },
    { key: "plan", keys: ["planning", "planned", "plan_generated", "execution_plan"], label: "Planning the approach" },
    { key: "edit", keys: ["editing", "dispatch", "tool", "spawn", "create_", "set_", "delete_"], label: "Building your scene" },
    { key: "build", keys: ["building", "compile", "save_level", "save", "import_"], label: "Compiling assets" },
    { key: "validate", keys: ["validating", "validation", "verify", "get_", "list_", "inspect", "capture"], label: "Checking the result" },
    { key: "fix", keys: ["fixing", "fix", "retry", "replan"], label: "Repairing the issue" }
  ];
  var STAGE_ORDER = ["understand", "plan", "edit", "build", "validate", "fix"];

  function stageOf(type, title, tool) {
    var t = String(type || "").toLowerCase() + " " + String(title || "").toLowerCase();
    for (var i = 0; i < STAGES.length; i++) {
      for (var j = 0; j < STAGES[i].keys.length; j++) {
        if (t.indexOf(STAGES[i].keys[j]) !== -1) return STAGES[i].key;
      }
    }
    var tl = String(tool || "").toLowerCase();
    if (/spawn|create/.test(tl)) return "edit";
    if (/save|compile/.test(tl)) return "build";
    if (/get_|list_|inspect|capture|verify/.test(tl)) return "validate";
    return null;
  }

  function stageLabel(key) {
    for (var i = 0; i < STAGES.length; i++) if (STAGES[i].key === key) return STAGES[i].label;
    return "Working";
  }

  function refreshTaskProgress() {
    var pct = S.planSteps ? Math.min(100, Math.round((S.doneSteps / S.planSteps) * 100)) : 12;
    var label = stageLabel(STAGE_ORDER[Math.min(S.stageIdx, STAGE_ORDER.length - 1)]);
    setTaskCard({
      tc: "working",
      badge: "working",
      title: label + "…",
      pct: pct,
      step: $("tcStep").textContent || "Working…"
    });
  }

  /* ============================================================
     EVENT HANDLING (SSE)
     ============================================================ */
  function handleEvent(e) {
    if (!e || !S.running) return;
    var type = String(e.type || e.event || "");
    var title = String(e.title || "");
    var detail = e.detail;
    var tool = (detail && detail.step_id) || e.tool_name || (title.match(/^(?:Running|finished|failed)\s+([a-z0-9_]+)/i) || [])[1] || "";

    var st = stageOf(type, title, tool);
    if (st) {
      setMode(st);
      var idx = STAGE_ORDER.indexOf(st);
      if (idx > S.stageIdx) {
        S.stageIdx = idx;
        setState("working", stageLabel(st) + "…");
      }
      setDirectorPhase(st === "validate" ? "review" : (st === "fix" ? "repair" : (st === "edit" || st === "build" ? "capture" : "")));
    }

    if (type === "planning") {
      S.stageIdx = Math.max(S.stageIdx, 1);
      if (detail && Array.isArray(detail.steps)) {
        S.planSteps = detail.steps.length;
        S.doneSteps = 0;
        renderPlan(detail.steps);
      }
      setMode("plan");
      setState("working", "Planning…");
      showTaskCard();
      setTaskCard({ tc: "working", badge: "planning", title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Planning", pct: 6, step: "Planning the approach…" });
      return;
    }

    if (type === "tool" && e.status === "running") {
      showTaskCard();
      setTaskCard({ tc: "working", badge: "working", title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Building", step: humanTool(tool) + "…" });
      setWorkStatus(humanTool(tool));
      refreshTaskProgress();
      return;
    }

    if (type === "tool_result") {
      S.doneSteps++;
      advancePlan(S.doneSteps);
      if (e.status === "success" || (detail && detail.ok === true)) {
        setTaskCard({ tc: "working", badge: "working", title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Building", step: "✓ " + humanTool(tool) });
      } else {
        setTaskCard({ tc: "working", badge: "working", title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Building", step: humanTool(tool) + " — retrying…" });
      }
      refreshTaskProgress();
      return;
    }

    if (type === "answer") {
      // conversational answer (chat mode) — stream it
      var ansText = typeof detail === "string" ? detail : (detail && (detail.message || detail.summary)) || "";
      if (ansText) streamAnswer(ansText);
      return;
    }

    if (type === "final" || type === "complete") {
      var okFinal = !(e.status === "failed" || e.status === "error" || (detail && detail.ok === false));
      finishTask(okFinal, formatAnswer(detail), e);
      return;
    }

    if (type === "error") {
      var emsg = (typeof detail === "string" ? detail : (detail && detail.message)) || title || "Execution error";
      finishTask(false, emsg, e);
      return;
    }

    if (type === "approval") {
      enterApprovalMode();
      return;
    }
  }

  /* ============================================================
     COMPANION SPEECH (auto-triggered, fire-and-forget)
     After a reply finishes, ask the backend to run the proven
     frozen speak pipeline. Never blocks the reply; the backend is
     single-flight and truthfully skips when AvaLive is offline.
     ============================================================ */
  function speakChip(mode, text) {
    var chip = $("speakChip");
    if (!chip) return;
    chip.className = "speak-chip" + (mode ? " " + mode : "");
    chip.textContent = text || "";
  }

  function speakStatusPoll() {
    api("/api/chat/speak/status").then(function (r) { return r.json(); }).then(function (s) {
      if (s && s.active) { speakChip("playing", "Companion speaking…"); setTimeout(speakStatusPoll, 4000); return; }
      if (s && s.last) {
        if (s.last.status === "skipped_unavailable") {
          speakChip("skipped", "AvaLive offline — speech skipped");
          widgetPost("speaking", { state: "skip", reason: "unavailable" });
          setTimeout(function () { speakChip("", ""); }, 6000);
          return;
        }
        var ok = !!(s.last.ok);
        speakChip(ok ? "playing" : "error", ok ? "Spoken ✓" : "Speech error");
        widgetPost("speaking", ok ? { state: "done" } : { state: "error" });
        setTimeout(function () { speakChip("", ""); }, 6000);
        return;
      }
      speakChip("", "");
    }).catch(function () { speakChip("", ""); });
  }

  function triggerSpeak(ev) {
    if (!S.online) return; // editor offline: PiP already hides; skip silently
    api("/api/chat/speak", { method: "POST" }).then(function (r) { return r.json(); }).then(function (s) {
      if (!s) return;
      if (s.speak === "started") { speakChip("playing", "Companion speaking…"); widgetPost("speaking", { state: "start" }); setTimeout(speakStatusPoll, 4000); return; }
      if (s.speak === "skipped_active") { speakChip("playing", "Speaking (already active)…"); widgetPost("speaking", { state: "skip", reason: "active" }); setTimeout(speakStatusPoll, 4000); return; }
      if (s.speak === "skipped_unavailable") { speakChip("skipped", "AvaLive offline — speech skipped"); widgetPost("speaking", { state: "skip", reason: "unavailable" }); setTimeout(function () { speakChip("", ""); }, 6000); return; }
    }).catch(function () {});
  }

  function streamAnswer(text) {
    var h = currentAiHandle;
    if (!h) h = addAiMsg();
    h.stream(text, function () {
      setState("success");
      widgetPost("typing", { state: "end" });
      widgetPost("reply", { text: text, mode: "chat" });
      triggerSpeak();
    });
  }

  function finishTask(ok, text, ev) {
    S.running = false;
    if (S.es) { S.es.close(); S.es = null; }
    S.taskId = null;

    if (ok) {
      setMode("complete");
      setState("success");
      setDirectorPhase("verified");
      setWorkStatus("verified");
      updateMissionUI("complete", S.lastPrompt ? S.lastPrompt.slice(0, 64) + "…" : "Mission complete", "The mission completed and the result was verified in the live surface.");
      showCompletion("Complete", summarize(text));
      widgetPost("typing", { state: "end" });
      widgetPost("reply", { text: text, mode: "task" });
      triggerSpeak();
      setTaskCard({
        tc: "success", badge: "complete",
        title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Complete",
        pct: 100,
        step: "Done — the task completed successfully."
      });
    } else {
      setMode("error");
      setState("error");
      setDirectorPhase("failed");
      setWorkStatus("attention needed");
      updateMissionUI("error", S.lastPrompt ? S.lastPrompt.slice(0, 64) + "…" : "Mission", "The mission did not complete — see the response below.");
      showCompletion("Attention", "The task didn't complete. See the response below.", true);
      setTaskCard({
        tc: "error", badge: "attention",
        title: S.lastPrompt ? S.lastPrompt.slice(0, 64) : "Task",
        pct: 100,
        step: "Something went wrong — the agent explains below."
      });
      text = humanizeError(text);
      widgetPost("typing", { state: "end" });
      widgetPost("error", { text: text });
    }

    if (text) {
      var h = currentAiHandle || addAiMsg();
      h.stream(text, function () { /* idle */ });
      setTimeout(function () { if (!S.running) setState("idle"); }, 1400);
    } else {
      setTimeout(function () { if (!S.running) setState("idle"); }, 1600);
    }
    pollStatus();
  }

  function summarize(text) {
    var s = String(text || "").replace(/\s+/g, " ").trim();
    return s.length > 110 ? s.slice(0, 110) + "…" : s;
  }

  function showCompletion(title, msg, warn) {
    var c = $("completionCard");
    $("completionTitle").textContent = title;
    $("completionMsg").textContent = msg;
    c.classList.toggle("warn", !!warn);
    c.classList.remove("out", "hidden");
    clearTimeout(showCompletion._t);
    showCompletion._t = setTimeout(function () {
      c.classList.add("out");
      setTimeout(function () { c.classList.add("hidden"); c.classList.remove("out"); }, 500);
    }, warn ? 5200 : 3400);
  }

  /* ============================================================
     SUBMIT
     ============================================================ */
  var currentAiHandle = null;

  function updateSend() {
    var input = $("input");
    var empty = !input.value.trim();
    var off = !S.online;
    $("sendBtn").disabled = empty || S.running || off;
  }

  function submit() {
    var input = $("input");
    var text = input.value.trim();
    if (!text || S.running || !S.online) return;
    if (S.listening) stopListening();

    S.lastPrompt = text;
    updateMissionUI("running", text.length > 64 ? text.slice(0, 64) + "…" : text, "Planning, building and verifying in Unreal — watch the live surface.");
    addRecentMission(text);
    setWorkStatus("mission running");
    renderPlan([]);
    input.value = "";
    autoGrow();
    updateSend();

    var promptText = text;
    if (S.attached.length) {
      promptText += "\n\nReference files for the request: " + S.attached.map(function (f) { return f.name; }).join(", ");
    }
    S.attached = [];
    renderAttachChips();

    addUserMsg(text);
    var h = addAiMsg();
    currentAiHandle = h;
    h.startTyping();

    S.running = true;
    S.planSteps = 0; S.doneSteps = 0; S.stageIdx = -1;
    setMode("thinking");
    setState("thinking", "Thinking…");
    widgetPost("typing", { state: "start" });

    api("/api/action", {
      method: "POST",
      body: { action: "prompt", payload: { message: promptText }, context: { model: localStorage.getItem("ua_model") || "reasoning", reasoning: "standard" } }
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    }).then(function (res) {
      if (!res.ok) {
        var msg = (res.json && (res.json.detail || res.json.error)) || ("HTTP " + res.status);
        failLocal("Submission failed", String(msg));
        return;
      }
      var j = res.json;
      var taskId = j.task_id || (j.data && j.data.task_id);
      if (taskId) {
        S.taskId = taskId;
        showTaskCard();
        setTaskCard({ tc: "working", badge: "starting", title: text.slice(0, 64), pct: 4, step: "Starting agent…" });
        streamTask(taskId);
        return;
      }
      // synchronous answer (plan / simple chat)
      var answer = (j.data && j.data.message) || j.message || j.answer || "";
      if (answer) {
        currentAiHandle = h;
        streamAnswer(answer);
        S.running = false;
        updateSend();
        setTimeout(function () { setState("idle"); }, 1600);
        return;
      }
      failLocal("Unexpected response", JSON.stringify(j).slice(0, 400));
    }).catch(function (err) {
      failLocal("Submission failed", String(err && err.message || err));
    });
  }

  function failLocal(title, msg) {
    setMode("error");
    setState("error");
    setDirectorPhase("failed");
    setWorkStatus("attention needed");
    updateMissionUI("error", S.lastPrompt ? S.lastPrompt.slice(0, 64) + "…" : "Mission", "The mission could not start — see the response below.");
    showCompletion("Attention", msg, true);
    if (currentAiHandle) currentAiHandle.setPlain(msg);
    widgetPost("typing", { state: "end" });
    widgetPost("error", { text: msg });
    S.running = false;
    if (S.es) { S.es.close(); S.es = null; }
    S.taskId = null;
    hideTaskCard();
    updateSend();
    setTimeout(function () { setState("idle"); }, 2000);
  }

  function streamTask(taskId) {
    if (S.es) S.es.close();
    var es = new EventSource("/api/events/stream/" + encodeURIComponent(taskId));
    S.es = es;
    es.onmessage = function (msg) {
      var e;
      try { e = JSON.parse(msg.data); } catch (err) { return; }
      if (e && (e.type === "ping" || e.type === "keepalive")) return;
      handleEvent(e || {});
    };
    es.onerror = function () {
      es.close();
      S.es = null;
      if (S.running) setTimeout(function () { pollTask(taskId); }, 1600);
    };
  }

  function pollTask(taskId) {
    if (!S.running) return;
    api("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      if (!S.running) return;
      if (s && !s.execution_active) {
        api("/api/events").then(function (r) { return r.json(); }).then(function (d) {
          if (!S.running) return;
          var evs = (d.events || []).filter(function (e) { return e.task_id === taskId; });
          var finalEv = null;
          for (var i = evs.length - 1; i >= 0; i--) {
            if (evs[i].type === "final" || evs[i].type === "complete" || evs[i].type === "error" || evs[i].status === "failed") { finalEv = evs[i]; break; }
          }
          if (finalEv) handleEvent(finalEv);
          else failLocal("Task ended", "The task ended without a terminal event. Check Advanced → Terminal for details.");
        });
      } else {
        setTimeout(function () { pollTask(taskId); }, 1800);
      }
    }).catch(function () {
      if (S.running) setTimeout(function () { pollTask(taskId); }, 2200);
    });
  }

  function cancelTask() {
    if (!S.running) return;
    api("/api/action", { method: "POST", body: { action: "cancel" } }).then(function (r) { return r.json(); })
      .then(function (j) {
        toast("Task cancelled");
        if (currentAiHandle) currentAiHandle.setPlain("Task cancelled.");
        finishCancel();
      }).catch(function () {
        toast("Cancel request failed — retrying");
        finishCancel();
      });
  }

  function finishCancel() {
    S.running = false;
    if (S.es) { S.es.close(); S.es = null; }
    S.taskId = null;
    body.classList.remove("work-open");
    hideTaskCard();
    updateSend();
    setMode("idle");
    setState("idle", "Cancelled. Ready when you are.");
    setDirectorPhase("");
    setWorkStatus("awaiting capture");
    updateMissionUI("cancelled", S.lastPrompt ? S.lastPrompt.slice(0, 64) + "…" : "Mission", "Mission cancelled. Describe what to build next.");
  }

  function resolveApproval(approved) {
    api("/api/action", {
      method: "POST",
      body: { action: approved ? "approval_approve" : "approval_reject" }
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok && !(j.data && j.data.state)) {
        toast("Approval not applied: " + ((j.detail) || "unknown"));
        return;
      }
      toast(approved ? "Approved — continuing" : "Rejected");
      if (!approved && S.running) {
        S.running = false;
        if (S.es) { S.es.close(); S.es = null; }
        updateSend();
      }
    }).catch(function (err) {
      toast("Approval failed: " + String(err.message || err).slice(0, 60));
    });
  }

  /* ============================================================
     COMPOSER
     ============================================================ */
  function autoGrow() {
    var t = $("input");
    t.style.height = "auto";
    t.style.height = Math.min(150, Math.max(38, t.scrollHeight)) + "px";
  }

  function renderAttachChips() {
    var wrap = $("attachChips");
    wrap.innerHTML = "";
    S.attached.forEach(function (f, idx) {
      var chip = document.createElement("span");
      chip.className = "attach-chip";
      chip.textContent = f.name;
      var rm = document.createElement("button");
      rm.textContent = "×";
      rm.title = "Remove";
      rm.addEventListener("click", function () {
        S.attached.splice(idx, 1);
        renderAttachChips();
      });
      chip.appendChild(rm);
      wrap.appendChild(chip);
    });
  }

  /* voice */
  function stopListening() {
    S.listening = false;
    body.dataset.voice = "off";
    $("micBtn").classList.remove("active");
    $("voiceHint").textContent = "";
    if (S.recognition) { try { S.recognition.stop(); } catch (e) { /* noop */ } }
    if (body.dataset.state === "listening" && !S.running) setState("idle");
  }

  function startListening() {
    if (S.running) { toast("Wait for the current task to finish"); return; }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SR) {
      try {
        var rec = new SR();
        S.recognition = rec;
        rec.lang = "en-US";
        rec.interimResults = true;
        rec.continuous = false;
        S.listening = true;
        body.dataset.voice = "listening";
        $("micBtn").classList.add("active");
        setState("listening");
        $("voiceHint").textContent = "Listening… speak now";

        rec.onresult = function (ev) {
          var text = "";
          for (var i = ev.resultIndex; i < ev.results.length; i++) {
            text += ev.results[i][0].transcript;
          }
          $("input").value = text.trim();
          autoGrow();
          updateSend();
        };
        var finish = function () {
          stopListening();
          if ($("input").value.trim()) { toast("Heard you — press send when ready"); }
        };
        rec.onend = finish;
        rec.onerror = function (ev) {
          stopListening();
          if (ev.error !== "aborted" && ev.error !== "no-speech") {
            toast("Voice unavailable here (" + ev.error + ")");
          }
        };
        rec.start();
        return;
      } catch (err) { /* fall through to visual mode */ }
    }

    // visual listening preview (no speech engine)
    S.listening = true;
    body.dataset.voice = "listening";
    $("micBtn").classList.add("active");
    setState("listening");
    $("voiceHint").textContent = "Listening… (voice engine unavailable — visual mode)";
    setTimeout(function () { stopListening(); }, 4200);
  }

  /* ============================================================
     ADVANCED DRAWER
     ============================================================ */
  function openDrawer() {
    body.classList.add("drawer-open");
    $("drawer").setAttribute("aria-hidden", "false");
  }
  function closeDrawer() {
    body.classList.remove("drawer-open");
    $("drawer").setAttribute("aria-hidden", "true");
  }

  /* ============================================================
     PARALLAX
     ============================================================ */
  var px = 0, py = 0, tx = 0, ty = 0;
  function parallaxLoop() {
    px += (tx - px) * 0.05;
    py += (ty - py) * 0.05;
    body.style.setProperty("--mx", px.toFixed(1) + "px");
    body.style.setProperty("--my", py.toFixed(1) + "px");
    requestAnimationFrame(parallaxLoop);
  }

  /* ============================================================
     INIT
     ============================================================ */
  function buildAvatarDecor() {
    // orbital dots
    var orbitA = $("orbitA"), orbitB = $("orbitB");
    [[orbitA, 3, 0], [orbitB, 4, 60]].forEach(function (cfg) {
      var track = document.createElement("div");
      track.className = "orbit-track";
      for (var i = 0; i < cfg[1]; i++) {
        var d = document.createElement("i");
        d.style.transform = "rotate(" + (cfg[2] + i * (360 / cfg[1])) + "deg) translateY(calc(var(--avR) * -1))";
        track.appendChild(d);
      }
      cfg[0].appendChild(track);
    });

    // waveform ring — 24 bars
    var wave = $("wave");
    for (var w = 0; w < 24; w++) {
      var bar = document.createElement("div");
      bar.className = "wbar";
      bar.style.transform = "rotate(" + (w * 15) + "deg) translateY(calc(var(--avR) * -1.04))";
      var i2 = document.createElement("i");
      i2.style.setProperty("--d", (Math.random() * 0.7).toFixed(2) + "s");
      bar.appendChild(i2);
      wave.appendChild(bar);
    }

    // thinking streams — 7 converging particles
    var streams = $("streams");
    for (var s = 0; s < 7; s++) {
      var ang = (s / 7) * Math.PI * 2;
      var r = 0.55 + Math.random() * 0.25;
      var d2 = document.createElement("i");
      d2.style.setProperty("--fx", Math.cos(ang) * r * 100 + "px");
      d2.style.setProperty("--fy", Math.sin(ang) * r * 100 + "px");
      d2.style.setProperty("--d", (Math.random() * 1.1).toFixed(2) + "s");
      streams.appendChild(d2);
    }

    // idle specks
    var specks = $("specks");
    for (var sp = 0; sp < 11; sp++) {
      var e = document.createElement("i");
      var a2 = (sp / 11) * Math.PI * 2;
      e.style.setProperty("--dx", (Math.cos(a2) * (34 + Math.random() * 30)).toFixed(0) + "px");
      e.style.setProperty("--dy", (Math.sin(a2) * (30 + Math.random() * 34)).toFixed(0) + "px");
      e.style.setProperty("--dur", (5 + Math.random() * 6).toFixed(1) + "s");
      e.style.setProperty("--d", (Math.random() * 5).toFixed(2) + "s");
      specks.appendChild(e);
    }
  }

  function init() {
    buildAvatarDecor();
    sizeCanvas();
    window.addEventListener("resize", sizeCanvas);
    requestAnimationFrame(drawFrame);

    window.addEventListener("mousemove", function (ev) {
      tx = (ev.clientX / window.innerWidth - 0.5) * 2;
      ty = (ev.clientY / window.innerHeight - 0.5) * 2;
      mouse.x = ev.clientX; mouse.y = ev.clientY;
    });
    requestAnimationFrame(parallaxLoop);

    // composer
    var input = $("input"), send = $("sendBtn");
    input.addEventListener("input", function () { autoGrow(); updateSend(); });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        if (!send.disabled) submit();
      }
    });
    send.addEventListener("click", submit);

    $("attachBtn").addEventListener("click", function () { $("fileInput").click(); });
    $("fileInput").addEventListener("change", function () {
      var files = Array.prototype.slice.call(this.files || []);
      files.forEach(function (f) { S.attached.push({ name: f.name, size: f.size }); });
      this.value = "";
      renderAttachChips();
      if (files.length) toast(files.length + " file reference(s) attached");
    });

    $("micBtn").addEventListener("click", function () {
      if (S.listening) stopListening(); else startListening();
    });

    // task card
    $("tcCancel").addEventListener("click", cancelTask);
    $("tcExpand").addEventListener("click", openDrawer);
    $("tcApprove").addEventListener("click", function () { resolveApproval(true); });
    $("tcReject").addEventListener("click", function () { resolveApproval(false); });
    $("tcDismiss").addEventListener("click", hideTaskCard);

    // update chip → public latest release
    var upd = $("updateChip");
    if (upd) upd.addEventListener("click", function () {
      window.open(PUBLIC_LATEST_URL, "_blank", "noopener");
    });

    // context rail toggle
    var railBtn = $("railToggle");
    if (railBtn) railBtn.addEventListener("click", function () {
      var closed = body.classList.toggle("rail-closed");
      railBtn.setAttribute("aria-label", closed ? "Open context panel" : "Collapse context panel");
    });

    // live-work sheet (narrow layout): header or chevron toggles expansion
    var workBtn = $("workToggle");
    if (workBtn) workBtn.addEventListener("click", function (ev) { ev.stopPropagation(); body.classList.toggle("work-open"); });
    var workHead = $("workHead");
    if (workHead) workHead.addEventListener("click", function () { body.classList.toggle("work-open"); });

    // status pill → advanced
    $("statusPill").addEventListener("click", openDrawer);
    $("advancedBtn").addEventListener("click", openDrawer);
    $("drawerClose").addEventListener("click", closeDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && body.classList.contains("drawer-open")) closeDrawer();
    });

    // boot
    pip.img = $("pipImg");
    pipTick();
    setInterval(pipTick, 2500);
    if (window.parent !== window) {
      // widget height feed: on load, on window/body resize, and on content change
      widgetPostHeight();
      var _hDeb;
      var postH = function () { clearTimeout(_hDeb); _hDeb = setTimeout(widgetPostHeight, 150); };
      window.addEventListener("resize", postH);
      if (window.ResizeObserver) new ResizeObserver(postH).observe(document.body);
      new MutationObserver(postH).observe($("messages"), { childList: true, subtree: true });
    }
    pollStatus();
    setInterval(pollStatus, 5000);
    updateCheck();
    setInterval(updateCheck, 15 * 60 * 1000);
    setInterval(function () {
      // if running and approvals pending, surface the confirmation card
      if (S.running && S.approvals > 0) enterApprovalMode();
    }, 2500);

    setMode("idle");
    setState("idle");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
