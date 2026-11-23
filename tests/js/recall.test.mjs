/* DOM-level test for the batch recall & expiry auditor.
 *
 * The backend suite (tests/test_recall.py) proves the engine. This proves the
 * part a pharmacist actually sees:
 *
 *   index.html + state.js + audio-pack.js + app.js in jsdom
 *     → the pharmacy preset posts the printed batch and expiry
 *     → a recalled batch renders a CRIMSON banner above the verdict
 *     → an expiring box renders the same banner in AMBER
 *     → the banner copy follows the selected language (ml / hi)
 *     → box findings are not repeated in the list below
 *     → the audio pack is asked for a clip per new finding code
 *     → typing a batch in manual entry sends it
 *
 * Payloads are real captures from the running API (`fixtures/batch-recall.json`
 * = recalled metformin batch that also expired, `batch-soon.json` = a box
 * expiring next month), so the copy asserted here is the copy the server sends.
 *
 * Run: node recall.test.mjs        (from tests/js)
 * Needs: jsdom (already a dev dependency). No server.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(HERE, "../../static");
const read = (p) => readFileSync(join(STATIC_DIR, p), "utf8");

const RECALL = JSON.parse(readFileSync(join(HERE, "fixtures/batch-recall.json"), "utf8"));
const SOON = JSON.parse(readFileSync(join(HERE, "fixtures/batch-soon.json"), "utf8"));
const PLAIN = JSON.parse(readFileSync(join(HERE, "fixtures/duplasa.json"), "utf8"));

const RECALL_CODES = ["RECALLED_BATCH", "EXPIRED_STOCK"];
const MALAYALAM = /[\u0d00-\u0d7f]/;
const DEVANAGARI = /[\u0900-\u097f]/;
const MANIFEST_URL = "/static/audio/manifest.json";
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

/** A manifest whose clips cover the batch findings, framed by intro/outro. */
function manifestWith(codes, lang = "ml") {
  const clips = { [`${lang}:intro`]: `/static/audio/${lang}/intro.webm` };
  for (const code of codes) clips[`${lang}:${code}`] = `/static/audio/${lang}/${code}.webm`;
  clips[`${lang}:outro`] = `/static/audio/${lang}/outro.webm`;
  return { schema: 1, version: "5", clips };
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

function boot({ payload = RECALL, manifest = { schema: 1, version: "0", clips: {} } } = {}) {
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

  // --- network: the manifest, plus whatever scan payload this test needs -----
  const requests = [];
  const fetched = [];
  window.fetch = async (url, options = {}) => {
    const target = String(url);
    fetched.push(target);
    if (target.includes("manifest.json")) {
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(manifest)) };
    }
    if (target.includes("/verify-medicines")) {
      requests.push({
        url: target,
        body: options.body ? JSON.parse(options.body) : null,
      });
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(payload)) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };

  // --- audio: record clips, finish each one ---------------------------------
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

  return { win: window, doc, spoken, played, packCalls, requests, fetched, errors, pack };
}

async function runPreset(env, id = "batch-recall") {
  const button = env.doc.querySelector(`[data-demo="${id}"]`);
  assert.ok(button, `no [data-demo="${id}"] button in index.html`);
  button.click();
  await flush();
}

async function switchTo(env, lang) {
  const select = env.doc.getElementById("language");
  select.value = lang;
  select.dispatchEvent(new env.win.Event("change", { bubbles: true }));
  await flush(60);
}

const banner = (env) => env.doc.getElementById("batch-banner");
const items = (env) => [...banner(env).querySelectorAll(".batch-item")];

// ---------------------------------------------------------------------------
// 1. The preset sends the box, not just the molecule
// ---------------------------------------------------------------------------

await test("the pharmacy preset posts the printed batch and expiry", async () => {
  const env = boot();
  await runPreset(env);

  assert.equal(env.requests.length, 1, `posted ${env.requests.length} times`);
  const sent = env.requests[0].body;
  assert.deepEqual(sent.medicines, [
    { name: "Glycomet 500", batch_no: "GM2407A", expiry: "09/2026" },
  ]);
  assert.equal(sent.language, "ml");
});

// ---------------------------------------------------------------------------
// 2. Crimson banner, above the verdict
// ---------------------------------------------------------------------------

await test("a recalled batch renders a crimson banner above the verdict", async () => {
  const env = boot();
  await runPreset(env);

  assert.equal(banner(env).hidden, false, "no banner for a recalled batch");
  assert.match(banner(env).className, /critical/, `banner class: ${banner(env).className}`);
  assert.equal(items(env).length, 2, `banner has ${items(env).length} items, expected 2`);

  const following = env.win.Node.DOCUMENT_POSITION_FOLLOWING;
  assert.ok(
    banner(env).compareDocumentPosition(env.doc.getElementById("verdict")) & following,
    "the banner is not above the verdict"
  );

  const text = banner(env).textContent;
  assert.match(text, MALAYALAM, "banner copy is not Malayalam");
  assert.match(text, /GM2407A/, "the batch number is not shown");
  assert.match(text, /തിരിച്ചുവിളിച്ച/, "the recall title is missing");
});

await test("box findings are not repeated in the findings list", async () => {
  const env = boot();
  await runPreset(env);

  const list = env.doc.getElementById("findings");
  assert.equal(list.children.length, 0, `findings list repeated ${list.children.length} box finding(s)`);
});

await test("the banner is a live region, so a screen reader announces it", async () => {
  const env = boot();
  await runPreset(env);
  assert.equal(banner(env).getAttribute("role"), "alert");
});

// ---------------------------------------------------------------------------
// 3. Amber case and the no-finding case
// ---------------------------------------------------------------------------

await test("an expiring box uses the amber warning treatment", async () => {
  const env = boot({ payload: SOON });
  await runPreset(env);

  assert.equal(banner(env).hidden, false, "no banner for a near-expiry box");
  assert.match(banner(env).className, /warning/, `banner class: ${banner(env).className}`);
  assert.doesNotMatch(banner(env).className, /critical/);
  assert.equal(items(env).length, 1);
  assert.match(banner(env).textContent, /കാലഹരണം അടുത്തു/);
  assert.match(banner(env).textContent, /12\/2026/);
});

await test("a scan with no box findings shows no banner", async () => {
  const env = boot({ payload: PLAIN });
  await runPreset(env, "dup-lasa");

  assert.equal(banner(env).hidden, true, "a banner appeared without a batch finding");
  assert.equal(env.doc.getElementById("findings").children.length, 2, "the combination findings disappeared");
});

// ---------------------------------------------------------------------------
// 4. Language
// ---------------------------------------------------------------------------

await test("Hindi selection renders Devanagari in the banner and speaks the Hindi script", async () => {
  const env = boot();
  await switchTo(env, "hi");
  await runPreset(env);

  assert.match(banner(env).textContent, DEVANAGARI, "banner stayed in Malayalam under Hindi");
  assert.doesNotMatch(banner(env).textContent, MALAYALAM, "Malayalam leaked into the Hindi banner");
  assert.equal(env.spoken.length, 1);
  assert.equal(env.spoken[0].lang, "hi");
  assert.equal(env.spoken[0].text, RECALL.safety_message_hi);
});

// ---------------------------------------------------------------------------
// 5. Audio pack slots for the new codes
// ---------------------------------------------------------------------------

await test("the audio pack is asked for one clip per batch finding code", async () => {
  const env = boot({ manifest: manifestWith(RECALL_CODES) });
  await runPreset(env);

  assert.equal(env.packCalls.length, 1, `playScript called ${env.packCalls.length} times`);
  assert.deepEqual(env.packCalls[0].codes, RECALL_CODES);
  assert.equal(env.spoken.length, 0, "the device voice spoke over the shipped clips");
  assert.deepEqual(env.played, [
    "/static/audio/ml/intro.webm",
    "/static/audio/ml/RECALLED_BATCH.webm",
    "/static/audio/ml/EXPIRED_STOCK.webm",
    "/static/audio/ml/outro.webm",
  ]);
});

await test("Hindi clips are addressed with the Hindi language key", async () => {
  const manifest = {
    schema: 1,
    version: "5",
    clips: { ...manifestWith(RECALL_CODES, "ml").clips, ...manifestWith(RECALL_CODES, "hi").clips },
  };
  const env = boot({ manifest });
  await switchTo(env, "hi");
  await runPreset(env);

  assert.equal(env.packCalls[0].lang, "hi");
  assert.ok(
    env.played.every((src) => src.includes("/hi/")),
    `played non-Hindi clips: ${env.played.join(", ")}`
  );
});

// ---------------------------------------------------------------------------
// 6. Manual entry carries a typed batch
// ---------------------------------------------------------------------------

await test("manual entry sends the batch and expiry a pharmacist types", async () => {
  const env = boot();
  env.doc.getElementById("manual-input").value = "Glycomet 500";
  env.doc.getElementById("batch-input").value = "gm 2407a";
  env.doc.getElementById("expiry-input").value = "09/2026";
  env.doc
    .getElementById("manual-form")
    .dispatchEvent(new env.win.Event("submit", { bubbles: true, cancelable: true }));
  await flush();

  assert.equal(env.requests.length, 1, "the manual form posted nothing");
  assert.deepEqual(env.requests[0].body.medicines, [
    { name: "Glycomet 500", batch_no: "gm 2407a", expiry: "09/2026" },
  ]);
  assert.equal(banner(env).hidden, false, "a typed batch did not render the banner");
});

await test("an empty batch field is not invented for the server", async () => {
  const env = boot({ payload: PLAIN });
  env.doc.getElementById("manual-input").value = "Dolo 650";
  env.doc
    .getElementById("manual-form")
    .dispatchEvent(new env.win.Event("submit", { bubbles: true, cancelable: true }));
  await flush();

  assert.deepEqual(env.requests[0].body.medicines, [
    { name: "Dolo 650", batch_no: "", expiry: "" },
  ]);
});

await test("the whole boot + preset + language switch path raises nothing unhandled", async () => {
  const env = boot({ manifest: manifestWith(RECALL_CODES) });
  await runPreset(env);
  await switchTo(env, "hi");
  await flush(100);
  assert.deepEqual(env.errors, [], `window errors: ${env.errors.join(", ")}`);
});

await test("the manifest is still warmed at boot (audio tier stays alive)", async () => {
  const env = boot();
  await flush(120);
  assert.ok(env.fetched.includes(MANIFEST_URL), "boot did not warm the audio pack");
  assert.equal(env.packCalls.length, 0, "a clip played without a scan");
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
