/* DOM-level test for dose reminders (Pass 31).
 *
 * The backend suite (tests/test_audio_reminders.py) proves the parser, the
 * paracetamol ceiling and the translation. This proves what the patient sees:
 *
 *   index.html + state.js + reminders.js + audio-pack.js + app.js in jsdom
 *     → the reminder panel appears for a matched scan and only then
 *     → SET posts the scan's medicines and the chosen pattern to /reminders
 *     → a scheduled plan paints a localised countdown banner
 *     → a refusal (SOS) shows the reason and never paints a banner
 *     → CANCEL drops the in-memory plan; so does a scan of other medicines
 *     → switching language re-renders the banner in that language
 *     → a failed request leaves a readable error and no phantom clock
 *
 * The banner text is computed by the pure helper in static/js/reminders.js, so
 * the clock arithmetic is tested directly here too.
 *
 * Payloads are real captures (`fixtures/reminder-plan.json`,
 * `fixtures/reminder-refused.json`).
 *
 * Run: node reminders.test.mjs        (from tests/js). No server needed.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(HERE, "../../static");
const read = (p) => readFileSync(join(STATIC_DIR, p), "utf8");

const PLAN = JSON.parse(readFileSync(join(HERE, "fixtures/reminder-plan.json"), "utf8"));
const REFUSED = JSON.parse(readFileSync(join(HERE, "fixtures/reminder-refused.json"), "utf8"));
const SCAN = JSON.parse(readFileSync(join(HERE, "fixtures/groundtruth.json"), "utf8"));
const AGE = JSON.parse(readFileSync(join(HERE, "fixtures/age-warning.json"), "utf8"));

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

// ---------------------------------------------------------------------------
// 1. The pure clock (static/js/reminders.js)
// ---------------------------------------------------------------------------

const clock = {};
{
  const window = {};
  new Function("window", read("js/reminders.js"))(window);
  clock.R = window.KathaPulseReminders;
}

await test("nextDose picks the next slot later today", () => {
  const now = new Date(2026, 10, 23, 20, 0, 0).getTime();
  const next = clock.R.nextDose([{ time: "09:00" }, { time: "21:00" }], now);

  assert.equal(next.slot.time, "21:00");
  assert.equal(next.inMs, 60 * 60 * 1000);
});

await test("a slot already past rolls to tomorrow", () => {
  const now = new Date(2026, 10, 23, 22, 0, 0).getTime();
  const next = clock.R.nextDose([{ time: "09:00" }], now);

  assert.equal(new Date(next.at).getDate(), 24);
});

await test("nextDose survives empty and malformed input", () => {
  assert.equal(clock.R.nextDose([], Date.now()), null);
  assert.equal(clock.R.nextDose(null, Date.now()), null);
  assert.equal(clock.R.nextDose([{ time: "99:99" }], Date.now()), null);
  assert.equal(clock.R.nextDose([{ nope: 1 }], Date.now()), null);
});

await test("formatLeft speaks hours and minutes in the chosen language", () => {
  assert.equal(clock.R.formatLeft(60_000, { h: " h", m: " min" }), "1 min");
  assert.equal(clock.R.formatLeft(3_600_000, { h: " h", m: " min" }), "1 h 0 min");
  const ml = clock.R.formatLeft(3_600_000, { h: " മണിക്കൂർ", m: " മിനിറ്റ്" });
  assert.match(ml, MALAYALAM);
  assert.match(ml, /1/);
});

await test("isDue fires at the dose time, not before", () => {
  const now = Date.now();
  assert.equal(clock.R.isDue({ at: now }, now), true);
  assert.equal(clock.R.isDue({ at: now + 60_000 }, now), false);
  assert.equal(clock.R.isDue(null, now), false);
});

// ---------------------------------------------------------------------------
// 2. Harness
// ---------------------------------------------------------------------------

const boots = [];

function boot({
  payload = SCAN,
  plan = PLAN,
  planFails = false,
  manifest = { schema: 1, version: "0", clips: {} },
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

  const requests = [];
  let current = payload;
  window.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.includes("manifest.json")) {
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(manifest)) };
    }
    if (target.includes("/reminders")) {
      requests.push({ url: target, body: options.body ? JSON.parse(options.body) : null });
      if (planFails) throw new TypeError("Failed to fetch");
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(plan)) };
    }
    if (target.includes("/verify-medicines")) {
      requests.push({ url: target, body: options.body ? JSON.parse(options.body) : null });
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(current)) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };

  function MockAudio(src) {
    this.src = src;
    this.addEventListener = () => {};
    this.play = () => Promise.resolve();
    this.pause = () => {};
  }
  window.Audio = MockAudio;

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

  window.KathaPulseCapture = {
    startCamera: async () => {},
    stopCamera: () => {},
    isRunning: () => false,
    showPreview: () => {},
    grabFrame: async () => null,
    scrubFile: async () => null,
    getLast: () => null,
  };

  window.eval(read("js/state.js"));
  window.eval(read("js/audio-pack.js"));
  window.eval(read("js/reminders.js"));
  window.eval(read("js/app.js"));

  boots.push(window);

  return {
    win: window,
    doc,
    requests,
    errors,
    spoken,
    setPayload: (next) => {
      current = next;
    },
  };
}

const byId = (env, id) => env.doc.getElementById(id);

async function scanNamed(env, names, { age = null } = {}) {
  byId(env, "manual-input").value = names.join("\n");
  if (age !== null) byId(env, "age-input").value = String(age);
  byId(env, "manual-form").dispatchEvent(
    new env.win.Event("submit", { bubbles: true, cancelable: true })
  );
  await flush();
}

async function switchTo(env, lang) {
  const select = byId(env, "language");
  select.value = lang;
  select.dispatchEvent(new env.win.Event("change", { bubbles: true }));
  await flush(80);
}

async function schedule(env, pattern = null) {
  if (pattern !== null) byId(env, "pattern").value = pattern;
  byId(env, "schedule").click();
  await flush();
}

// ---------------------------------------------------------------------------
// 3. Panel visibility
// ---------------------------------------------------------------------------

await test("the panel is hidden until a scan has a matched medicine", async () => {
  const env = boot();
  assert.equal(byId(env, "reminder-panel").hidden, true, "panel shown before any scan");

  await scanNamed(env, ["Glycomet GP"]);
  assert.equal(byId(env, "reminder-panel").hidden, false, "panel hidden after a matched scan");

  const empty = JSON.parse(JSON.stringify(SCAN));
  empty.medicines = empty.medicines.map((m) => ({ ...m, matched: false }));
  const env2 = boot({ payload: empty });
  await scanNamed(env2, ["SMUDGED"]);
  assert.equal(byId(env2, "reminder-panel").hidden, true, "panel shown for an unmatched scan");
});

await test("the panel explains that the page must stay open", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);

  const help = byId(env, "reminder-help").textContent;
  assert.match(help, MALAYALAM, `help text is not Malayalam: ${help}`);
  assert.match(help, /പേജ്/, "help does not mention keeping the page open");
});

// ---------------------------------------------------------------------------
// 4. Scheduling
// ---------------------------------------------------------------------------

await test("SET posts the scan's medicines and the chosen pattern", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env, "1-0-1");

  const call = env.requests.find((r) => r.url.includes("/reminders"));
  assert.ok(call, "no /reminders request");
  assert.equal(call.body.pattern, "1-0-1");
  assert.equal(call.body.language, "ml");
  assert.ok(call.body.medicines.length >= 1);
  for (const medicine of call.body.medicines) {
    assert.deepEqual(Object.keys(medicine), ["name"], "extra keys would be a 422");
    assert.ok(medicine.name.length > 0);
  }
});

await test("a scheduled plan paints a localised countdown banner", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);

  assert.equal(byId(env, "reminder-banner").hidden, false, "no banner after scheduling");
  const text = byId(env, "reminder-next").textContent;
  assert.match(text, MALAYALAM, `banner is not Malayalam: ${text}`);
  assert.match(text, /\d{2}:\d{2}/, `banner has no dose time: ${text}`);
});

await test("the confirmation names the times the server chose", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);

  const message = byId(env, "reminder-msg").textContent;
  assert.match(message, /08:00/, `confirmation lost the times: ${message}`);
  assert.match(message, MALAYALAM);
});

await test("switching to Hindi re-renders the banner in Hindi", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);
  await switchTo(env, "hi");

  const text = byId(env, "reminder-next").textContent;
  assert.match(text, DEVANAGARI, `banner is not Hindi: ${text}`);
  assert.doesNotMatch(text, MALAYALAM, "Malayalam leaked into the Hindi banner");
  assert.equal(byId(env, "reminder-banner").hidden, false);
});

// ---------------------------------------------------------------------------
// 5. Refusals and cancellation
// ---------------------------------------------------------------------------

await test("an SOS refusal shows the reason and no banner", async () => {
  const env = boot({ plan: REFUSED });
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env, "1-0-1");

  assert.equal(byId(env, "reminder-banner").hidden, true, "a refused plan painted a banner");
  const message = byId(env, "reminder-msg").textContent;
  assert.match(message, MALAYALAM, `refusal is not localised: ${message}`);
  assert.match(message, /SOS/);
});

await test("CANCEL drops the plan and the banner", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);
  assert.equal(byId(env, "reminder-banner").hidden, false);

  byId(env, "cancel-reminder").click();
  await flush(60);

  assert.equal(byId(env, "reminder-banner").hidden, true, "banner survived CANCEL");
});

await test("scanning different medicines clears the old reminder", async () => {
  const env = boot({ payload: AGE });
  await scanNamed(env, ["Amaryl 1"]);
  await schedule(env);
  assert.equal(byId(env, "reminder-banner").hidden, false, "no banner to clear");

  // A stale plan naming Amaryl must not survive a scan of something else.
  env.setPayload(SCAN);
  await scanNamed(env, ["Glycomet GP"]);

  assert.equal(byId(env, "reminder-banner").hidden, true, "the old plan survived a new scan");
  assert.equal(byId(env, "reminder-msg").hidden, true, "the old confirmation survived");
});

await test("a failed request leaves a readable error and no clock", async () => {
  const env = boot({ planFails: true });
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);

  assert.equal(byId(env, "reminder-banner").hidden, true, "a failed request painted a clock");
  const message = byId(env, "reminder-msg").textContent;
  assert.ok(message.trim().length > 0, "the failure was silent");
  assert.match(message, MALAYALAM, `error is not localised: ${message}`);
});

await test("the whole path raises nothing unhandled", async () => {
  const env = boot();
  await scanNamed(env, ["Glycomet GP"]);
  await schedule(env);
  await switchTo(env, "hi");
  byId(env, "cancel-reminder").click();
  await flush(100);

  assert.deepEqual(env.errors, [], `window errors: ${env.errors.join(", ")}`);
});

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

// Each window holds the 15-second reminder interval; closing it lets Node exit.
for (const window of boots) {
  try {
    window.close();
  } catch (err) {
    // jsdom already closed
  }
}

for (const { name, ok, detail } of results) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed\n`);
if (failed) process.exit(1);
