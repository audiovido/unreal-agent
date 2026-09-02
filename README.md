# Unreal Agent

Local autonomous AI agent specialized exclusively for Unreal Engine.

Core goals:
- Control and inspect Unreal Engine projects
- C++ development
- Blueprint assistance and automation
- UMG / UI creation
- Level and gameplay development
- Asset and project management
- Automated testing and debugging
- Local LLM integration
- Persistent project memory
- Planning, execution, verification and recovery

# Reusable Chat UI (embedding)

The Ava Chat is a self-contained web app served by the backend at `http://127.0.0.1:8765/`
(HTML `ui/ava.html`, static assets under `/static/`, all data via same-origin `/api/*`).
It is iframe-embeddable in other apps: no frame-busting, no `X-Frame-Options`,
and the backend allows cross-origin (`CORS allow_origins=["*"]`).

Embedding contract:

- `<iframe src="http://127.0.0.1:8765/?embed=1">` — `embed=1` hides the product
  top bar (brand/status) and keeps the composer, message list, MetaHuman PiP
  and speech chip fully functional.
- Core endpoints the page uses: `GET /api/status` (health), `POST /api/chat`
  (`{message}` → user-facing reply), `POST /api/chat/speak` (fire-and-forget,
  single-flight MetaHuman speech; truthfully reports `skipped_unavailable`
  when AvaLive is offline), `GET /api/chat/speak/status`, and AvaLive-scoped
  `GET /api/proof/live` (+ `/api/proof/live/status`) for the viewport PiP.
- Conversation prompts return real assistant replies; only genuinely
  execute-classified tasks run the agent executor, and structured failure
  codes are humanized client-side before display.

Portrait/mobile is validated at ≤439px; desktop at 1440×900 / 1024×768.

# Backend structure (app/)

- `app/api.py` — the FastAPI app object (`api.app`) and the main executor/workboard
  API. `app/served:app` is the uvicorn entry (`run_agent.py`); it re-exports
  `api.app` and is the composition root.
- `app/served.py` — thin router/composition layer: registers routes for the
  extracted modules and owns the executor guard/deadlock-breaker wiring.
- `app/proof.py` — viewport-capture discovery (`_proof_files`) + the four
  `/api/proof/*` handlers; default project file injected via `setup()`.
- `app/speak.py` — chat auto-speak single-flight runner. State ownership:
  `_speak_state` owns active/pid only; the run RESULT is owned by the gate
  subprocess log (`scripts/chat_speak_last.log`), read live by the status
  endpoint (one source of truth).
- `app/workboard_api.py` — workboard-specific API surface.

Rule for later passes: new endpoint logic goes in a module (like proof.py/
speak.py) that owns its state; served.py only registers routes and wires config.

# Ava widget host contract (postMessage)

`/?widget=1` is the host-panel variant: it hides the top bar AND the hero orb so
the chat fills the host iframe (desktop and portrait). The contract helpers
(`event`, `parseCommand`) live in `ui/ava_widget.js` and are node-testable
(`node tests/test_widget_contract.js`). A same-origin reference host is served
at `/static/widget_harness.html` (logs the event stream, drives the widget).

Widget → host events (`iframe.contentWindow` posts to `parent`, target `*`):

| type | payload | fired when |
|---|---|---|
| `ava:ready` | `{ online }` | first status poll completes |
| `ava:typing` | `{ state: "start"\|"end" }` | a reply starts loading/thinking (`start`) and when it renders or fails (`end`) |
| `ava:height` | `{ height }` | widget's needed px height on load, resize, and content change (hosts size the iframe from the latest value) |
| `ava:reply` | `{ text, mode: "chat"\|"task" }` | an assistant reply finishes |
| `ava:speaking` | `{ state: "start"\|"skip"\|"done"\|"error", reason? }` | auto-speak starts / skips (`active`\|`unavailable`) / finishes / fails |
| `ava:error` | `{ text }` | a task fails (text is already humanized) |
| `ava:cleared` | `{}` | the host `clear` command completed |

Origin filtering (host side): the widget accepts `ava:command` messages from
any origin and posts events with target `*`, which is fine for a local tool but
should be restricted when embedding across hosts — verify `event.origin` on the
host before trusting an `ava:*` event, and only send commands to iframes you
created:

```js
window.addEventListener("message", (ev) => {
  if (ev.origin !== "http://127.0.0.1:8765") return;       // events from the widget
  if (!ev.data || !ev.data.type || ev.data.type.indexOf("ava:") !== 0) return;
  // …handle ava:* events…
});
const iframe = document.getElementById("ava");             // iframe you created
iframe.contentWindow.postMessage({ type: "ava:command", command: "send", message: "Hi" }, "*");
```

Host → widget commands (`parent` posts to the iframe you created, target `*`):

| command | payload | effect |
|---|---|---|
| `send` | `{ message }` | sends the message through the normal chat path (offline/busy → `ava:error`) |
| `clear` | — | empties the conversation, resets state, emits `ava:cleared` |
| `focus` | — | focuses the composer |

Example (host page):

```html
<iframe src="http://127.0.0.1:8765/?widget=1" id="ava"></iframe>
<script>
  window.addEventListener("message", (ev) => {
    if (ev.data && ev.data.type === "ava:reply") console.log(ev.data.payload.text);
    if (ev.data && ev.data.type === "ava:speaking" && ev.data.payload.state === "skip")
      console.log("speech skipped:", ev.data.payload.reason);
  });
  document.getElementById("ava").contentWindow.postMessage(
    { type: "ava:command", command: "send", message: "Hello" }, "*");
</script>
```
