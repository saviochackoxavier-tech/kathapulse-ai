/* Live preset integration test — the three one-click demo buttons, end to end.
 *
 * This is the suite that answers "does the demo actually work?", so it is the
 * one place where stubbing the network would defeat the point:
 *
 *   1. POST each preset's names to the running FastAPI app and record the real
 *      payload (verdict, findings, Malayalam and Hindi speech scripts).
 *   2. Boot static/index.html in jsdom with the same state.js/app.js the
 *      browser runs, click the `data-demo` button, and assert what the user
 *      would see: the right card colour, localised copy, medicine chips and the
 *      exact text handed to Web Speech.
 *
 * The transport is stubbed only for the DOM half, because jsdom's
 * AbortController signal is not accepted by Node's fetch — the payloads are the
 * ones the live server just returned, so the rendering path is still real.
 *
 * Requires the server:   ./scripts/serve.sh
 * Run:                   node presets.test.mjs        (from tests/js)
 * Against another host:  KATHA_BASE_URL=http://127.0.0.1:8000 node presets.test.mjs
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const BASE = (process.env.KATHA_BASE_URL || "http://127.0.0.1:3004").replace(/\/$/, "");
const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(HERE, "../../static");
const read = (p) => readFileSync(join(STATIC_DIR, p), "utf8");

const MALAYALAM = /[\u0d00-\u0d7f]/;
const DEVANAGARI = /[\u0900-\u097f]/;
const flush = (ms = 300) => new Promise((resolve) => setTimeout(resolve, ms));

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, detail: err.message });
  }
}

//: id -> names, mirroring DEMO_PRESETS in app.js and the buttons in index.html.
const PRESETS = {
  "dup-lasa": ["Telma 40", "Telma-H 40/12.5"],
  "dup-para": ["Dolo 650", "Crocin Cold & Flu"],
  "lasa-alone": ["Amaryl 1 mg"],
};

//: What each preset must produce, as a clinical contract (not just "a card").
const EXPECTED = {
  "dup-lasa": { verdict: "critical", codes: ["DUPLICATE_SALT", "LASA_RISK"], minFindings: 2 },
  "dup-para": { verdict: "critical", codes: ["DUPLICATE_SALT"], minFindings: 1 },
  "lasa-alone": { verdict: "caution", codes: ["LASA_RISK"], minFindings: 1 },
};

const label = (names) => names.join("|");

async function postScan(names) {
  const response = await fetch(`${BASE}/verify-medicines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ medicines: names.map((name) => ({ name })), language: "ml" }),
    signal: AbortSignal.timeout(10000),
  });
  assert.equal(response.status, 200, `HTTP ${response.status} for ${label(names)}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// 1. The live server returns the clinical contract for every preset
// ---------------------------------------------------------------------------

let payloads = {};
const timings = {};

try {
  const health = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(3000) });
  assert.equal(health.ok, true, `GET /health -> ${health.status}`);
} catch (err) {
  console.error(
    `\nCannot reach the KathaPulse server at ${BASE} (${err.message}).\n` +
      "Start it first:   ./scripts/serve.sh\n" +
      "Or point elsewhere: KATHA_BASE_URL=http://127.0.0.1:8000 node presets.test.mjs\n"
  );
  process.exit(1);
}

for (const [id, names] of Object.entries(PRESETS)) {
  const started = performance.now();
  payloads[label(names)] = await postScan(names);
  timings[id] = Math.round(performance.now() - started);
}
// One unreadable name, to prove the engine refuses to guess.
payloads["Zzqx 999"] = await postScan(["Zzqx 999"]);

for (const [id, names] of Object.entries(PRESETS)) {
  await test(`API contract: ${id} -> ${EXPECTED[id].verdict} ${EXPECTED[id].codes.join("+")}`, () => {
    const payload = payloads[label(names)];
    assert.equal(payload.safety.verdict, EXPECTED[id].verdict, "wrong verdict");
    assert.deepEqual(
      payload.safety.findings.map((f) => f.code),
      EXPECTED[id].codes,
      "wrong finding set"
    );
    assert.equal(payload.processed_in_memory, true, "response does not declare RAM-only processing");
    assert.match(payload.safety_message_ml || "", MALAYALAM, "no Malayalam speech script");
    assert.match(payload.safety_message_hi || "", DEVANAGARI, "no Hindi speech script");
    assert.ok(timings[id] < 2000, `preset took ${timings[id]} ms — demo would not feel instant`);
  });
}

await test("API contract: an unknown name is never invented into a medicine", () => {
  const payload = payloads["Zzqx 999"];
  assert.equal(payload.safety.verdict, "unknown", "unknown name produced a confident verdict");
  assert.equal(payload.medicines.every((m) => !m.matched), true, "an unidentified strip was matched");
});

// ---------------------------------------------------------------------------
// 2. Clicking the buttons renders the cards and hands text to Web Speech
// ---------------------------------------------------------------------------

function boot() {
  const dom = new JSDOM(read("index.html"), {
    url: `${BASE}/`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.Element.prototype.scrollIntoView = function () {};

  // Serve the payloads captured from the live server, keyed by the scan asked for.
  window.fetch = async (url, options) => {
    const key = JSON.parse(options.body)
      .medicines.map((m) => m.name)
      .join("|");
    const payload = payloads[key];
    if (!payload) throw new window.Error(`unexpected scan: ${key}`);
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(payload)) };
  };

  // Camera/canvas are irrelevant to a preset: no strip is photographed.
  window.KathaPulseCapture = {
    startCamera: async () => {},
    stopCamera: () => {},
    isRunning: () => false,
    showPreview: () => {},
    grabFrame: async () => null,
    scrubFile: async () => null,
    getLast: () => null,
  };

  // Speech is recorded instead of spoken: this asserts the handoff, not audio.
  const spoken = [];
  window.KathaPulseSpeech = {
    isSupported: () => true,
    hasVoiceFor: () => true,
    speak: async (text, lang) => {
      spoken.push({ text, lang });
      return { ok: true };
    },
    stop: () => {},
    isSpeaking: () => false,
  };

  window.eval(read("js/state.js"));
  window.eval(read("js/app.js"));

  return { window, doc: window.document, spoken };
}

for (const [id, names] of Object.entries(PRESETS)) {
  const mlWord = EXPECTED[id].verdict === "critical" ? /അപകടം/ : /ശ്രദ്ധിക്കുക/;

  await test(`preset ${id}: click renders a ${EXPECTED[id].verdict} card and speaks Malayalam`, async () => {
    const { doc, spoken } = boot();
    const button = doc.querySelector(`[data-demo="${id}"]`);
    assert.ok(button, `no [data-demo="${id}"] button in index.html`);

    button.click();
    await flush();

    assert.equal(doc.getElementById("error-card").hidden, true, "error card shown");
    assert.equal(doc.getElementById("result").hidden, false, "result panel hidden");
    assert.equal(doc.getElementById("steps").hidden, true, "stepper left running");
    assert.match(doc.getElementById("verdict").className, new RegExp(EXPECTED[id].verdict), "wrong card colour");
    assert.match(doc.getElementById("verdict-label").textContent, mlWord, "verdict label is not Malayalam");

    const findings = doc.querySelectorAll("#findings li.finding");
    assert.ok(findings.length >= EXPECTED[id].minFindings, `rendered ${findings.length} findings`);
    assert.match(findings[0].textContent, MALAYALAM, "finding text is not Malayalam");
    assert.ok(doc.querySelectorAll("#matched-list li").length >= 1, "no medicine chips rendered");
    assert.ok(doc.getElementById("memory-proof").textContent.length > 5, "RAM-only proof line missing");

    const script = doc.getElementById("spoken-script").textContent;
    assert.ok(script.length > 80, `on-screen script too short (${script.length})`);
    assert.equal(doc.getElementById("spoken-panel").hidden, false, "offline read-aloud panel hidden");

    assert.equal(spoken.length, 1, `speech called ${spoken.length} times`);
    assert.equal(spoken[0].lang, "ml", "speech language is not Malayalam");
    assert.match(spoken[0].text, MALAYALAM, "speech text is not Malayalam");
    assert.equal(spoken[0].text, payloads[label(names)].safety_message_ml, "speech text differs from the API script");
  });
}

await test("language switch re-renders every card and re-speaks in Hindi", async () => {
  const { window, doc, spoken } = boot();
  doc.querySelector('[data-demo="dup-lasa"]').click();
  await flush();

  const select = doc.getElementById("language");
  select.value = "hi";
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
  await flush();

  assert.equal(doc.documentElement.lang, "hi", "<html lang> not switched");
  assert.match(doc.getElementById("verdict-label").textContent, /खतरा/, "verdict label is not Hindi");
  assert.match(doc.querySelector("#findings li").textContent, DEVANAGARI, "finding is not Hindi");
  assert.equal(spoken.length, 2, `expected a second utterance, got ${spoken.length}`);
  assert.equal(spoken[1].lang, "hi");
  assert.match(spoken[1].text, DEVANAGARI, "Hindi speech is not Devanagari");
});

await test("a preset cannot be started twice while a scan is in flight", async () => {
  const { doc, spoken } = boot();
  doc.querySelector('[data-demo="dup-lasa"]').click();
  doc.querySelector('[data-demo="dup-para"]').click();
  await flush();
  assert.equal(spoken.length, 1, `double submit produced ${spoken.length} results`);
});

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

console.log(`\nLive presets (${BASE}) — integration checks`);
for (const [id, ms] of Object.entries(timings)) {
  const payload = payloads[label(PRESETS[id])];
  console.log(
    `  ${id.padEnd(12)} ${String(ms).padStart(4)} ms  ` +
      `${payload.safety.verdict.padEnd(8)} ${payload.safety.findings.map((f) => f.code).join("+")}`
  );
}
console.log("");
for (const { name, ok, detail } of results) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed\n`);
if (failed) process.exit(1);
