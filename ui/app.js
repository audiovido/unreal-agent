/* ============================================================
   Unreal Agent — workspace UI logic
   Wired to the real backend on the same origin:
     GET  /api/status                service health + models
     GET  /api/workspace             branch / commit / last verification
     GET  /api/workspace/changes     real `git status`
     GET  /api/workspace/files       repository file tree
     GET  /api/events                live backend event log
     GET  /api/events/stream/:id     SSE stream for a running task
     GET  /api/proof/status, /api/proof/latest
     POST /api/action                build (prompt) / plan actions
   ============================================================ */
(function () {
  "use strict";

  var API = location.origin || "http://127.0.0.1:8765";
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var now = function () { return new Date(); };
  var stamp = function (d) {
    d = d || now();
    return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2) + ":" + ("0" + d.getSeconds()).slice(-2);
  };
  var fmtSize = function (n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  };
  var shortId = function (id) { return id ? String(id).slice(0, 8) : "—"; };
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var state = {
    running: false,
    taskId: null,
    es: null,
    online: false,
    executionActive: false,
    models: {},
    proofUrl: null,
    files: [],
    filesLoaded: false,
    attached: [],
    agent: "unreal",
    mode: "build"
  };

  /* ---------------- API ---------------- */
  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, opts);
  }

  /* ---------------- Toast ---------------- */
  var toastTimer = null;
  function toast(msg) {
    var el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 2200);
  }

  /* ---------------- Copy ---------------- */
  function copyText(text, label) {
    if (!text) return;
    function done() { toast((label || "Copied") + " — " + String(text).slice(0, 40) + (text.length > 40 ? "…" : "")); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text); done(); });
    } else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* noop */ }
    document.body.removeChild(ta);
  }

  /* ============================================================
     STATUS + WORKSPACE POLLING
     ============================================================ */
  function setOnline(online, busy) {
    state.online = online;
    state.executionActive = !!busy;
    var dot = $("onlineDot"), txt = $("onlineText"), cs = $("composerState");
    dot.className = "dot " + (online ? "ok" : "off");
    txt.textContent = online ? (busy ? "Busy" : "Online") : "Offline";
    cs.innerHTML = '<span class="dot ' + (online ? "ok" : "off") + '"></span> ' + (online ? (busy ? "Busy" : "Online") : "Offline");
    cs.classList.toggle("off", !online);
    if (!online && !state.running) $("sendBtn").disabled = true;
    else if (online) updateSendState();
  }

  function populateModels(models) {
    if (!models) return;
    state.models = models;
    var sel = $("modelSel");
    if (sel.options.length) return;
    var keys = ["fast", "reasoning", "coder", "vision", "heavy"];
    var saved = localStorage.getItem("ua_model") || "";
    keys.forEach(function (k) {
      if (!models[k]) return;
      var opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k.charAt(0).toUpperCase() + k.slice(1) + " · " + models[k];
      sel.appendChild(opt);
      if (k === saved) opt.selected = true;
    });
    if (!saved) sel.value = "reasoning";
  }

  function refreshStatus() {
    return api("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      setOnline(true, !!(s.execution_active));
      populateModels(s.models || {});
      if (s.models && s.models.reasoning) $("headModel").textContent = s.models.reasoning;
      updatePreview(s);
      refreshQueue();
      return s;
    }).catch(function () {
      setOnline(false, false);
      return null;
    });
  }

  function refreshWorkspace() {
    api("/api/workspace").then(function (r) { return r.json(); }).then(function (w) {
      if (!w || !w.ok) return;
      $("wsName").textContent = w.repo || "unreal-agent";
      $("wsBranch").textContent = w.branch || "—";
      $("wsCommit").textContent = w.commit || "—";
      $("pvBranch").textContent = w.branch || "—";
      $("pvCommit").textContent = w.commit ? (w.commit + (w.dirty_count ? " · " + w.dirty_count + " dirty" : "")) : "—";
      $("pvProject").textContent = w.project || "—";
      $("pvVerified").textContent = w.last_verified_at ? String(w.last_verified_at).replace("T", " ").replace("Z", " UTC") : "—";
    }).catch(function () {});
  }

  /* ============================================================
     PREVIEW TAB
     ============================================================ */
  function updatePreview(s) {
    var versionEl = $("pvVersion"), healthEl = $("pvHealth");
    if (!versionEl) return;
    var version = s && s.version ? s.version : "—";
    versionEl.textContent = version;

    var backendOk = !!s;
    var bridge = s && s.unreal ? s.unreal : null;
    var bridgeOk = !!(bridge && bridge.ok);
    var ollama = s && s.ollama ? s.ollama : null;
    var ollamaOk = !!(ollama && ollama.ok);

    function row(el, ok, label, detail) {
      el.innerHTML = '<span class="dot ' + (ok ? "ok" : "off") + '"></span> ' + esc(label) +
        (detail ? ' <span style="color:var(--dim);font-size:10px;font-family:var(--mono)">' + esc(detail) + "</span>" : "");
      el.className = "val " + (ok ? "ok" : "down");
    }
    row($("pvBackend"), backendOk, backendOk ? "Healthy" : "Unavailable",
        backendOk ? "" : (s ? "no response" : "connection refused"));
    row($("pvBridge"), bridgeOk, bridgeOk ? "Ready" : "Unavailable",
        bridgeOk ? (bridge.engine || "") : (bridge && (bridge.error || bridge.message) ? String(bridge.error || bridge.message).slice(0, 60) : ""));
    row($("pvOllama"), ollamaOk, ollamaOk ? "Online" : "Unavailable",
        ollamaOk ? ((ollama.models || [])[0] || "") : (ollama && ollama.error ? String(ollama.error).slice(0, 60) : ""));

    var health = "down", healthText = "UNAVAILABLE";
    if (backendOk && bridgeOk && ollamaOk) { health = "ok"; healthText = "HEALTHY"; }
    else if (backendOk) { health = "degraded"; healthText = "DEGRADED"; }
    healthEl.className = "health " + health;
    healthEl.textContent = healthText;

    $("pvUpdated").textContent = stamp();
  }

  function refreshProof() {
    api("/api/proof/status").then(function (r) { return r.json(); }).then(function (p) {
      var img = $("pvProof"), meta = $("pvProofMeta");
      if (!img) return;
      if (p && p.ok && p.url) {
        state.proofUrl = API + p.url;
        img.src = state.proofUrl + "?t=" + Date.now();
        img.style.display = "block";
        meta.textContent = "Capture " + (p.size ? fmtSize(p.size) : "") + " · " + stamp();
      } else {
        img.style.display = "none";
        meta.textContent = "No viewport capture yet — run a task to generate proof.";
      }
    }).catch(function () {
      var img = $("pvProof");
      if (img) { img.style.display = "none"; $("pvProofMeta").textContent = "Proof unavailable — backend offline."; }
    });
  }

  /* ============================================================
     QUEUE TAB
     ============================================================ */
  var queueCache = null;
  function refreshQueue() {
    api("/api/events").then(function (r) { return r.json(); }).then(function (d) {
      queueCache = d && d.events ? d.events : [];
      if ($("tab-queue").classList.contains("hidden")) return;
      renderQueue(queueCache);
    }).catch(function () {});
  }

  function renderQueue(events) {
    var list = $("queueList"), meta = $("queueMeta");
    var byTask = {};
    events.forEach(function (e) {
      var tid = e.task_id;
      if (!tid) return;
      var t = byTask[tid] || (byTask[tid] = { id: tid, events: [] });
      t.events.push(e);
    });
    var rows = Object.keys(byTask).map(function (tid) { return byTask[tid]; });
    rows.sort(function (a, b) {
      var ta = (a.events[a.events.length - 1].timestamp || 0);
      var tb = (b.events[b.events.length - 1].timestamp || 0);
      return tb - ta;
    });
    meta.textContent = rows.length + " task(s)";
    if (!rows.length) {
      list.innerHTML = '<div class="empty-note">No tasks yet — submit a task from the chat.</div>';
      return;
    }
    var html = "";
    rows.slice(0, 12).forEach(function (t) {
      var evs = t.events;
      var first = evs.find(function (e) { return e.type === "user" || e.type === "planning"; });
      var title = "";
      if (first && first.detail) {
        if (typeof first.detail === "string") title = first.detail;
        else title = first.detail.message || first.detail.goal || "";
      }
      title = title || ("Task " + shortId(t.id));
      var last = evs[evs.length - 1];
      var stateName = "running";
      if (last && (last.type === "final" || last.type === "complete")) {
        stateName = (last.status === "failed" || last.status === "error") ? "failed" : "complete";
      } else if (last && last.status === "failed") {
        stateName = "failed";
      } else if (last && last.type === "user") {
        stateName = "running";
      }
      var planSteps = 0, doneSteps = 0;
      var planEv = evs.find(function (e) { return e.type === "planning" && e.detail && e.detail.steps; });
      if (planEv && planEv.detail.steps) planSteps = planEv.detail.steps.length;
      evs.forEach(function (e) {
        if (e.type === "tool_result" && e.status === "success") doneSteps++;
      });
      var pct = planSteps ? Math.min(100, Math.round((doneSteps / planSteps) * 100)) : 8;
      if (stateName === "complete" || stateName === "failed") pct = 100;
      var curStep = "";
      for (var i = evs.length - 1; i >= 0; i--) {
        if (evs[i].type === "tool" && evs[i].status === "running") { curStep = evs[i].title || evs[i].detail && evs[i].detail.step_id || ""; break; }
        if (evs[i].type === "tool_result") { curStep = (evs[i].title || "").replace(" finished", ""); break; }
      }
      html +=
        '<div class="queue-item fade-in">' +
        '<div class="q-title">' + esc(String(title).slice(0, 140)) + "</div>" +
        '<div class="q-meta"><span class="q-badge ' + stateName + '">' + stateName.toUpperCase() + "</span>" +
        '<span>' + shortId(t.id) + "</span>" +
        (curStep ? "<span>" + esc(String(curStep).slice(0, 60)) + "</span>" : "") +
        '<span>' + pct + "%</span></div>" +
        '<div class="q-progress"><i style="width:' + pct + '%"></i></div>' +
        "</div>";
    });
    list.innerHTML = html;
  }

  /* ============================================================
     CHANGES TAB
     ============================================================ */
  function refreshChanges() {
    api("/api/workspace/changes").then(function (r) { return r.json(); }).then(function (d) {
      var list = $("changesList"), meta = $("changesMeta");
      if (!list) return;
      if (!d || !d.ok) {
        list.innerHTML = '<div class="empty-note">Changes unavailable — git not reachable.</div>';
        return;
      }
      meta.textContent = d.count + " uncommitted change(s)";
      if (!d.changes.length) {
        list.innerHTML = '<div class="empty-note">Working tree clean — no uncommitted changes.</div>';
        return;
      }
      var html = "";
      d.changes.slice(0, 300).forEach(function (c) {
        html += '<div class="change-row fade-in">' +
          '<span class="c-badge ' + c.status.replace(/[^A-Za-z?]/g, "") + '">' + esc(c.status) + "</span>" +
          '<span class="c-path">' + esc(c.path) + "</span>" +
          '<span class="c-kind">' + esc(c.kind) + (c.staged ? " · staged" : "") + "</span></div>";
      });
      list.innerHTML = html;
    }).catch(function () {
      $("changesList").innerHTML = '<div class="empty-note">Changes unavailable — backend offline.</div>';
    });
  }

  /* ============================================================
     FILES TAB
     ============================================================ */
  function loadFiles(force) {
    if (state.filesLoaded && !force) { renderFiles($("filesSearch").value); return; }
    api("/api/workspace/files").then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok) {
        state.files = d.files || [];
        state.filesLoaded = true;
        $("filesMeta").textContent = state.files.length + " entries";
        renderFiles($("filesSearch").value);
      } else {
        $("filesList").innerHTML = '<div class="empty-note">File tree unavailable.</div>';
      }
    }).catch(function () {
      $("filesList").innerHTML = '<div class="empty-note">File tree unavailable — backend offline.</div>';
    });
  }

  function renderFiles(filter) {
    var list = $("filesList");
    filter = (filter || "").trim().toLowerCase();
    var files = state.files;
    if (!files || !files.length) {
      list.innerHTML = '<div class="empty-note">No files listed.</div>';
      return;
    }
    var html = "";
    var count = 0;
    files.forEach(function (f) {
      if (filter && f.path.toLowerCase().indexOf(filter) === -1) return;
      count++;
      if (count > 500) return;
      var icon = f.type === "dir" ? "▸" : "·";
      html += '<div class="file-row" data-path="' + esc(f.path) + '" title="Click to copy path">' +
        '<span class="f-icon">' + icon + "</span>" +
        '<span class="f-path">' + esc(f.path) + "</span>" +
        (f.type === "file" ? '<span class="f-size">' + fmtSize(f.size) + "</span>" : "") +
        "</div>";
    });
    if (!count) html = '<div class="empty-note">No files match the filter.</div>';
    list.innerHTML = html;
  }

  /* ============================================================
     TERMINAL TAB (live backend event log)
     ============================================================ */
  var termLines = 0;
  function renderTerminal(events) {
    var term = $("term");
    if (!term) return;
    var html = "";
    var evs = (events || []).slice(-400);
    evs.forEach(function (e) {
      var cls = "ok";
      if (e.status === "failed" || e.status === "error") cls = "err";
      else if (e.status === "warn" || e.status === "warning" || e.status === "paused") cls = "warn";
      else if (e.status !== "success" && e.status !== "info") cls = "";
      var type = String(e.type || e.event || "event");
      var detail = "";
      if (e.detail && typeof e.detail === "object") {
        try { detail = JSON.stringify(e.detail); if (detail.length > 160) detail = detail.slice(0, 160) + "…"; } catch (err) { detail = ""; }
      } else if (e.detail) detail = String(e.detail);
      if (e.title && detail.indexOf(e.title) === -1) detail = String(e.title) + (detail ? " " + detail : "");
      if (!detail && e.message) detail = String(e.message);
      html += '<div class="tl ' + cls + '"><span class="tt">' + stamp(new Date((e.timestamp || Date.now()) * 1000)) + "</span>" +
        "<span>" + esc(type) + (e.status ? "·" + esc(e.status) : "") + "</span>" +
        '<span class="tdetail">' + esc(detail).slice(0, 240) + "</span></div>";
    });
    term.innerHTML = html;
    termLines = evs.length;
    term.scrollTop = term.scrollHeight;
  }

  function refreshTerminal() {
    api("/api/events").then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.events) return;
      if ($("tab-terminal").classList.contains("hidden")) return;
      renderTerminal(d.events);
    }).catch(function () {});
  }

  /* ============================================================
     TABS
     ============================================================ */
  var activeTab = "preview";
  function setTab(name) {
    activeTab = name;
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle("active", tabs[i].dataset.tab === name);
    var bodies = ["preview", "queue", "changes", "files", "terminal"];
    bodies.forEach(function (b) {
      $("tab-" + b).classList.toggle("hidden", b !== name);
    });
    if (name === "queue") renderQueue(queueCache || []);
    if (name === "changes") refreshChanges();
    if (name === "files") loadFiles(false);
    if (name === "terminal") refreshTerminal();
    if (name === "preview") { refreshProof(); }
  }

  /* ============================================================
     DRAWERS (responsive)
     ============================================================ */
  function closeDrawers() {
    document.body.classList.remove("panel-open", "sidebar-open", "scrim-on");
  }
  function onResize() {
    if (window.innerWidth >= 1280) document.body.classList.remove("panel-open", "scrim-on");
    if (window.innerWidth >= 1024) document.body.classList.remove("sidebar-open", "scrim-on");
  }

  /* ============================================================
     CHAT — message rendering
     ============================================================ */
  function addMessage(role, opts) {
    opts = opts || {};
    var col = $("msgCol");
    $("emptyState").classList.add("hidden");

    var msg = document.createElement("div");
    msg.className = "msg " + role + " fade-in";
    msg.dataset.role = role;

    if (role === "system") {
      msg.innerHTML = '<div class="sys-note">' + esc(opts.text || "") + "</div>";
      col.appendChild(msg);
      scrollBottom();
      return msg;
    }

    var avatar = "";
    if (role === "assistant") {
      avatar = '<div class="msg-avatar">UA</div>';
    }
    var body = document.createElement("div");
    body.className = "msg-body";
    var headHtml = role === "user"
      ? '<div class="msg-head"><span class="msg-name">You</span><span class="msg-time">' + stamp() + "</span></div>"
      : '<div class="msg-head"><span class="msg-name">Unreal Agent</span><span class="ai-badge">AI</span><span class="msg-time">' + stamp() + "</span></div>";
    body.innerHTML = headHtml;

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    body.appendChild(bubble);

    var actions = document.createElement("div");
    actions.className = "msg-actions";
    actions.style.display = "none";
    body.appendChild(actions);

    msg.appendChild(avatar ? parse(avatar) : document.createTextNode(""));
    msg.appendChild(body);
    col.appendChild(msg);

    var handle = {
      el: msg,
      bubble: bubble,
      actions: actions,
      planEl: null,
      trailEl: null,
      stepMap: {},
      progressEl: null,
      runningEl: null,
      setText: function (text) {
        bubble.textContent = "";
        if (text) {
          var p = document.createElement("p");
          p.textContent = text;
          bubble.appendChild(p);
        }
      },
      addRunning: function (label) {
        if (this.runningEl) return;
        var row = document.createElement("div");
        row.className = "running-row";
        row.innerHTML = '<span class="typing"><i></i><i></i><i></i></span><span class="run-label"></span>';
        row.querySelector(".run-label").textContent = label || "Working";
        bubble.appendChild(row);
        this.runningEl = row;
        var track = document.createElement("div");
        track.className = "progress-track";
        track.innerHTML = '<div class="progress-fill indet"></div>';
        bubble.appendChild(track);
        this.progressEl = track.querySelector(".progress-fill");
      },
      setRunningLabel: function (label) {
        if (this.runningEl) this.runningEl.querySelector(".run-label").textContent = label;
      },
      setProgress: function (pct) {
        if (!this.progressEl) return;
        this.progressEl.classList.remove("indet");
        this.progressEl.style.width = Math.max(2, Math.min(100, pct)) + "%";
      },
      finishRunning: function () {
        if (this.runningEl) { this.runningEl.remove(); this.runningEl = null; }
        if (this.progressEl) { this.progressEl.remove(); this.progressEl = null; }
      },
      addPlan: function (steps) {
        if (this.planEl) { this.planEl.remove(); }
        var block = document.createElement("div");
        block.className = "plan-block";
        var goal = "";
        var html = '<div class="plan-title">Execution plan</div>';
        var list = [];
        steps.forEach(function (s, i) {
          var tool = s.preferred_tool || s.intent || ("step " + (i + 1));
          html += '<div class="plan-step" data-tool="' + esc(tool) + '"><span class="num">' + (i + 1) + '</span><span>' + esc(tool) + "</span></div>";
        });
        block.innerHTML = html;
        bubble.appendChild(block);
        this.planEl = block;
        var stepsEls = block.querySelectorAll(".plan-step");
        for (var i = 0; i < stepsEls.length; i++) {
          this.stepMap[stepsEls[i].dataset.tool] = stepsEls[i];
        }
      },
      markStep: function (tool, mode) {
        var el = this.stepMap[tool];
        if (!el) return;
        el.classList.remove("active", "done");
        if (mode === "done") el.classList.add("done");
        else el.classList.add("active");
      },
      addToolLine: function (cls, text) {
        if (!this.trailEl) {
          this.trailEl = document.createElement("div");
          this.trailEl.className = "tool-trail";
          bubble.appendChild(this.trailEl);
        }
        var line = document.createElement("div");
        line.className = "tline";
        line.innerHTML = '<span class="tstatus ' + (cls === "err" ? "err" : "") + '">' + (cls === "err" ? "✕" : "▸") + "</span><span>" + esc(text) + "</span>";
        this.trailEl.appendChild(line);
        while (this.trailEl.children.length > 60) this.trailEl.removeChild(this.trailEl.firstChild);
        scrollBottom();
      },
      showResult: function (ok, title, bodyText, taskId) {
        this.finishRunning();
        var card = document.createElement("div");
        card.className = "result-card " + (ok ? "ok" : "err");
        var rbody = esc(bodyText || "");
        try {
          var parsed = JSON.parse(bodyText);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && "verdict" in parsed) {
            var extra = Object.keys(parsed).filter(function (k) { return k !== "verdict"; });
            rbody = "Verdict: <b>" + esc(String(parsed.verdict)) + "</b>" +
              (extra.length ? "<br>" + esc(extra.map(function (k) { return k + ": " + parsed[k]; }).join(", ")) : "");
          }
        } catch (err) { /* keep raw body */ }
        var clamp = rbody.length > 900;
        card.innerHTML = '<div class="rtitle">' + esc(title) + "</div>" +
          '<div class="rbody' + (clamp ? " clamp" : "") + '">' + rbody + "</div>" +
          (clamp ? '<button class="more-btn">Show more</button>' : "");
        bubble.appendChild(card);
        if (clamp) {
          var more = card.querySelector(".more-btn");
          more.addEventListener("click", function () {
            var rb = card.querySelector(".rbody");
            var collapsed = rb.classList.contains("clamp");
            rb.classList.toggle("clamp");
            more.textContent = collapsed ? "Show less" : "Show more";
          });
        }
        // actions
        this.actions.style.display = "flex";
        var self = this;
        this.actions.innerHTML =
          '<button class="icon-btn" data-act="copy" title="Copy result">⧉</button>' +
          '<button class="icon-btn" data-act="up" title="Helpful">▲</button>' +
          '<button class="icon-btn" data-act="down" title="Not helpful">▼</button>' +
          '<div class="overflow-menu"><button class="icon-btn" data-act="menu" title="More">⋯</button>' +
          '<div class="menu-pop">' +
          '<button data-act="copy-id">Copy task ID</button>' +
          '<button data-act="copy-result">Copy result</button>' +
          '<button data-act="retry">Run again</button>' +
          "</div></div>";
        this.actions.addEventListener("click", function (ev) {
          var b = ev.target.closest("button");
          if (!b) return;
          var act = b.dataset.act;
          if (act === "copy") { copyText(bodyText, "Result copied"); }
          else if (act === "copy-id") { copyText(taskId || "", "Task ID copied"); }
          else if (act === "copy-result") { copyText(bodyText, "Result copied"); }
          else if (act === "retry") {
            var input = $("input");
            if (input && !state.running) { input.value = state.lastPrompt || ""; $("sendBtn").disabled = false; submit(); }
          }
          else if (act === "up" || act === "down") {
            var sib = b.parentElement.querySelectorAll(".icon-btn");
            for (var i = 0; i < sib.length; i++) sib[i].classList.remove("on");
            b.classList.add("on");
            toast(act === "up" ? "Marked helpful" : "Marked not helpful");
          }
          else if (act === "menu") {
            var menu = b.parentElement;
            var open = menu.classList.contains("open");
            document.querySelectorAll(".overflow-menu.open").forEach(function (m) { m.classList.remove("open"); });
            if (!open) menu.classList.add("open");
          }
        });
        scrollBottom();
      }
    };

    scrollBottom();
    return handle;
  }

  function parse(html) {
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    return tpl.content;
  }

  function scrollBottom() {
    var m = $("messages");
    if (reducedMotion) m.scrollTop = m.scrollHeight;
    else m.scrollTo({ top: m.scrollHeight, behavior: "smooth" });
  }

  /* ============================================================
     TASK FLOW
     ============================================================ */
  var STAGES = [
    { key: "understand", keys: ["understanding"], label: "Understanding" },
    { key: "plan", keys: ["planning", "planned", "plan_generated", "execution_plan"], label: "Planning" },
    { key: "edit", keys: ["editing", "dispatch", "tool", "step_started", "step_completed", "step_failed", "spawn", "create_blueprint", "set_"], label: "Editing" },
    { key: "build", keys: ["building", "compile", "save_level", "save"], label: "Building" },
    { key: "validate", keys: ["validating", "validation", "verify", "get_actor", "get_blueprint", "capture"], label: "Validating" },
    { key: "fix", keys: ["fixing", "fix", "retry", "replan"], label: "Fixing" },
    { key: "complete", keys: ["complete", "final", "done", "success"], label: "Complete" }
  ];
  var STAGE_ORDER = ["understand", "plan", "edit", "build", "validate", "fix", "complete"];

  var live = null; // current live assistant message handle

  function stageOf(e) {
    var t = String(e.type || e.event || "").toLowerCase();
    var title = String(e.title || "").toLowerCase();
    var tool = String((e.detail && e.detail.step_id) || (e.step && e.step.tool_name) || e.tool_name || (e.title || "").match(/^(?:Running|finished|failed)\s+([a-z0-9_]+)/i)?.[1] || "").toLowerCase();
    for (var i = 0; i < STAGES.length; i++) {
      for (var j = 0; j < STAGES[i].keys.length; j++) {
        if (t.indexOf(STAGES[i].keys[j]) !== -1) return STAGES[i].key;
      }
    }
    if (tool && (tool.indexOf("spawn") !== -1 || tool.indexOf("create") !== -1 || tool.indexOf("set_") !== -1 || tool.indexOf("delete") !== -1)) return "edit";
    if (tool && tool.indexOf("save") !== -1) return "build";
    if (tool && (tool.indexOf("get_") !== -1 || tool.indexOf("verify") !== -1 || tool.indexOf("list_") !== -1 || tool.indexOf("inspect") !== -1 || tool.indexOf("capture") !== -1)) return "validate";
    if (title.indexOf("compile") !== -1) return "build";
    return null;
  }

  var stageIndex = -1;
  function setStage(key) {
    var idx = STAGE_ORDER.indexOf(key);
    if (idx > stageIndex) stageIndex = idx;
    var label = STAGE_ORDER[idx] ? STAGE_ORDER[idx].charAt(0).toUpperCase() + STAGE_ORDER[idx].slice(1) : "";
    if (live) {
      live.setRunningLabel((STAGES[idx] ? STAGES[idx].label : key) + "…");
      if (stageIndex >= 0) live.setProgress(Math.round(((stageIndex + 1) / STAGE_ORDER.length) * 100));
    }
    return label;
  }

  function handleEvent(e) {
    if (!live) return;
    var tool = "";
    var titleMatch = String(e.title || "").match(/^(?:Running|finished|failed)\s+([a-z0-9_]+)/i);
    tool = titleMatch ? titleMatch[1] : (e.detail && e.detail.step_id) || e.tool_name || "";
    var st = stageOf(e);
    if (st) setStage(st);

    var type = String(e.type || e.event || "");

    if (type === "planning") {
      if (e.detail && e.detail.steps) live.addPlan(e.detail.steps);
      setStage("plan");
      return;
    }
    if (type === "tool" && e.status === "running") {
      if (tool) live.markStep(tool, "active");
      if (tool) live.addToolLine("", "running " + tool);
      return;
    }
    if (type === "tool_result") {
      var ok = e.status === "success" || (e.detail && e.detail.ok === true);
      if (tool) live.markStep(tool, ok ? "done" : "active");
      if (tool) live.addToolLine(ok ? "" : "err", (ok ? "ok " : "FAILED ") + tool + (e.detail && e.detail.error ? " — " + String(e.detail.error).slice(0, 90) : ""));
      return;
    }
    if (type === "final" || type === "complete") {
      var okFinal = !(e.status === "failed" || e.status === "error" || (e.detail && e.detail.ok === false));
      var detail = "";
      if (e.detail && typeof e.detail === "object") {
        detail = e.detail.summary || e.detail.message || JSON.stringify(e.detail);
      } else detail = e.detail || e.message || "";
      live.showResult(okFinal, okFinal ? "Task complete" : "Task failed", String(detail).slice(0, 6000), state.taskId);
      finishTask(okFinal);
      return;
    }
    if (type === "error") {
      var msg = (typeof e.detail === "string" ? e.detail : e.message) || "Execution error";
      live.addToolLine("err", "error " + msg);
      return;
    }
    // generic events → status line
    if (e.title && type !== "ping") {
      live.setRunningLabel(String(e.title).slice(0, 90));
    }
  }

  function finishTask(ok) {
    state.running = false;
    if (state.es) { state.es.close(); state.es = null; }
    state.taskId = null;
    updateSendState();
    refreshProof();
  }

  function streamTask(taskId) {
    if (state.es) state.es.close();
    var es = new EventSource(API + "/api/events/stream/" + encodeURIComponent(taskId));
    state.es = es;
    es.onmessage = function (msg) {
      var e;
      try { e = JSON.parse(msg.data); } catch (err) { return; }
      if (e && e.type === "ping") return;
      handleEvent(e || {});
    };
    es.onerror = function () {
      es.close();
      state.es = null;
      if (state.running) {
        // Stream dropped; fall back to status polling for terminal state.
        setTimeout(function () { pollTask(taskId); }, 1500);
      }
    };
  }

  function pollTask(taskId) {
    api("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      if (!state.running) return;
      if (s && !s.execution_active) {
        // Execution finished between polls; pull the latest events for the verdict.
        api("/api/events").then(function (r) { return r.json(); }).then(function (d) {
          var evs = (d.events || []).filter(function (e) { return e.task_id === taskId; });
          var finalEv = null;
          for (var i = evs.length - 1; i >= 0; i--) {
            if (evs[i].type === "final" || evs[i].type === "complete" || evs[i].status === "failed") { finalEv = evs[i]; break; }
          }
          if (finalEv) handleEvent(finalEv);
          else { live.showResult(false, "Task ended", "The task ended without a terminal event. Check the Terminal tab for the last steps.", taskId); finishTask(false); }
        });
      } else {
        setTimeout(function () { pollTask(taskId); }, 1800);
      }
    }).catch(function () {
      if (state.running) setTimeout(function () { pollTask(taskId); }, 2200);
    });
  }

  /* ---------------- submit ---------------- */
  function updateSendState() {
    var input = $("input");
    var empty = !input.value.trim();
    var off = !state.online;
    $("sendBtn").disabled = empty || state.running || off;
    $("sendBtn").textContent = state.running ? "Running…" : (state.mode === "plan" ? "Plan" : "Run");
  }

  function submit() {
    var input = $("input");
    var text = input.value.trim();
    if (!text || state.running || !state.online) return;
    state.lastPrompt = text;
    input.value = "";
    stageIndex = -1;

    var userMsg = addMessage("user", {});
    userMsg.setText(text);
    if (state.attached.length) {
      var ref = document.createElement("p");
      ref.style.cssText = "font-size:11px;color:var(--dim);margin-top:4px";
      ref.textContent = "Attached: " + state.attached.join(", ");
      userMsg.bubble.appendChild(ref);
    }

    var promptText = text;
    if (state.attached.length) {
      promptText += "\n\nReference files for the request: " + state.attached.map(function (f) { return f.name; }).join(", ");
    }

    live = addMessage("assistant", {});
    live.addRunning(state.mode === "plan" ? "Planning…" : "Starting…");
    live.setProgress(4);

    state.running = true;
    updateSendState();
    $("emptyState").classList.add("hidden");

    var context = { model: $("modelSel").value || "reasoning", reasoning: $("reasonSel").value };
    var action = state.mode === "plan" ? "plan" : "prompt";

    api("/api/action", {
      method: "POST",
      body: { action: action, payload: { message: promptText }, context: context }
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, json: j }; });
    }).then(function (res) {
      if (!res.ok) {
        var msg = (res.json && (res.json.detail || res.json.error)) || ("HTTP " + res.status);
        live.showResult(false, "Submission failed", String(msg), null);
        finishTask(false);
        return;
      }
      var j = res.json;
      var taskId = j.task_id || (j.data && j.data.task_id) || (j.data && j.data.id);
      if (taskId) {
        state.taskId = taskId;
        live.setRunningLabel("Task " + shortId(taskId) + " — agent working…");
        streamTask(taskId);
        return;
      }
      // Synchronous answer (plan / chat modes)
      var answer = (j.data && j.data.message) || j.message || j.answer || "";
      if (answer) {
        live.setRunningLabel("Done");
        live.finishRunning();
        live.setText(answer);
        // actions for copy
        live.actions.style.display = "flex";
        live.actions.innerHTML =
          '<button class="icon-btn" data-act="copy" title="Copy">⧉</button>' +
          '<div class="overflow-menu"><button class="icon-btn" data-act="menu" title="More">⋯</button>' +
          '<div class="menu-pop"><button data-act="copy-result">Copy</button></div></div>';
        live.actions.addEventListener("click", function (ev) {
          var b = ev.target.closest("button");
          if (!b) return;
          if (b.dataset.act === "copy" || b.dataset.act === "copy-result") copyText(answer, "Copied");
          else if (b.dataset.act === "menu") {
            var menu = b.parentElement;
            var open = menu.classList.contains("open");
            document.querySelectorAll(".overflow-menu.open").forEach(function (m) { m.classList.remove("open"); });
            if (!open) menu.classList.add("open");
          }
        });
        finishTask(true);
        return;
      }
      live.showResult(false, "Unexpected response", JSON.stringify(j).slice(0, 500), null);
      finishTask(false);
    }).catch(function (err) {
      live.showResult(false, "Submission failed", String(err.message || err), null);
      finishTask(false);
    });
  }

  /* ============================================================
     SIDEBAR
     ============================================================ */
  var AGENT_NOTES = {
    audio: "Audio Agent is not connected in this build. Only Unreal Agent is wired to the live backend.",
    assets: "Assets Agent is not connected in this build. Only Unreal Agent is wired to the live backend.",
    avlc: "AudioVidoLiving is the target project workspace; Unreal Agent drives it through the editor bridge.",
    ops: "Project Ops is not connected in this build. Only Unreal Agent is wired to the live backend."
  };
  function selectAgent(key) {
    state.agent = key;
    var buttons = document.querySelectorAll(".agent");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i].dataset.agent === key);
    }
    var names = { unreal: "Unreal Agent", audio: "Audio Agent", assets: "Assets Agent", avlc: "AudioVidoLiving", ops: "Project Ops" };
    $("chatAgentName").textContent = names[key] || "Unreal Agent";
    if (key !== "unreal" && AGENT_NOTES[key]) {
      addMessage("system", { text: AGENT_NOTES[key] });
      closeDrawers();
    }
  }

  /* ============================================================
     COMPOSER
     ============================================================ */
  function autoGrow() {
    var t = $("input");
    t.style.height = "auto";
    t.style.height = Math.min(180, Math.max(46, t.scrollHeight)) + "px";
  }

  function addAttachChips() {
    var wrap = $("attachChips");
    wrap.innerHTML = "";
    state.attached.forEach(function (f, idx) {
      var chip = document.createElement("span");
      chip.className = "attach-chip";
      chip.textContent = f.name;
      var rm = document.createElement("button");
      rm.textContent = "×";
      rm.title = "Remove";
      rm.addEventListener("click", function () {
        state.attached.splice(idx, 1);
        addAttachChips();
      });
      chip.appendChild(rm);
      wrap.appendChild(chip);
    });
  }

  /* ============================================================
     INIT
     ============================================================ */
  function init() {
    // tabs
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].addEventListener("click", function () { setTab(this.dataset.tab); });
    }
    // drawers
    $("panelBtn").addEventListener("click", function () {
      document.body.classList.toggle("panel-open");
      document.body.classList.toggle("scrim-on", document.body.classList.contains("panel-open"));
    });
    $("panelClose").addEventListener("click", closeDrawers);
    $("menuBtn").addEventListener("click", function () {
      document.body.classList.toggle("sidebar-open");
      document.body.classList.toggle("scrim-on", document.body.classList.contains("sidebar-open"));
    });
    $("scrim").addEventListener("click", closeDrawers);
    window.addEventListener("resize", onResize);

    // sidebar
    var agentBtns = document.querySelectorAll(".agent");
    for (var i = 0; i < agentBtns.length; i++) {
      agentBtns[i].addEventListener("click", function () { selectAgent(this.dataset.agent); });
    }
    $("addAgent").addEventListener("click", function () {
      var name = window.prompt("New agent workspace name", "");
      if (!name) return;
      var list = $("agentList");
      var b = document.createElement("button");
      b.className = "agent";
      b.dataset.agent = "custom-" + name;
      b.innerHTML = '<span class="dot off"></span><span class="name">' + esc(name) + '</span><span class="state">offline</span>';
      b.addEventListener("click", function () {
        selectAgent("unreal");
        addMessage("system", { text: esc(name) + " is not connected in this build — register its backend to make it available." });
      });
      list.insertBefore(b, $("addAgent"));
      toast("Agent workspace added (offline)");
    });
    $("devLink").addEventListener("click", function () { window.open(API + "/static/devboard.html", "_blank"); });

    // composer
    $("modeBuild").addEventListener("click", function () { setMode("build"); });
    $("modePlan").addEventListener("click", function () { setMode("plan"); });
    $("modelSel").addEventListener("change", function () { localStorage.setItem("ua_model", this.value); });
    $("reasonSel").addEventListener("change", function () { localStorage.setItem("ua_reasoning", this.value); });
    $("sendBtn").addEventListener("click", submit);
    $("input").addEventListener("input", function () { autoGrow(); updateSendState(); });
    $("input").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        if (!$("sendBtn").disabled) submit();
      }
    });
    $("attachBtn").addEventListener("click", function () { $("fileInput").click(); });
    $("fileInput").addEventListener("change", function () {
      var files = Array.prototype.slice.call(this.files || []);
      files.forEach(function (f) { state.attached.push({ name: f.name, size: f.size }); });
      this.value = "";
      addAttachChips();
      toast(files.length + " file reference(s) attached");
    });

    // empty-state chips
    var chips = document.querySelectorAll(".chip");
    for (var i = 0; i < chips.length; i++) {
      chips[i].addEventListener("click", function () {
        $("input").value = this.textContent;
        autoGrow();
        updateSendState();
        $("input").focus();
      });
    }

    // preview controls
    $("pvLaunch").addEventListener("click", function () {
      if (state.proofUrl) window.open(state.proofUrl, "_blank");
      else toast("No viewport capture yet — run a task first.");
    });
    $("pvOpen").addEventListener("click", function () { window.open(API + "/", "_blank"); });
    $("pvRefresh").addEventListener("click", function () { refreshStatus(); refreshProof(); toast("Status refreshed"); });
    $("pvAuto").addEventListener("change", function () { localStorage.setItem("ua_pvauto", this.checked ? "1" : "0"); });

    // files search
    $("filesSearch").addEventListener("input", function () { renderFiles(this.value); });
    $("filesList").addEventListener("click", function (ev) {
      var row = ev.target.closest(".file-row");
      if (row) { copyText(row.dataset.path, "Path copied"); }
    });

    // terminal
    $("termClear").addEventListener("click", function () {
      $("term").innerHTML = "";
      termLines = 0;
    });
    document.addEventListener("click", function (ev) {
      if (!ev.target.closest(".overflow-menu")) {
        document.querySelectorAll(".overflow-menu.open").forEach(function (m) { m.classList.remove("open"); });
      }
    });

    // boot
    var savedMode = localStorage.getItem("ua_mode");
    setMode(savedMode === "plan" ? "plan" : "build");
    var savedReason = localStorage.getItem("ua_reasoning");
    if (savedReason) $("reasonSel").value = savedReason;
    var savedAuto = localStorage.getItem("ua_pvauto");
    if (savedAuto === "0") $("pvAuto").checked = false;

    refreshStatus();
    refreshWorkspace();
    refreshProof();
    refreshQueue();
    refreshTerminal();
    setInterval(function () {
      refreshStatus();
      refreshTerminal();
    }, 5000);
    setInterval(function () {
      if ($("pvAuto").checked) refreshProof();
    }, 15000);
  }

  function setMode(mode) {
    state.mode = mode;
    $("modeBuild").classList.toggle("active", mode === "build");
    $("modePlan").classList.toggle("active", mode === "plan");
    localStorage.setItem("ua_mode", mode);
    updateSendState();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
