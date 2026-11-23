/* DOM-level test for the ground-truth knowledge base and the age rule.
 *
 * The backend suite (tests/test_knowledge_base.py) proves the matcher. This
 * proves what a user sees:
 *
 *   index.html + state.js + audio-pack.js + app.js in jsdom
 *     → "Glycomet GP" (resolved by the local base) shows a
 *       "Ground-Truth verified" badge, in the selected language
 *     → a plain taxonomy hit shows no badge (the badge means something)
 *     → an age-band warning renders as a normal amber finding and is spoken
 *     → the audio pack is asked for the AGE_WARNING clip
 *     → the age travels as a request field, never inside a medicine object
 *       (the schema forbids extra keys, so getting this wrong is a 422)
 *
 * Payloads are real captures from the running API (`fixtures/groundtruth.json`
 * and `fixtures/age-warning.json`).
 *
 * Run: node groundtruth.test.mjs        (from tests/js). No server needed.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(HERE, "../../static");
const read = (p) => readFileSync(join(STATIC_DIR, p), "utf8");

const GT = JSON.parse(readFileSync(join(HERE, "fixtures/groundtruth.json"), "utf8"));
const AGE = JSON.parse(readFileSync(join(HERE, "fixtures/age-warning.json"), "utf8"));
const PLAIN = JSON.parse(readFileSync(join(HERE, "fixtures/duplasa.json"), "utf8"));
// The preset posts names only, but the capture is reused so the badge assertion
// is about the real payload the server sends for "Glycomet GP".

const MALAYALAM = /[\u0d00-\u0d7f]/;
const DEVANAGARI = /[\u0900-\u097f]/;
const flush = (ms = 350) => new Promise((resolve) => setTimeout(resolve, ms));

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, detail: err.message });
  }
}

function manifestWith(codes, lang = "ml") {
  const clips = { [`${lang}:intro`]: `/static/audio/${lang}/intro.webm` };
  for (const code of codes) clips[`${lang}:${code}`] = `/static/audio/${lang}/${code}.webm`;
  clips[`${lang}:outro`] = `/static/audio/${lang}/outro.webm`;
  return { schema: 1, version: "6", clips };
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

function boot({ payload = GT, manifest = { schema: 1, version: "0", clips: {} } } = {}) {
  const dom = new JSDOM(read("index.html"), {
    url: "http://127.0.0.1:3004/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const doc = window.document;
  window.Element.prototype.scrollIntoView = function () {};

  const errors = [];
  window.addEventListener("error", (event) => errors.push(String(event.message)));
  window.addEventListener("unhandledrejection", (event) =>
    errors.push("unhandledrejection: " + String(event.reason))
  );

  const requests = [];
  window.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.includes("manifest.json")) {
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(manifest)) };
    }
    if (target.includes("/verify-medicines")) {
      requests.push({ url: target, body: options.body ? JSON.parse(options.body) : null });
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(payload)) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };

  const played = [];
  function MockAudio(src) {
    this.src = src;
    this.preload = "";
    this.playbackRate = 1;
    this._handlers = {};
    played.push(src);
    this.addEventListener = (name, handler) => {
      (this._handlers[name] = this._handlers[name] || []).push(handler);
    };
    this.play = () => {
      setTimeout(() => (this._handlers.ended || []).forEach((h) => h()), 0);
      return Promise.resolve();
    };
    this.pause = () => {};
  }
  window.Audio = MockAudio;

  window.KathaPulseCapture = {
    startCamera: async () => {},
    stopCamera: () => {},
    isRunning: () => false,
    showPreview: () => {},
    grabFrame: async () => null,
    scrubFile: async () => null,
    getLast: () => null,
  };

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
  window.eval(read("js/audio-pack.js"));
  window.eval(read("js/app.js"));

  const pack = window.AudioPack;
  const packCalls = [];
  const realPlayScript = pack.playScript;
  pack.playScript = function (lang, codes, options) {
    packCalls.push({ lang, codes: [...(codes || [])] });
    return realPlayScript.call(pack, lang, codes, options);
  };

  return { win: window, doc, spoken, played, packCalls, requests, errors };
}

async function scanNamed(env, names, { batch = null, age = null } = {}) {
  env.doc.getElementById("manual-input").value = names.join("\n");
  if (batch !== null) env.doc.getElementById("batch-input").value = batch;
  if (age !== null) env.doc.getElementById("age-input").value = String(age);
  env.doc
    .getElementById("manual-form")
    .dispatchEvent(new env.win.Event("submit", { bubbles: true, cancelable: true }));
  await flush();
}

async function switchTo(env, lang) {
  const select = env.doc.getElementById("language");
  select.value = lang;
  select.dispatchEvent(new env.win.Event("change", { bubbles: true }));
  await flush(60);
}

const badge = (env) => env.doc.getElementById("gt-badge");

// ---------------------------------------------------------------------------
// 1. The badge
// ---------------------------------------------------------------------------

await test("a ground-truth resolution shows the verified badge", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);

  assert.equal(badge(env).hidden, false, "no badge after a ground-truth match");
});

await test("the badge is localised, not English-only chrome", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  const ml = badge(env).textContent;
  assert.match(ml, MALAYALAM, `Malayalam badge missing: ${ml}`);

  await switchTo(env, "hi");
  const hi = badge(env).textContent;
  assert.match(hi, DEVANAGARI, `Hindi badge missing: ${hi}`);
  assert.doesNotMatch(hi, MALAYALAM, "Malayalam leaked into the Hindi badge");
});

await test("the ground-truth preset shows the badge in one tap", async () => {
  const env = boot();
  const button = env.doc.querySelector('[data-demo="ground-truth"]');
  assert.ok(button, "no [data-demo=\"ground-truth\"] button in index.html");
  button.click();
  await flush();

  assert.equal(badge(env).hidden, false, "the preset did not show the badge");
  assert.deepEqual(env.requests[0].body.medicines, [
    { name: "Glycomet GP", batch_no: "", expiry: "" },
  ]);
});

await test("a plain taxonomy match shows no badge", async () => {
  const env = boot({ payload: PLAIN });
  await scanNamed(env, ["Telma 40", "Telma-H"]);

  assert.equal(badge(env).hidden, true, "the badge appeared without a ground-truth match");
});

await test("the badge sits above the speech controls, not in the footer", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);

  const following = env.win.Node.DOCUMENT_POSITION_FOLLOWING;
  assert.ok(
    badge(env).compareDocumentPosition(env.doc.getElementById("speak")) & following,
    "the badge is below the LISTEN button"
  );
});

// ---------------------------------------------------------------------------
// 2. The age rule
// ---------------------------------------------------------------------------

await test("an age-band warning renders as an amber finding", async () => {
  const env = boot({ payload: AGE });
  await scanNamed(env, ["Amaryl 1"], { age: 72 });

  // Amaryl also carries its LASA advisory, so the age warning is one of two.
  const findings = [...env.doc.querySelectorAll("#findings .finding")];
  const age = findings.find((node) => /65/.test(node.textContent));
  assert.ok(age, "no finding mentions the age band");
  assert.match(age.className, /warning/);
  assert.match(age.textContent, MALAYALAM, "age copy is not Malayalam");
  assert.equal(findings.length, 2, `${findings.length} findings rendered`);
});

await test("the age warning is spoken, in the selected language", async () => {
  const env = boot({ payload: AGE });
  await scanNamed(env, ["Amaryl 1"], { age: 72 });

  assert.equal(env.spoken.length, 1, `device voice called ${env.spoken.length} times`);
  assert.equal(env.spoken[0].text, AGE.safety_message_ml);
  assert.match(env.spoken[0].text, MALAYALAM);
});

await test("the audio pack is asked for the AGE_WARNING clip", async () => {
  const env = boot({
    payload: AGE,
    manifest: manifestWith(["AGE_WARNING", "LASA_RISK"]),
  });
  await scanNamed(env, ["Amaryl 1"], { age: 72 });

  assert.equal(env.packCalls.length, 1);
  // The Amaryl payload carries its LASA advisory too; both need a clip.
  assert.deepEqual(env.packCalls[0].codes, ["AGE_WARNING", "LASA_RISK"]);
  assert.ok(
    env.played.includes("/static/audio/ml/AGE_WARNING.webm"),
    `clips played: ${env.played.join(", ")}`
  );
});

await test("no age typed means no age field sent", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);

  assert.equal(env.requests.length, 1);
  assert.equal("age_years" in env.requests[0].body, false, "an empty age was sent");
});

// ---------------------------------------------------------------------------
// 3. Wire format: age is request-level, batch is per-medicine
// ---------------------------------------------------------------------------

await test("the typed age travels as a request field and never inside a medicine", async () => {
  const env = boot({ payload: AGE });
  await scanNamed(env, ["Amaryl 1"], { age: 72, batch: "AM2401" });

  const sent = env.requests[0].body;
  assert.equal(sent.age_years, 72);
  assert.deepEqual(sent.medicines, [
    { name: "Amaryl 1", batch_no: "AM2401", expiry: "" },
  ]);
  assert.equal("age_years" in sent.medicines[0], false, "age leaked into the medicine");
});

await test("an impossible age is not sent at all", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"], { age: 500 });

  assert.equal("age_years" in env.requests[0].body, false);
});

await test("the whole boot + scan path raises nothing unhandled", async () => {
  const env = boot({
    payload: AGE,
    manifest: manifestWith(["AGE_WARNING", "LASA_RISK"]),
  });
  await scanNamed(env, ["Amaryl 1"], { age: 72 });
  await switchTo(env, "hi");
  await flush(100);
  assert.deepEqual(env.errors, [], `window errors: ${env.errors.join(", ")}`);
});

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

for (const { name, ok, detail } of results) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed\n`);
if (failed) process.exit(1);
