/* Runtime tests for static/js/state.js — the scan lifecycle and error surface.
 *
 * No DOM required: state.js is deliberately pure, so the whole orchestration
 * contract can be checked in plain Node.
 *
 * Run: node tests/js/state.test.mjs
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "../../static/js/state.js"), "utf8");

// state.js assigns to window.KathaPulseState
globalThis.window = globalThis;
new Function("window", source)(globalThis);

const S = globalThis.KathaPulseState;
assert.ok(S, "state.js did not expose window.KathaPulseState");

const results = [];
function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, detail: err.message });
  }
}

// ---------------------------------------------------------------------------
// Happy path — the exact sequence app.js emits
// ---------------------------------------------------------------------------

test("full happy path reaches speaking then idle", () => {
  let st = S.create();
  assert.equal(st.name, "idle");

  st = S.transition(st, "CAMERA_OPENED");
  assert.equal(st.name, "camera_ready");

  st = S.transition(st, "CAPTURE_START");
  assert.equal(st.name, "capturing");
  assert.equal(S.isBusy(st), true);

  st = S.transition(st, "CAPTURE_DONE");
  assert.equal(st.name, "scrubbing");

  st = S.transition(st, "SCRUB_DONE");
  assert.equal(st.name, "uploading");
  assert.equal(S.stepIndex(st), 1);

  st = S.transition(st, "UPLOAD_OK");
  assert.equal(st.name, "rendering");
  assert.equal(S.isBusy(st), false);

  st = S.transition(st, "SPEECH_START");
  assert.equal(st.name, "speaking");

  st = S.transition(st, "SPEECH_END");
  assert.equal(st.name, "idle");
});

test("gallery path skips the camera entirely", () => {
  let st = S.create();
  st = S.transition(st, "FILE_SELECTED");
  assert.equal(st.name, "scrubbing");
  st = S.transition(st, "SCRUB_DONE");
  st = S.transition(st, "UPLOAD_OK");
  assert.equal(st.name, "rendering");
});

// ---------------------------------------------------------------------------
// Guard rails
// ---------------------------------------------------------------------------

test("unknown events are ignored, never crash", () => {
  let st = S.create();
  st = S.transition(st, "NOT_A_REAL_EVENT");
  assert.equal(st.name, "idle");
  assert.equal(st.lastEvent, "NOT_A_REAL_EVENT");
});

test("out-of-order events cannot skip ahead", () => {
  let st = S.create();
  st = S.transition(st, "UPLOAD_OK"); // nothing uploaded yet
  assert.equal(st.name, "idle");
});

test("transitions do not mutate the previous state", () => {
  const first = S.create();
  const second = S.transition(first, "FILE_SELECTED");
  assert.equal(first.name, "idle");
  assert.equal(second.name, "scrubbing");
});

test("camera permission failure reaches the error screen", () => {
  const st = S.transition(S.create(), "CAMERA_FAILED", { code: "camera_denied" });
  assert.equal(st.name, "error");
  assert.equal(st.error.code, "camera_denied");
});

test("reset always returns to idle from a busy state", () => {
  let st = S.transition(S.create(), "FILE_SELECTED");
  st = S.transition(st, "RESET");
  assert.equal(st.name, "idle");
});

test("busy states disable actions", () => {
  ["capturing", "scrubbing", "uploading"].forEach((name) => {
    assert.equal(S.isBusy({ name }), true, name + " should be busy");
  });
  ["idle", "rendering", "speaking", "error"].forEach((name) => {
    assert.equal(S.isBusy({ name }), false, name + " should not be busy");
  });
});

// ---------------------------------------------------------------------------
// Failure paths
// ---------------------------------------------------------------------------

test("upload failure lands in error and records the code", () => {
  let st = S.transition(S.create(), "FILE_SELECTED");
  st = S.transition(st, "SCRUB_DONE");
  st = S.transition(st, "UPLOAD_FAIL", { code: "timeout" });
  assert.equal(st.name, "error");
  assert.equal(st.error.code, "timeout");
});

test("retry leaves the error state", () => {
  let st = S.transition(S.create(), "FILE_SELECTED");
  st = S.transition(st, "SCRUB_DONE");
  st = S.transition(st, "UPLOAD_FAIL", { code: "server" });
  assert.equal(st.name, "error");
  st = S.transition(st, "RETRY");
  assert.equal(st.name, "idle");
  assert.equal(st.error, null);
});

test("retry is repeatable across successive failures", () => {
  let st = S.create();
  const codes = ["image_failed", "network", "timeout", "bad_request"];

  for (const code of codes) {
    st = S.transition(st, "FILE_SELECTED");
    st = S.transition(st, "SCRUB_DONE");
    st = S.transition(st, "UPLOAD_FAIL", { code });
    assert.equal(st.name, "error", "after " + code);

    st = S.transition(st, "RETRY");
    assert.equal(st.name, "idle", "retry after " + code);
    assert.equal(st.error, null);
  }

  // ...and the same machine can still complete a scan afterwards.
  st = S.transition(st, "FILE_SELECTED");
  st = S.transition(st, "SCRUB_DONE");
  st = S.transition(st, "UPLOAD_OK");
  assert.equal(st.name, "rendering");
});

test("a failure outside uploading still reaches FATAL from any state", () => {
  // Mirrors app.js: a failure event with no path falls through to FATAL.
  const from = ["idle", "camera_ready", "rendering", "speaking"];
  for (const name of from) {
    let st = S.transition({ name, error: null }, "UPLOAD_FAIL", { code: "network" });
    if (st.name !== "error") st = S.transition(st, "FATAL", { code: "network" });
    assert.equal(st.name, "error", "failure from " + name);
  }
});

test("FATAL reaches the error screen from every state", () => {
  for (const name of Object.values(S.STATES)) {
    const st = S.transition({ name, error: null }, "FATAL", { code: "unknown" });
    assert.equal(st.name, "error", "FATAL from " + name);
  }
});

// ---------------------------------------------------------------------------
// Error classification
// ---------------------------------------------------------------------------

test("classifies the errors the browser actually throws", () => {
  const abort = new Error("aborted");
  abort.name = "AbortError";
  assert.equal(S.classifyError(abort, { online: true }), "timeout");

  const net = new TypeError("Failed to fetch");
  assert.equal(S.classifyError(net, { online: true }), "network");
  assert.equal(S.classifyError(net, { online: false }), "offline");

  const big = new Error("too big");
  big.status = 413;
  assert.equal(S.classifyError(big, { online: true }), "too_large");

  const typed = new Error("bad type");
  typed.status = 415;
  assert.equal(S.classifyError(typed, { online: true }), "bad_type");

  const bad = new Error("bad request");
  bad.status = 422;
  assert.equal(S.classifyError(bad, { online: true }), "bad_request");

  const server = new Error("boom");
  server.status = 503;
  assert.equal(S.classifyError(server, { online: true }), "server");

  assert.equal(S.classifyError(new Error("?"), { online: true }), "unknown");
});

test("offline wins over an HTTP status — the phone knows better", () => {
  const server = new Error("boom");
  server.status = 500;
  assert.equal(S.classifyError(server, { online: false }), "offline");
});

// ---------------------------------------------------------------------------
// Localisation of the fallback copy (Inspector: clear ml/hi fallback text)
// ---------------------------------------------------------------------------

test("every error code has Malayalam, Hindi and English copy", () => {
  for (const [code, entry] of Object.entries(S.ERROR_COPY)) {
    for (const lang of ["ml", "hi", "en"]) {
      assert.ok(entry[lang] && entry[lang].length > 10, `${code}.${lang} missing`);
    }
    assert.ok(/[\u0d00-\u0d7f]/.test(entry.ml), `${code}.ml is not Malayalam script`);
    assert.ok(/[\u0900-\u097f]/.test(entry.hi), `${code}.hi is not Devanagari script`);
  }
});

test("errorCopy never returns undefined for an unknown code", () => {
  const text = S.errorCopy("does-not-exist", "ml");
  assert.ok(text && text.length > 0);
});

test("retry label is localised for all three languages", () => {
  for (const lang of ["ml", "hi", "en"]) {
    assert.ok(S.RETRY_COPY[lang], "missing retry label for " + lang);
  }
});

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

console.log("\nState machine — runtime checks");
for (const { name, ok, detail } of results) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed\n`);
if (failed) process.exit(1);
