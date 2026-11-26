#!/usr/bin/env bun
/**
 * Capture the Stage 4 visual evidence set in `evidence/`.
 *
 * Drives a real headless Chrome over the DevTools protocol so the phone
 * widths are exact (320 / 360 CSS px, overlay scrollbars, device scale 1) and
 * every file is a crop of the live result panel — no mock markup, no source
 * changes to `app/` or `static/`.
 *
 * Pre-conditions
 * --------------
 *   * the app is running (`./scripts/serve.sh`, or the Windows shim on :3004);
 *   * Google Chrome is installed (override with CHROME_PATH);
 *   * Bun is the runtime (`bun scripts/capture_evidence.mjs`).
 *
 * What is real and what is injected
 * ---------------------------------
 *   (a) 01-*  real `/verify-medicines` response for the ground-truth preset;
 *   (c) 03-*  real response for the recalled + expired Glycomet batch;
 *   (d) 04-*  real speech/reminder path — headless Chrome has no ml-IN / hi-IN
 *             voice, so the on-screen fallback is the one a low-end phone shows;
 *   (b) 02-*  SIMULATED confidence response. With `vision_keys: 0` the server
 *             cannot produce a low/medium read, so the fetch response is
 *             rewritten in the page to the shape the vision tier returns, and
 *             an amber "simulated" banner is rendered into the capture so the
 *             screenshot can never be mistaken for a live OCR result.
 */

import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.KATHA_URL || "http://127.0.0.1:3004/";
const OUT = "evidence";
const PORT = Number(process.env.CDP_PORT || 9333);
const CHROME =
  process.env.CHROME_PATH ||
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.next = 1;
    this.pending = new Map();
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new Error(JSON.stringify(message.error)));
      else entry.resolve(message.result);
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.next++;
    this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`timeout: ${method}`));
      }, 30000);
    });
  }
}

async function launch() {
  const profile = join(tmpdir(), `katha-cdp-${Date.now()}`);
  mkdirSync(profile, { recursive: true });
  const child = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      `--user-data-dir=${profile}`,
      `--remote-debugging-port=${PORT}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  );

  let info = null;
  for (let i = 0; i < 60 && !info; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (response.ok) info = await response.json();
    } catch {
      await sleep(250);
    }
  }
  if (!info) throw new Error("Chrome did not expose a DevTools endpoint");

  const ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });

  return { cdp: new CDP(ws), child, profile };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const { cdp, child, profile } = await launch();
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", {
    targetId,
    flatten: true,
  });
  const send = (method, params) => cdp.send(method, params, sessionId);

  await send("Page.enable");
  await send("Runtime.enable");

  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "eval failed");
    }
    return result.result?.value;
  };

  const viewport = (width, height = 900) =>
    send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: true,
    });

  const open = async () => {
    await send("Page.navigate", { url: BASE });
    for (let i = 0; i < 80; i += 1) {
      if (await evaluate("document.readyState === 'complete'")) break;
      await sleep(100);
    }
    await evaluate("document.fonts.ready.then(() => true)");
    await sleep(250);
  };

  const waitFor = async (expression, label, tries = 100) => {
    for (let i = 0; i < tries; i += 1) {
      if (await evaluate(expression)) return;
      await sleep(100);
    }
    throw new Error(`timed out waiting for ${label}`);
  };

  const setLanguage = async (language) => {
    await evaluate(`(() => {
      const select = document.getElementById('language');
      select.value = ${JSON.stringify(language)};
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return select.value;
    })()`);
    await sleep(200);
  };

  /** Run a demo preset and wait for the rendered result. */
  const runPreset = async (id) => {
    await evaluate(`document.querySelector('[data-demo="${id}"]').click()`);
    await waitFor("!document.getElementById('result').hidden", `result for ${id}`);
    await sleep(400);
  };

  /**
   * Crop to the result panel (plus any annotation placed above it), or from an
   * anchor section — the manual-entry card sits above the result and is part of
   * the low-confidence story.
   */
  const shot = async (name, width, anchorId) => {
    const rect = await evaluate(`(() => {
      const top = document.getElementById('result').getBoundingClientRect().top + window.scrollY;
      const note = document.getElementById('capture-note');
      const anchor = ${JSON.stringify(anchorId || null)} ? document.getElementById(${JSON.stringify(anchorId || null)}) : null;
      const anchorTop = anchor && !anchor.hidden ? anchor.getBoundingClientRect().top + window.scrollY : null;
      let start = note ? note.getBoundingClientRect().top + window.scrollY : top;
      if (anchorTop !== null && anchorTop < start) start = anchorTop;
      const bottom = document.getElementById('result').getBoundingClientRect().bottom + window.scrollY;
      return { start: Math.max(0, Math.round(start - 6)), height: Math.round(bottom - start + 12) };
    })()`);
    const { data } = await send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      clip: { x: 0, y: rect.start, width, height: rect.height, scale: 1 },
    });
    writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
    console.log(`  ${name}  ${width}x${rect.height}`);
  };

  const annotate = (text) =>
    evaluate(`(() => {
      document.getElementById('capture-note')?.remove();
      const note = document.createElement('p');
      note.id = 'capture-note';
      note.setAttribute('role', 'note');
      note.textContent = ${JSON.stringify(text)};
      note.style.cssText = 'margin:0 0 8px;padding:8px 10px;border:1px dashed #d99b1c;' +
        'background:#3a2a0c;color:#ffdf9e;font:600 11px/1.35 system-ui,sans-serif;border-radius:6px';
      const result = document.getElementById('result');
      result.parentNode.insertBefore(note, result);
      return note.textContent;
    })()`);

  try {
    console.log("(a) evidence card — ground truth, English");
    await viewport(320);
    await open();
    await setLanguage("en");
    await runPreset("ground-truth");
    await shot("01-evidence-card-320.png", 320);
    const overflow = await evaluate(
      "(document.documentElement.scrollWidth === document.documentElement.clientWidth) ? document.documentElement.clientWidth : -1"
    );
    console.log(`  horizontal overflow check @320: clientWidth=${overflow}`);
    await viewport(360);
    await sleep(300);
    const overflow360 = await evaluate(
      "(document.documentElement.scrollWidth === document.documentElement.clientWidth) ? document.documentElement.clientWidth : -1"
    );
    console.log(`  horizontal overflow check @360: clientWidth=${overflow360}`);
    await shot("01-evidence-card-360.png", 360);

    console.log("(b) confidence gate — SIMULATED responses");
    const simulate = async (low) => {
      await viewport(320);
      await open();
      await setLanguage("en");
      await evaluate(`(() => {
        const real = window.fetch;
        window.__kathaRealFetch = real;
        window.fetch = async (input, init) => {
          const url = typeof input === 'string' ? input : input.url;
          const response = await real(input, init);
          if (!url.includes('/verify-medicines') || (init && init.method !== 'POST')) return response;
          const data = await response.clone().json();
          data.recapture_required = true;
          data.low_confidence_rejected = ${low};
          data.extraction_status = ${low} ? 'manual_required' : 'partial';
          data.ground_truth_verified = false;
          data.evidence = (data.evidence || []).map((row) => ({
            ...row, name_status: 'unverified', strength_status: 'unverified',
            ingredient_status: 'unverified', source: '', verified_on: ''
          }));
          return new Response(JSON.stringify(data), {
            status: 200, headers: { 'Content-Type': 'application/json' }
          });
        };
        return true;
      })()`);
      await runPreset("ground-truth");
      await waitFor("!document.getElementById('recapture-card').hidden", "recapture card");
      await sleep(300);
      await annotate(
        low
          ? "SIMULATED CONFIDENCE RESPONSE — low read, refused before matching (vision_keys: 0 in this environment; response injected in the page, real UI path)"
          : "SIMULATED CONFIDENCE RESPONSE — medium read, candidate held for a retake (vision_keys: 0 in this environment; response injected in the page, real UI path)"
      );
      await sleep(150);
      await shot(
        low ? "02-low-rejected-simulated.png" : "02-recapture-simulated.png",
        320,
        low ? "manual-card" : undefined
      );
    };
    await simulate(false);
    await simulate(true);

    console.log("(c) recalled + expired batch — English / Malayalam / Hindi");
    const languages = [
      ["en", "03-recall-banner-320.png"],
      ["ml", "03-recall-banner-ml.png"],
      ["hi", "03-recall-banner-hi.png"],
    ];
    await viewport(320);
    for (const [language, name] of languages) {
      await open();
      await setLanguage(language);
      await runPreset("batch-recall");
      await waitFor("!document.getElementById('batch-banner').hidden", "batch banner");
      await sleep(250);
      await shot(name, 320);
    }

    console.log("(d) speech fallback + running 1-0-1 reminder — Malayalam / Hindi");
    for (const [language, name] of [
      ["ml", "04-voice-reminder-ml.png"],
      ["hi", "04-voice-reminder-hi.png"],
    ]) {
      await open();
      await setLanguage(language);
      await runPreset("dup-lasa");
      await evaluate(`(() => {
        const pattern = document.getElementById('pattern');
        pattern.value = '1-0-1';
        pattern.dispatchEvent(new Event('change', { bubbles: true }));
        document.getElementById('schedule').click();
        return pattern.value;
      })()`);
      await waitFor("!document.getElementById('reminder-banner').hidden", "reminder countdown", 120);
      await evaluate("document.getElementById('speak').click()");
      await sleep(1200);
      const spoken = await evaluate(
        "!document.getElementById('speech-warning').hidden"
      );
      console.log(`  ${language}: speech fallback notice visible = ${spoken}`);
      await shot(name, 320);
    }

    console.log(`\nCaptures written to ${OUT}/`);
  } finally {
    try {
      child.kill();
    } catch {
      /* ignore */
    }
    // Chrome can still hold the profile briefly on Windows; a leftover temp
    // directory is harmless and must not fail the run.
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        rmSync(profile, { recursive: true, force: true });
        break;
      } catch {
        await sleep(300);
      }
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
