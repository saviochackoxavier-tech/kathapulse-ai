/* DOM-level integration test for the local audio pack (tier 0).
 *
 * The unit suite (audio-pack.test.mjs) proves the loader in isolation. This one
 * proves the wiring the user actually depends on:
 *
 *   index.html + state.js + audio-pack.js + app.js in jsdom
 *     → a scan result renders
 *     → app.js calls AudioPack.playScript with the right language and codes
 *     → clips present  : the shipped clips play and the device voice stays idle
 *     → clips missing  : nothing half-plays, the device voice takes over
 *     → nothing usable : the written warning is promoted, never silence
 *
 * It caught a real bug when it was written: nothing loaded the manifest before
 * the first LISTEN, so a populated pack could never be used on a cold page.
 *
 * Run: node audiopack.test.mjs        (from tests/js)
 * Needs: jsdom (already a dev dependency of this folder). No server.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(HERE, "../../static");
const read = (p) => readFileSync(join(STATIC_DIR, p), "utf8");

/** A real payload captured from POST /verify-medicines (Telma 40 + Telma-H). */
const FIXTURE = JSON.parse(readFileSync(join(HERE, "fixtures/duplasa.json"), "utf8"));
const CODES = ["DUPLICATE_SALT", "LASA_RISK"];
const MANIFEST_URL = "/static/audio/manifest.json";

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

/** A clip set for one language, framed by intro/outro as playScript expects. */
function clipsFor(lang) {
  const clips = {};
  clips[`${lang}:intro`] = `/static/audio/${lang}/intro.webm`;
  for (const code of CODES) clips[`${lang}:${code}`] = `/static/audio/${lang}/${code}.webm`;
  clips[`${lang}:outro`] = `/static/audio/${lang}/outro.webm`;
  return clips;
}

function manifestWith(clips, version = "4") {
  return { schema: 1, version, clips };
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

/**
 * Boot the real app in jsdom.
 *
 * Only the edges are faked: fetch (manifest + the captured scan payload), the
 * <audio> element, device speech, and the camera. audio-pack.js and app.js are
 * the shipped files, executed unmodified.
 */
function boot({
  manifest = manifestWith({}),
  fetchFails = false,
  holdAudio = false, // clips never report `ended`: keeps a script "playing"
  speech = { supported: true, voices: true },
  audioPack = null, // replace window.AudioPack entirely (broken/absent pack)
  removePack = false,
} = {}) {
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

  // --- network: the manifest and one captured scan ---------------------------
  const fetched = [];
  window.fetch = async (url) => {
    const target = String(url);
    fetched.push(target);
    if (target.includes("manifest.json")) {
      if (fetchFails) throw new window.Error("offline");
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(manifest)) };
    }
    if (target.includes("/verify-medicines")) {
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(FIXTURE)) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };

  // --- audio: record every clip, finish each one asynchronously --------------
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
      // `ended` fires after playToEnd has attached its listener.
      if (!holdAudio) {
        setTimeout(() => (this._handlers.ended || []).forEach((h) => h()), 0);
      }
      return Promise.resolve();
    };
    this.pause = () => {};
  }
  window.Audio = MockAudio;

  // --- camera: irrelevant to a named scan -----------------------------------
  window.KathaPulseCapture = {
    startCamera: async () => {},
    stopCamera: () => {},
    isRunning: () => false,
    showPreview: () => {},
    grabFrame: async () => null,
    scrubFile: async () => null,
    getLast: () => null,
  };

  // --- device speech: recorded, never spoken --------------------------------
  const spoken = [];
  window.KathaPulseSpeech = {
    isSupported: () => speech.supported,
    hasVoiceFor: () => speech.voices,
    speak: async (text, lang) => {
      spoken.push({ text, lang });
      return { ok: true };
    },
    stop: () => {},
    isSpeaking: () => false,
  };

  window.eval(read("js/state.js"));
  if (removePack) delete window.AudioPack;
  else if (audioPack) window.AudioPack = audioPack;
  else window.eval(read("js/audio-pack.js"));
  window.eval(read("js/app.js"));

  const pack = window.AudioPack || null;

  // Record what app.js asks the pack to do, delegating to the real code.
  const packCalls = [];
  const stopCalls = [];
  if (pack && typeof pack.playScript === "function" && !audioPack) {
    const realPlayScript = pack.playScript;
    const realStop = pack.stop;
    pack.playScript = function (lang, codes, options) {
      packCalls.push({ lang, codes: [...(codes || [])] });
      return realPlayScript.call(pack, lang, codes, options);
    };
    pack.stop = function () {
      stopCalls.push(true);
      return realStop.call(pack);
    };
  }

  return { win: window, doc, spoken, played, packCalls, stopCalls, fetched, errors, pack };
}

/** Click the Telma preset and let render + speech settle. */
async function scan(env) {
  const button = env.doc.querySelector('[data-demo="dup-lasa"]');
  assert.ok(button, "no [data-demo=\"dup-lasa\"] button in index.html");
  button.click();
  await flush();
}

// ---------------------------------------------------------------------------
// 1. Clips present: the pack speaks, the device voice stays idle
// ---------------------------------------------------------------------------

await test("the manifest is fetched at boot, before the first LISTEN", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")) });
  await flush(120);
  assert.ok(
    env.fetched.includes(MANIFEST_URL),
    `boot did not warm the pack (fetched: ${env.fetched.join(", ") || "nothing"})`
  );
  assert.equal(env.pack.status().clips, 4, "warm load did not pick up the clips");
});

await test("clips present: app.js calls playScript with the language and finding codes", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")) });
  await scan(env);
  assert.equal(env.packCalls.length, 1, `playScript called ${env.packCalls.length} times`);
  assert.equal(env.packCalls[0].lang, "ml");
  assert.deepEqual(env.packCalls[0].codes, CODES, "wrong finding codes handed to the pack");
});

await test("clips present: intro → each finding → outro play in order, device voice silent", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")) });
  await scan(env);
  assert.deepEqual(env.played, [
    "/static/audio/ml/intro.webm",
    "/static/audio/ml/DUPLICATE_SALT.webm",
    "/static/audio/ml/LASA_RISK.webm",
    "/static/audio/ml/outro.webm",
  ]);
  assert.equal(env.spoken.length, 0, "device voice spoke over the shipped clips");
  assert.equal(env.doc.getElementById("speech-warning").hidden, true, "fallback notice shown despite clips");
  assert.equal(env.doc.getElementById("spoken-panel").hidden, false, "on-screen script disappeared");
});

await test("clips present: Hindi selection requests Hindi clips", async () => {
  const manifest = manifestWith({ ...clipsFor("ml"), ...clipsFor("hi") });
  const env = boot({ manifest });
  const select = env.doc.getElementById("language");
  select.value = "hi";
  select.dispatchEvent(new env.win.Event("change", { bubbles: true }));
  await scan(env);
  assert.equal(env.packCalls.length, 1);
  assert.equal(env.packCalls[0].lang, "hi", "pack asked for the wrong language");
  assert.ok(env.played.every((src) => src.includes("/hi/")), `walked ml clips: ${env.played.join(", ")}`);
  assert.equal(env.spoken.length, 0);
});

await test("a playing clip script offers STOP, and STOP stops the pack", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")), holdAudio: true });
  await scan(env);
  const stop = env.doc.getElementById("stop-speak");
  assert.equal(stop.hidden, false, "a playing clip script cannot be stopped");
  stop.click();
  assert.ok(env.stopCalls.length >= 1, "AudioPack.stop was never called");
  assert.equal(stop.hidden, true, "STOP stayed visible after stopping");
});

await test("LISTEN replays the whole script", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")) });
  await scan(env);
  const first = env.played.length;
  env.doc.getElementById("speak").click();
  await flush();
  assert.equal(env.played.length, first * 2, `replay produced ${env.played.length - first} clips`);
});

// ---------------------------------------------------------------------------
// 2. Clips missing: fall back to the device voice, never half-speak
// ---------------------------------------------------------------------------

await test("empty manifest: playScript is skipped and the device voice speaks", async () => {
  const env = boot({ manifest: manifestWith({}) });
  await scan(env);
  assert.equal(env.played.length, 0, "played audio from an empty pack");
  assert.equal(env.spoken.length, 1, `device voice called ${env.spoken.length} times`);
  assert.equal(env.spoken[0].lang, "ml");
  assert.match(env.spoken[0].text, MALAYALAM);
  assert.equal(env.spoken[0].text, FIXTURE.safety_message_ml, "spoke something other than the API script");
});

await test("a pack missing only the outro plays nothing and hands over to the device voice", async () => {
  const clips = clipsFor("ml");
  delete clips["ml:outro"];
  const env = boot({ manifest: manifestWith(clips) });
  await scan(env);
  assert.equal(env.pack.status().clips, 3, "partial manifest not loaded");
  assert.equal(env.packCalls.length, 1, "app.js did not consult the pack");
  assert.equal(env.played.length, 0, "a half-spoken warning was played");
  assert.equal(env.spoken.length, 1, "no device-voice fallback after an incomplete pack");
});

await test("a pack that throws never silences the warning", async () => {
  const env = boot({
    audioPack: {
      status: () => ({ loaded: true, clips: 2, version: "9", error: null }),
      playScript: () => {
        throw new Error("decoder blew up");
      },
      stop: () => {},
    },
  });
  await scan(env);
  assert.equal(env.spoken.length, 1, "the throw swallowed the warning");
  assert.match(env.spoken[0].text, MALAYALAM);
  assert.deepEqual(env.errors, [], `unhandled error leaked: ${env.errors.join(", ")}`);
});

await test("no AudioPack at all (older cached bundle) still speaks", async () => {
  const env = boot({ removePack: true });
  await scan(env);
  assert.equal(env.spoken.length, 1, "missing pack broke speech");
  assert.equal(env.doc.getElementById("result").hidden, false);
});

// ---------------------------------------------------------------------------
// 3. Nothing readable: promote the written warning
// ---------------------------------------------------------------------------

await test("no pack, no speech support: the written warning is promoted", async () => {
  const env = boot({ manifest: manifestWith({}), speech: { supported: false, voices: false } });
  await scan(env);
  assert.equal(env.spoken.length, 0);
  const warning = env.doc.getElementById("speech-warning");
  assert.equal(warning.hidden, false, "no fallback notice shown");
  assert.ok(warning.textContent.length > 5, "fallback notice is empty");
  assert.equal(env.doc.getElementById("spoken-panel").hidden, false, "on-screen script hidden");
  assert.ok(env.doc.getElementById("spoken-script").textContent.length > 80);
  assert.equal(env.doc.getElementById("stop-speak").hidden, true);
});

await test("no Malayalam voice installed: text fallback, not English audio", async () => {
  const env = boot({ manifest: manifestWith({}), speech: { supported: true, voices: false } });
  await scan(env);
  assert.equal(env.spoken.length, 0, "spoke in some other language instead of falling back");
  assert.equal(env.doc.getElementById("speech-warning").hidden, false);
  assert.match(env.doc.getElementById("spoken-script").textContent, MALAYALAM);
});

await test("offline manifest fetch degrades to the device voice", async () => {
  const env = boot({ fetchFails: true });
  await scan(env);
  assert.equal(env.played.length, 0);
  assert.equal(env.spoken.length, 1, "an offline manifest fetch silenced the warning");
  assert.deepEqual(env.errors, []);
});

await test("the whole warm-up + scan path raises nothing unhandled", async () => {
  const env = boot({ manifest: manifestWith(clipsFor("ml")) });
  await scan(env);
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
