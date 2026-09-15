// Ava widget contract — executable contract (node tests/test_widget_contract.js)
"use strict";
const assert = require("assert");
const W = require("../ui/ava_widget.js");

// --- event() ---------------------------------------------------------------
const eventCases = [
  // type, payload, expected type, payload pass-through?
  ["ready", { online: true }, "ava:ready", true],
  ["reply", { text: "hi", mode: "chat" }, "ava:reply", true],
  ["typing", { state: "start" }, "ava:typing", true],
  ["typing", { state: "end" }, "ava:typing", true],
  ["height", { height: 480 }, "ava:height", true],
  ["speaking", { state: "skip", reason: "unavailable" }, "ava:speaking", true],
  ["error", { text: "boom" }, "ava:error", true],
  ["cleared", {}, "ava:cleared", true],
  ["ready", undefined, "ava:ready", false], // payload defaults to {}
  ["unknown", {}, null, false],
  ["REPLY", {}, null, false], // type is case-sensitive
];
for (const [type, payload, expectedType, passesPayload] of eventCases) {
  const e = W.event(type, payload);
  assert.strictEqual(e ? e.type : null, expectedType, `event(${type}) type`);
  if (e) {
    assert.ok(Number.isInteger(e.ts), `event(${type}) ts`);
    if (passesPayload) assert.strictEqual(e.payload, payload, `event(${type}) payload`);
    else assert.deepStrictEqual(e.payload, {}, `event(${type}) default payload`);
  }
}

// --- parseCommand() ----------------------------------------------------------
const commandCases = [
  // label, input, expected command or null
  ["send valid", { type: "ava:command", command: "send", message: "hello" }, { command: "send", message: "hello" }],
  ["send trims check", { type: "ava:command", command: "send", message: "  hi  " }, { command: "send", message: "  hi  " }],
  ["send empty message", { type: "ava:command", command: "send", message: "" }, null],
  ["send blank message", { type: "ava:command", command: "send", message: "   " }, null],
  ["send missing message", { type: "ava:command", command: "send" }, null],
  ["send non-string message", { type: "ava:command", command: "send", message: 42 }, null],
  ["clear valid", { type: "ava:command", command: "clear" }, { command: "clear" }],
  ["focus valid", { type: "ava:command", command: "focus" }, { command: "focus" }],
  ["wrong type", { type: "ava:event", command: "clear" }, null],
  ["unknown command", { type: "ava:command", command: "explode" }, null],
  ["non-object", "ava:command", null],
  ["null", null, null],
  ["array", [{ type: "ava:command", command: "clear" }], null],
];
for (const [label, input, expected] of commandCases) {
  const got = W.parseCommand(input);
  if (expected === null) assert.strictEqual(got, null, `parseCommand: ${label}`);
  else assert.deepStrictEqual(got, expected, `parseCommand: ${label}`);
}

console.log("widget contract: PASS (" + (eventCases.length + commandCases.length) + " cases)");