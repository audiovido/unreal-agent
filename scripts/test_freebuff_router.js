// Standalone harness for scripts/freebuff_unreal_router.js
// Runs the REAL flow: POST /api/action -> task_id -> SSE stream -> terminal.
// Usage: <bundled-bun> scripts/test_freebuff_router.js "<message>"
const router = await import("./freebuff_unreal_router.js");

const message =
  process.argv[2] ||
  "Create a visible test actor named FREEBUFF_API_ROUTING_TEST in the current Unreal level, save it, verify it exists, and capture proof.";

const collected = [];
function emit(ev) {
  collected.push(ev);
  if (ev.type === "text") {
    process.stdout.write(ev.text.replace(/\n{3,}/g, "\n\n"));
    process.stdout.write("\n");
  } else {
    process.stdout.write(`[${ev.type}] ${JSON.stringify(ev).slice(0, 200)}\n`);
  }
}

const status = await router.fbUnrealStatus(4000);
console.log("\n== BACKEND STATUS ==");
console.log(JSON.stringify(status, null, 2).slice(0, 800));

if (!status.ok) {
  console.error("Backend down — aborting harness (recovery is exercised by the turn runner).");
  process.exit(2);
}

console.log("\n== SUBMITTING ==");
const aborter = new AbortController();
const taskId = await router.fbSubmitUnrealPrompt(message, emit, aborter.signal);
if (!taskId) {
  console.error("No task_id returned.");
  process.exit(3);
}
console.log("task_id:", taskId);

console.log("\n== STREAMING EVENTS ==");
const streamed = await router.fbStreamUnrealTask(taskId, emit, aborter.signal);

console.log("\n== RESULT ==");
console.log(JSON.stringify(
  { terminal: streamed.terminal ? { kind: streamed.terminal.kind } : null, error: streamed.error, tools: streamed.state && streamed.state.tools },
  null,
  2
));
process.exit(streamed.terminal ? 0 : 1);
