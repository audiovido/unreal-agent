/* ============================================================
   Ava widget contract — host <-> widget postMessage bridge.
   Pure helpers, no DOM. Load before ava.js in ava.html; hosts
   can require() this file directly in Node for validation.
   ------------------------------------------------------------
   Widget -> host events (window.parent.postMessage, '*'):
     { type: "ava:ready",    payload: { online } }
     { type: "ava:reply",    payload: { text, mode: "chat"|"task" } }
     { type: "ava:speaking", payload: { state: "start"|"skip"|"done"|"error", reason? } }
     { type: "ava:error",    payload: { text } }
     { type: "ava:cleared",  payload: {} }
   Host -> widget commands (postMessage to the iframe):
     { type: "ava:command", command: "send",  message: "…" }
     { type: "ava:command", command: "clear" }
     { type: "ava:command", command: "focus" }
   ============================================================ */
(function () {
  "use strict";

  var EVENT_TYPES = { ready: 1, reply: 1, typing: 1, height: 1, speaking: 1, error: 1, cleared: 1 };
  var COMMANDS = { send: 1, clear: 1, focus: 1 };

  function event(type, payload) {
    if (!EVENT_TYPES[type]) return null;
    return { type: "ava:" + type, payload: payload || {}, ts: Date.now() };
  }

  function parseCommand(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    if (data.type !== "ava:command") return null;
    var c = data.command;
    if (!COMMANDS[c]) return null;
    var out = { command: c };
    if (c === "send") {
      if (typeof data.message !== "string" || !data.message.trim()) return null;
      out.message = data.message;
    }
    return out;
  }

  var api = { EVENT_TYPES: EVENT_TYPES, COMMANDS: COMMANDS, event: event, parseCommand: parseCommand };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else if (typeof window !== "undefined") window.AVAWidget = api;
})();