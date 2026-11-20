/* DOM-level test for the retry path — the one place the Pass 4 bug actually
 * lived.
 *
 * The state machine is already covered in state.test.mjs, but the defect was in
 * app.js: `pickFile`'s finally block nulled `retryAction`, so the button was
 * rendered, enabled, and pointed at nothing. Only executing app.js against a
 * real DOM catches that class of bug.
 *
 * jsdom runs static/index.html; capture and speech are stubbed so no camera,
 * canvas or audio is involved. fetch is scripted: fail once, then succeed.
 *
 * Run: node retry.test.mjs   (from tests/js)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const staticDir = join(here, "../../static");
const read = (p) => readFileSync(join(staticDir, p), "utf8");

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, detail: err.message });
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 30));

const SCAN_PAYLOAD = {
  scan_id: "test123",
  extraction_status: "ok",
  extraction_source: "manual",
  medicines: [
    {
      label: "Dolo 650",
      matched: true,
      ingredients: [
        {
          canonical: "paracetamol",
          name_en: "Paracetamol",
          name_ml: "പാരാസെറ്റമോൾ",
          name_hi: "पैरासिटामोल",
          drug_class: "paracetamol",
          strength_mg: 650,
          daily_max_mg: 4000,
        },
      ],
    },
  ],
  safety: {
    verdict: "critical",
    findings: [
      {
        code: "DUPLICATE_SALT",
        severity: "critical",
        title: { en: "Same medicine twice", ml: "ഒരേ മരുന്ന് രണ്ടുതവണ", hi: "एक ही दवा दो बार" },
        message: { en: "Paracetamol in 2 strips.", ml: "പാരാസെറ്റമോൾ 2 സ്ട്രിപ്പുകളിൽ.", hi: "पैरासिटामोल 2 पत्तों में।" },
        action: { en: "Take one.", ml: "ഒന്ന് കഴിക്കുക.", hi: "एक लें।" },
        anchors: ["paracetamol"],
      },
    ],
    speech: { language: "ml", text: "മുന്നറിയിപ്പ്", rate: 0.85, pause_before: 0.25 },
  },
  disclaimer: { en: "d", ml: "d", hi: "d" },
  language: "ml",
  processed_in_memory: true,
  image_bytes_received: 1024,
  safety_message_ml: "കഥാപൾസ് മുന്നറിയിപ്പ്. പാരാസെറ്റമോൾ 2 സ്ട്രിപ്പുകളിൽ.",
  safety_message_hi: "कथापल्स चेतावनी। पैरासिटामोल 2 पत्तों में।",
  duplicate_salt_warning: true,
  lasa_risk: false,
};

/** Build a fresh app instance with scripted fetch behaviour. */
function boot({ scrubImpl } = {}) {
  const html = read("index.html");
  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:3004/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;

  // jsdom has no layout; app.js scrolls result panels into view.
  window.Element.prototype.scrollIntoView = function () {};

  const fetchCalls = [];
  window.fetch = async (url, options) => {
    fetchCalls.push(url);
    const behaviour = window.__fetchBehaviour || "ok";
    if (behaviour === "reject") {
      throw new window.TypeError("Failed to fetch");
    }
    return {
      ok: true,
      status: 200,
      json: async () => JSON.parse(JSON.stringify(SCAN_PAYLOAD)),
    };
  };
  window.__fetchCalls = fetchCalls;

  // Camera/canvas stubbed: this test is about orchestration, not pixels.
  window.KathaPulseCapture = {
    startCamera: async () => {},
    stopCamera: () => {},
    isRunning: () => false,
    showPreview: () => {},
    grabFrame: async () => makeScrubbed(window),
    scrubFile: scrubImpl ? (file) => scrubImpl(window, file) : async () => makeScrubbed(window),
    getLast: () => null,
  };

  window.KathaPulseSpeech = {
    isSupported: () => false, // exercises the offline text fallback
    hasVoiceFor: () => false,
    speak: async () => ({ ok: false, reason: "no-voice" }),
    stop: () => {},
    isSpeaking: () => false,
  };

  window.eval(read("js/state.js"));
  window.eval(read("js/app.js"));

  return { dom, window, doc: window.document, fetchCalls };
}

function makeScrubbed(window) {
  return {
    blob: new window.Blob(["fake-jpeg"], { type: "image/jpeg" }),
    width: 1600,
    height: 1200,
    bytes: 240000,
    source: "camera",
  };
}

function selectFile(window, doc, name = "strip.jpg") {
  const file = new window.File(["fake"], name, { type: "image/jpeg" });
  const input = doc.getElementById("file-input");
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
  return input;
}

// ---------------------------------------------------------------------------
// 1. Network failure -> Retry -> success, all without a page reload
// ---------------------------------------------------------------------------

await test("retry after a network failure completes the scan", async () => {
  const { window, doc, fetchCalls } = boot();
  window.__fetchBehaviour = "reject";

  selectFile(window, doc);
  await flush();

  // Failure surfaces.
  assert.equal(doc.getElementById("error-card").hidden, false, "error card not shown");
  assert.ok(doc.getElementById("error-body").textContent.length > 10, "error body empty");
  assert.match(
    doc.getElementById("error-body").textContent,
    /[\u0d00-\u0d7f]/,
    "error text is not Malayalam"
  );
  assert.equal(doc.getElementById("retry").disabled, false, "retry disabled");
  assert.equal(fetchCalls.length, 1, "expected exactly one failed request");

  // Retry -> second request -> result rendered.
  window.__fetchBehaviour = "ok";
  doc.getElementById("retry").click();
  await flush();
  await flush();

  assert.equal(fetchCalls.length, 2, `retry did not re-request (calls: ${fetchCalls.length})`);
  assert.equal(doc.getElementById("error-card").hidden, true, "error card still visible");
  assert.equal(doc.getElementById("result").hidden, false, "result not rendered");
  assert.match(doc.getElementById("verdict-label").textContent, /അപകടം/);
  assert.equal(doc.getElementById("file-input").value, "", "file input not cleared");
});

// ---------------------------------------------------------------------------
// 2. The original bug: retry after a *scrub* failure must reopen the picker
// ---------------------------------------------------------------------------

await test("retry after an image failure reopens the file picker", async () => {
  let attempts = 0;
  const { window, doc } = boot({
    scrubImpl: async (win) => {
      attempts += 1;
      if (attempts === 1) {
        const err = new win.Error("bad image");
        err.name = "KathaImageError";
        throw err;
      }
      return makeScrubbed(win);
    },
  });

  const input = selectFile(window, doc, "broken.jpg");
  await flush();

  assert.equal(doc.getElementById("error-card").hidden, false, "error card not shown");

  // Watch for the picker being reopened.
  let pickerOpened = 0;
  input.click = () => {
    pickerOpened += 1;
  };

  doc.getElementById("retry").click();
  await flush();

  assert.equal(pickerOpened, 1, "retry did not reopen the file picker");
  assert.equal(input.value, "", "file input not cleared before reopening");
  assert.equal(doc.getElementById("error-card").hidden, true, "error card not dismissed");
});

// ---------------------------------------------------------------------------
// 3. Retry is repeatable, not one-shot
// ---------------------------------------------------------------------------

await test("retry survives three consecutive failures", async () => {
  const { window, doc, fetchCalls } = boot();
  window.__fetchBehaviour = "reject";

  for (let i = 0; i < 3; i += 1) {
    if (i === 0) {
      selectFile(window, doc);
    } else {
      doc.getElementById("retry").click();
      // Retry of an upload re-enters the flow, which re-sends the scrubbed blob.
    }
    await flush();
    await flush();
    assert.equal(
      doc.getElementById("error-card").hidden,
      false,
      `error card hidden on attempt ${i + 1}`
    );
  }

  assert.ok(fetchCalls.length >= 3, `expected >=3 requests, got ${fetchCalls.length}`);

  // And it still recovers.
  window.__fetchBehaviour = "ok";
  doc.getElementById("retry").click();
  await flush();
  await flush();
  assert.equal(doc.getElementById("result").hidden, false, "did not recover after retries");
});

// ---------------------------------------------------------------------------
// 4. Timeout classification is localised too
// ---------------------------------------------------------------------------

await test("a timeout shows the timeout message, not a generic one", async () => {
  const { window, doc } = boot();
  window.fetch = async () => {
    const err = new window.Error("aborted");
    err.name = "AbortError";
    throw err;
  };

  selectFile(window, doc);
  await flush();

  const body = doc.getElementById("error-body").textContent;
  assert.match(body, /[\u0d00-\u0d7f]/, "not Malayalam");
  assert.ok(body.length > 20, "message too short");
  assert.equal(doc.getElementById("retry").disabled, false);
});

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

console.log("\nRetry path (jsdom) — runtime checks");
for (const { name, ok, detail } of results) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed\n`);
if (failed) process.exit(1);
