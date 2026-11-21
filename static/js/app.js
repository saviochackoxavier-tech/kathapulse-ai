/* KathaPulse AI — end-to-end orchestration.
 *
 * This file owns the whole loop:
 *
 *   tap → camera/file → canvas scrub → fetch(/verify-strip) with a timeout
 *       → render cards → speak → reset
 *
 * All state changes go through KathaPulseState.transition(), so the screen
 * always reflects one of eight known states and no button can be tapped twice.
 * Failures are classified (timeout / offline / too large / server …) and shown
 * as a localised card with a retry, with the message text always on screen.
 */

(function () {
  "use strict";

  const State = window.KathaPulseState;
  const Capture = window.KathaPulseCapture;
  const Speech = window.KathaPulseSpeech;

  /** Server budget. A low-end Android on 3G needs headroom, but not forever. */
  const REQUEST_TIMEOUT_MS = 20000;

  const els = {
    language: document.getElementById("language"),
    video: document.getElementById("video"),
    preview: document.getElementById("preview"),
    placeholder: document.getElementById("placeholder"),
    startBtn: document.getElementById("start-camera"),
    shutter: document.getElementById("shutter"),
    fileInput: document.getElementById("file-input"),
    status: document.getElementById("status"),
    steps: document.getElementById("steps"),
    stepItems: Array.from(document.querySelectorAll("#steps li")),
    errorCard: document.getElementById("error-card"),
    errorTitle: document.getElementById("error-title"),
    errorBody: document.getElementById("error-body"),
    retryBtn: document.getElementById("retry"),
    manualCard: document.getElementById("manual-card"),
    manualForm: document.getElementById("manual-form"),
    manualInput: document.getElementById("manual-input"),
    result: document.getElementById("result"),
    verdict: document.getElementById("verdict"),
    verdictIcon: document.getElementById("verdict-icon"),
    verdictLabel: document.getElementById("verdict-label"),
    verdictDetail: document.getElementById("verdict-detail"),
    findings: document.getElementById("findings"),
    matchedBox: document.getElementById("matched-box"),
    matchedList: document.getElementById("matched-list"),
    disclaimer: document.getElementById("disclaimer"),
    memoryProof: document.getElementById("memory-proof"),
    speakBtn: document.getElementById("speak"),
    stopBtn: document.getElementById("stop-speak"),
    speechWarning: document.getElementById("speech-warning"),
    spokenPanel: document.getElementById("spoken-panel"),
    spokenScript: document.getElementById("spoken-script"),
    spokenLabel: document.getElementById("spoken-label"),
  };

  let language = "ml";
  let state = State.create();
  let lastPayload = null;
  let retryAction = null;

  // ---------------------------------------------------------------------
  // Copy
  // ---------------------------------------------------------------------
  const UI = {
    ml: {
      verdict: {
        critical: ["അപകടം — ഉടൻ നിർത്തുക", "Do not take these together"],
        caution: ["ശ്രദ്ധിക്കുക", "Check before taking"],
        safe: ["അപകടമില്ല", "No dangerous overlap found"],
        unknown: ["ഉറപ്പില്ല", "Could not verify"],
      },
      steps: ["മെറ്റാഡാറ്റ നീക്കുന്നു", "അയക്കുന്നു", "പരിശോധിക്കുന്നു"],
      busyCapture: "ഫോട്ടോ എടുക്കുന്നു…",
      busyScrub: "മെറ്റാഡാറ്റ നീക്കം ചെയ്യുന്നു…",
      busyCheck: "പരിശോധിക്കുന്നു…",
      cleaned: (kb, orig) =>
        `മെറ്റാഡാറ്റ മുഴുവൻ നീക്കി (${kb} KB അയച്ചു${orig ? `, യഥാർത്ഥം ${orig} KB` : ""})`,
      noVoice:
        "ഈ ഫോണിൽ മലയാളം ശബ്ദം ഇല്ല. Settings → Text-to-speech ൽ Malayalam ഭാഷ ഇൻസ്റ്റാൾ ചെയ്യുക.",
      noSpeech: "ഈ ബ്രൗസറിൽ ശബ്ദം പ്രവർത്തിക്കുന്നില്ല. താഴെയുള്ളത് വായിക്കുക.",
      badge: { critical: "അപകടം", warning: "ശ്രദ്ധ", info: "വിവരം" },
      unreadable: "വായിക്കാനായില്ല",
      matchedEmpty: "മരുന്നുകൾ ഒന്നും സ്ഥിരീകരിച്ചിട്ടില്ല",
      memory: "ചിത്രം സർവറിൽ സേവ് ചെയ്തിട്ടില്ല · processed in RAM only",
      listen: "കേൾക്കുക",
      readAloud: "ഉച്ചത്തിൽ വായിക്കുക · Read aloud",
      readAloudOffline: "ശബ്ദം ലഭ്യമല്ല — താഴെയുള്ളത് വായിക്കുക",
      errorTitle: "സാങ്കേതിക തകരാർ",
    },
    hi: {
      verdict: {
        critical: ["खतरा — तुरंत रोकें", "Do not take these together"],
        caution: ["ध्यान दें", "Check before taking"],
        safe: ["कोई खतरा नहीं", "No dangerous overlap found"],
        unknown: ["पक्का नहीं", "Could not verify"],
      },
      steps: ["मेटाडेटा हटा रहे हैं", "भेज रहे हैं", "जाँच हो रही है"],
      busyCapture: "फ़ोटो ले रहे हैं…",
      busyScrub: "मेटाडेटा हटा रहे हैं…",
      busyCheck: "जाँच हो रही है…",
      cleaned: (kb, orig) =>
        `पूरा मेटाडेटा हटाया (${kb} KB भेजा${orig ? `, मूल ${orig} KB` : ""})`,
      noVoice:
        "इस फ़ोन में हिन्दी आवाज़ नहीं है। Settings → Text-to-speech में Hindi भाषा इंस्टॉल करें।",
      noSpeech: "इस ब्राउज़र में आवाज़ काम नहीं करती। नीचे लिखा पढ़ें।",
      badge: { critical: "खतरा", warning: "ध्यान", info: "जानकारी" },
      unreadable: "पढ़ा नहीं जा सका",
      matchedEmpty: "कोई दवा पक्की नहीं हुई",
      memory: "फ़ोटो सर्वर पर सेव नहीं हुई · processed in RAM only",
      listen: "सुनें",
      readAloud: "ज़ोर से पढ़ें · Read aloud",
      readAloudOffline: "आवाज़ उपलब्ध नहीं — नीचे लिखा पढ़ें",
      errorTitle: "तकनीकी गड़बड़ी",
    },
    en: {
      verdict: {
        critical: ["Danger — stop", "Do not take these together"],
        caution: ["Check before taking", "Possible risk found"],
        safe: ["No dangerous overlap", "These strips look compatible"],
        unknown: ["Could not verify", "Manual check needed"],
      },
      steps: ["Removing metadata", "Sending", "Checking"],
      busyCapture: "Capturing photo…",
      busyScrub: "Removing metadata…",
      busyCheck: "Checking…",
      cleaned: (kb, orig) =>
        `All metadata removed (${kb} KB sent${orig ? `, original ${orig} KB` : ""})`,
      noVoice:
        "No Malayalam voice on this phone. Install it in Settings → Text-to-speech.",
      noSpeech: "Speech is not available in this browser. Please read the text below.",
      badge: { critical: "DANGER", warning: "CAUTION", info: "INFO" },
      unreadable: "unreadable",
      matchedEmpty: "No medicine confirmed",
      memory: "Image never written to disk · processed in RAM only",
      listen: "Listen",
      readAloud: "Read aloud",
      readAloudOffline: "Speech unavailable on this device — read the text below",
      errorTitle: "Something went wrong",
    },
  };

  const t = () => UI[language] || UI.ml;

  // ---------------------------------------------------------------------
  // State → screen
  // ---------------------------------------------------------------------
  const VERDICT_ICON = { critical: "⛔", caution: "⚠️", safe: "✅", unknown: "❓" };

  function dispatch(event, error) {
    state = State.transition(state, event, error);
    render(state);
    return state;
  }

  function render(current) {
    const busy = State.isBusy(current);
    els.steps.hidden = !busy;
    els.errorCard.hidden = current.name !== "error";
    els.verdict.setAttribute("aria-busy", busy ? "true" : "false");

    [els.startBtn, els.shutter, els.retryBtn].forEach((btn) => {
      if (btn) btn.disabled = busy;
    });
    els.fileInput.disabled = busy;

    const step = State.stepIndex(current);
    els.stepItems.forEach((item, index) => {
      item.classList.toggle("is-done", step > -1 && index < step);
      item.classList.toggle("is-active", index === step);
    });
  }

  function setStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.classList.toggle("is-busy", kind === "busy");
    els.status.classList.toggle("is-error", kind === "error");
  }

  function kb(bytes) {
    return Math.max(1, Math.round(bytes / 1024));
  }

  /** Keep the progress labels in the selected language (dot span preserved). */
  function applyStepLabels() {
    const labels = t().steps || [];
    els.stepItems.forEach((item, index) => {
      if (!labels[index]) return;
      const dot = item.querySelector(".dot");
      item.textContent = "";
      if (dot) item.appendChild(dot);
      item.appendChild(document.createTextNode(labels[index]));
    });
  }

  // ---------------------------------------------------------------------
  // Error boundary
  // ---------------------------------------------------------------------

  /** Show a localised error card and keep the previous result on screen. */
  function failWith(eventName, error, action) {
    const code = State.classifyError(error, { online: navigator.onLine !== false });
    retryAction = action || retryAction;

    state = State.transition(state, eventName, { code });
    // A failure raised from a state that has no path for this event must still
    // surface: the error screen is not optional.
    if (state.name !== "error") state = State.transition(state, "FATAL", { code });
    render(state);

    els.errorTitle.textContent = t().errorTitle;
    els.errorBody.textContent = State.errorCopy(code, language);
    els.retryBtn.textContent = State.RETRY_COPY[language] || State.RETRY_COPY.en;
    setStatus("", null);
  }

  // ---------------------------------------------------------------------
  // Rendering the result
  // ---------------------------------------------------------------------
  function renderResult(payload) {
    // The run is over: clear the "checking" line here so both the photo and the
    // named-scan paths leave no stale busy text under a finished verdict.
    setStatus("", null);
    lastPayload = payload;
    const safety = payload.safety || {};
    const verdict = safety.verdict || "unknown";
    const copy = t().verdict[verdict] || t().verdict.unknown;

    els.verdict.className = "verdict " + verdict;
    els.verdictIcon.textContent = VERDICT_ICON[verdict] || "❓";
    els.verdictLabel.textContent = copy[0];
    els.verdictDetail.textContent = copy[1];

    // Localised names so anchor chips never show a raw canonical id.
    const names = {};
    (payload.medicines || []).forEach((medicine) => {
      (medicine.ingredients || []).forEach((ingredient) => {
        names[ingredient.canonical] = {
          en: ingredient.name_en,
          ml: ingredient.name_ml,
          hi: ingredient.name_hi,
        };
      });
    });

    els.findings.textContent = "";
    (safety.findings || []).forEach((finding) => {
      const item = document.createElement("li");
      item.className = "finding " + finding.severity;

      const head = document.createElement("div");
      head.className = "finding-head";

      const badge = document.createElement("span");
      badge.className = "finding-badge";
      badge.textContent = (t().badge[finding.severity] || finding.severity).toUpperCase();

      const title = document.createElement("h3");
      title.className = "finding-title";
      title.textContent = finding.title[language] || finding.title.en;

      head.appendChild(badge);
      head.appendChild(title);

      const message = document.createElement("p");
      message.className = "finding-message";
      message.textContent = finding.message[language] || finding.message.en;

      const action = document.createElement("p");
      action.className = "finding-action";
      action.textContent = finding.action[language] || finding.action.en;

      item.appendChild(head);
      item.appendChild(message);
      item.appendChild(action);

      if (finding.anchors && finding.anchors.length) {
        const chipRow = document.createElement("div");
        chipRow.className = "anchors";
        finding.anchors.forEach((anchor) => {
          const chip = document.createElement("span");
          chip.className = "anchor-chip";
          const entry = names[anchor];
          // LASA anchors are printed labels, not molecules — show them verbatim.
          chip.textContent = entry ? entry[language] || entry.en : anchor;
          chipRow.appendChild(chip);
        });
        item.appendChild(chipRow);
      }

      els.findings.appendChild(item);
    });

    // Detected medicines
    els.matchedList.textContent = "";
    const medicines = payload.medicines || [];
    if (!medicines.length || medicines.every((m) => !m.matched)) {
      const li = document.createElement("li");
      li.className = "unmatched";
      li.textContent = t().matchedEmpty;
      els.matchedList.appendChild(li);
    } else {
      medicines.forEach((medicine) => {
        const li = document.createElement("li");
        if (!medicine.matched) {
          li.className = "unmatched";
          li.textContent = `${medicine.label} — ${t().unreadable}`;
        } else {
          li.textContent = medicine.ingredients
            .map((ingredient) => {
              const name = ingredient[`name_${language}`] || ingredient.name_en;
              return ingredient.strength_mg
                ? `${name} ${Math.round(ingredient.strength_mg)} mg`
                : name;
            })
            .join(" + ");
        }
        els.matchedList.appendChild(li);
      });
    }
    els.matchedBox.open = medicines.length <= 3;

    els.disclaimer.textContent =
      (payload.disclaimer && (payload.disclaimer[language] || payload.disclaimer.en)) || "";
    els.memoryProof.textContent = t().memory;

    // The script is always rendered: this is the offline fallback when the
    // device has no ml-IN / hi-IN voice.
    const script = spokenTextFor(payload);
    els.spokenScript.textContent = script;
    els.spokenPanel.hidden = !script;
    els.spokenPanel.classList.remove("is-fallback");
    els.spokenLabel.textContent = t().readAloud;

    els.result.hidden = false;
    els.manualCard.hidden = payload.extraction_status !== "manual_required";
    els.result.scrollIntoView({ block: "start", behavior: "smooth" });

    resetSpeechWarning();
    speakCurrent();
  }

  // ---------------------------------------------------------------------
  // Speech
  // ---------------------------------------------------------------------

  /** Prefer the backend's flat contract, then the tri-lingual speech payload. */
  function spokenTextFor(payload) {
    if (!payload) return "";
    if (language === "ml" && payload.safety_message_ml) return payload.safety_message_ml;
    if (language === "hi" && payload.safety_message_hi) return payload.safety_message_hi;
    if (payload.safety && payload.safety.speech) return payload.safety.speech.text || "";
    return "";
  }

  function resetSpeechWarning() {
    els.speechWarning.hidden = true;
    els.speechWarning.textContent = "";
    els.spokenPanel.classList.remove("is-fallback");
  }

  /** Promotes the on-screen script when audio is impossible. Never throws. */
  function showSpeechFallback(message) {
    els.speechWarning.hidden = false;
    els.speechWarning.textContent = message;
    els.spokenPanel.hidden = false;
    els.spokenPanel.classList.add("is-fallback");
    els.spokenLabel.textContent = t().readAloudOffline;
    els.stopBtn.hidden = true;
  }

  /** Finding codes the audio pack needs, worst first, capped for a short clip. */
  function packCodes(payload) {
    const findings = (payload && payload.safety && payload.safety.findings) || [];
    return findings.slice(0, 4).map((finding) => finding.code).filter(Boolean);
  }

  /**
   * Tier 0: shipped clips, tried only when the pack actually has some.
   * Returns true when the whole script played; false (immediately) otherwise,
   * so the unchanged device-voice path runs exactly as before.
   */
  async function tryAudioPack(payload) {
    const pack = typeof window !== "undefined" ? window.AudioPack : null;
    if (!pack || typeof pack.playScript !== "function") {
      return false;
    }
    // Only an *loaded* empty pack is worth skipping: gating on "clips === 0"
    // before the manifest lands made tier 0 unreachable on a cold page, because
    // nothing had loaded it yet. playScript loads lazily regardless.
    if (typeof pack.status === "function") {
      const packStatus = pack.status();
      if (packStatus.loaded && packStatus.clips === 0) {
        return false;
      }
    }
    try {
      const result = await pack.playScript(language, packCodes(payload));
      return !!result && result.status === "played";
    } catch (err) {
      return false; // a broken pack must never silence the warning
    }
  }

  async function speakCurrent() {
    const script = spokenTextFor(lastPayload);
    if (!script) {
      dispatch("SPEECH_SKIPPED");
      return;
    }

    resetSpeechWarning();

    // A recorded/synthesised clip outranks a synthesised device voice. The
    // script can run for half a minute, so STOP is offered while it plays.
    els.stopBtn.hidden = false;
    if (await tryAudioPack(lastPayload)) {
      els.stopBtn.hidden = true;
      dispatch("SPEECH_START");
      dispatch("SPEECH_END");
      return;
    }
    els.stopBtn.hidden = true;

    if (!Speech || !Speech.isSupported()) {
      dispatch("SPEECH_START");
      showSpeechFallback(t().noSpeech);
      dispatch("SPEECH_END");
      return;
    }
    if (language !== "en" && !Speech.hasVoiceFor(language)) {
      dispatch("SPEECH_START");
      showSpeechFallback(t().noVoice);
      dispatch("SPEECH_END");
      return;
    }

    dispatch("SPEECH_START");
    els.stopBtn.hidden = false;
    try {
      const result = await Speech.speak(script, language);
      if (!result.ok) {
        showSpeechFallback(result.reason === "no-voice" ? t().noVoice : t().noSpeech);
      }
    } catch (err) {
      // A speech engine failure must never take down the result screen.
      showSpeechFallback(t().noSpeech);
    } finally {
      els.stopBtn.hidden = true;
      dispatch("SPEECH_END");
    }
  }

  // ---------------------------------------------------------------------
  // Network
  // ---------------------------------------------------------------------

  /** fetch with an AbortController timeout; errors carry an HTTP status. */
  async function requestWithTimeout(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body && body.detail) {
            detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
          }
        } catch (err) {
          /* keep the status line */
        }
        const error = new Error(detail);
        error.name = "HttpError";
        error.status = response.status;
        throw error;
      }
      return response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function verifyBlob(scrubbed) {
    dispatch("SCRUB_DONE");

    const form = new FormData();
    // A fresh Blob built from canvas pixels: no EXIF, no original filename.
    form.append("image", scrubbed.blob, "strip.jpg");
    form.append("language", language);
    form.append("paracetamol_taken_today_mg", "0");

    const action = () => retryScan(scrubbed);
    try {
      const payload = await requestWithTimeout("/verify-strip", {
        method: "POST",
        body: form,
      });
      setStatus(
        t().cleaned(
          kb(scrubbed.bytes || scrubbed.blob.size),
          scrubbed.originalBytes ? kb(scrubbed.originalBytes) : null
        )
      );
      retryAction = null;
      dispatch("UPLOAD_OK");
      renderResult(payload);
    } catch (err) {
      failWith("UPLOAD_FAIL", err, action);
    }
  }

  /**
   * Re-enter the flow from the top when retrying an upload.
   * Calling the request directly would skip the state machine, leaving the
   * spinner off and the buttons live during the second attempt.
   */
  function retryScan(scrubbed) {
    dispatch("FILE_SELECTED");
    return handleScrubbed(scrubbed);
  }

  async function handleScrubbed(scrubbed) {
    retryAction = null;
    Capture.showPreview(els.preview, scrubbed);
    els.placeholder.hidden = true;
    els.video.hidden = true;
    setStatus(t().busyScrub, "busy");
    await verifyBlob(scrubbed);
  }

  // ---------------------------------------------------------------------
  // Capture
  // ---------------------------------------------------------------------
  async function openCamera() {
    setStatus("", null);
    try {
      await Capture.startCamera(els.video, els.preview);
      els.placeholder.hidden = true;
      els.preview.hidden = true;
      els.startBtn.hidden = true;
      els.shutter.hidden = false;
      els.shutter.focus();
      dispatch("CAMERA_OPENED");
    } catch (err) {
      const name = err && err.name;
      const synthetic = new Error("camera");
      synthetic.name = name === "NotAllowedError" ? "CameraDenied" : "CameraFailed";
      failWith("CAMERA_FAILED", synthetic, openCamera);
      els.errorBody.textContent = State.errorCopy(
        name === "NotAllowedError" ? "camera_denied" : "unknown",
        language
      );
      els.fileInput.focus();
    }
  }

  async function shoot() {
    if (State.isBusy(state)) return;
    // Retry after a capture failure reopens the camera; re-calling shoot()
    // would fail with "the camera is not running" and loop forever.
    const action = () => openCamera();
    try {
      dispatch("CAPTURE_START");
      setStatus(t().busyCapture, "busy");
      const scrubbed = await Capture.grabFrame();
      Capture.stopCamera();
      els.shutter.hidden = true;
      els.startBtn.hidden = false;
      dispatch("CAPTURE_DONE");
      await handleScrubbed(scrubbed);
    } catch (err) {
      failWith("CAPTURE_FAILED", err, action);
    }
  }

  async function pickFile(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const action = () => {
      els.fileInput.click();
    };
    dispatch("FILE_SELECTED");
    setStatus(t().busyScrub, "busy");

    try {
      const scrubbed = await Capture.scrubFile(file);
      await handleScrubbed(scrubbed);
    } catch (err) {
      const imageError = new Error(err && err.message ? err.message : "image");
      imageError.name = "KathaImageError";
      failWith("SCRUB_FAILED", imageError, action);
    } finally {
      // Clear the input so the SAME file can be picked again after a failure.
      // (Nulling retryAction here used to kill the Retry button immediately.)
      event.target.value = "";
    }
  }

  // ---------------------------------------------------------------------
  // Name-based checks: manual entry and the demo presets are one scan
  //
  // Both triggers submit a list of printed names -- no camera, no scrub stage.
  // A single handler owns the request, the transitions and the retry wiring,
  // so the two entry points cannot drift apart.
  // ---------------------------------------------------------------------

  /** Parse the manual textarea into at most ten trimmed, non-empty names. */
  function parseManualNames() {
    return els.manualInput.value
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 10);
  }

  /**
   * Scan a list of medicine names and render (or fail) exactly like a photo.
   *
   * @param {string[]} names printed names, as typed or preset
   * @param {() => unknown} [onRetry] what Retry should run; repeating this
   *        same scan by default.
   */
  async function runNamedScan(names, onRetry) {
    if (State.isBusy(state) || !names || !names.length) return;

    // A fresh attempt starts clean: no stale file selection, no stale error.
    els.fileInput.value = "";
    els.errorCard.hidden = true;
    retryAction = null;
    // There is no scrub stage, but the run must still pass through `uploading`
    // so a failed request has a valid path to the error screen.
    dispatch("FILE_SELECTED");
    dispatch("SCRUB_DONE");
    setStatus(t().busyCheck, "busy");

    try {
      const payload = await requestWithTimeout("/verify-medicines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ medicines: names.map((name) => ({ name })), language }),
      });
      dispatch("UPLOAD_OK");
      renderResult(payload);
    } catch (err) {
      failWith("UPLOAD_FAIL", err, onRetry || (() => runNamedScan(names)));
    }
  }

  function submitManual(event) {
    event.preventDefault();
    const names = parseManualNames();
    if (!names.length) return;
    // Retry re-submits the form, so an edit made after the failure is honoured.
    return runNamedScan(names, () => els.manualForm.requestSubmit());
  }

  // ---------------------------------------------------------------------
  // Demo presets: a live pitch cannot depend on a camera or a physical strip
  // ---------------------------------------------------------------------
  const DEMO_PRESETS = {
    "dup-lasa": ["Telma 40", "Telma-H 40/12.5"],
    "dup-para": ["Dolo 650", "Crocin Cold & Flu"],
    "lasa-alone": ["Amaryl 1 mg"],
  };

  /** Run the preset behind a `data-demo` id; unknown ids are ignored. */
  function runPreset(id) {
    const names = DEMO_PRESETS[id];
    if (names) return runNamedScan(names);
    return undefined;
  }

  async function retry() {
    const action = retryAction;
    retryAction = null;

    // Reset everything the failed attempt left behind, so a retry is a clean
    // run: no stale error card, no stale status, no stale file selection
    // (a file input that still holds a value will not fire `change` again).
    els.fileInput.value = "";
    els.errorCard.hidden = true;
    setStatus("", null);
    resetSpeechWarning();
    dispatch("RETRY");

    if (!action) {
      els.fileInput.focus();
      return;
    }
    try {
      await action();
    } catch (err) {
      failWith("FATAL", err, null);
    }
  }

  // ---------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------
  els.startBtn.addEventListener("click", openCamera);
  els.shutter.addEventListener("click", shoot);
  els.fileInput.addEventListener("change", pickFile);
  els.manualForm.addEventListener("submit", submitManual);
  els.retryBtn.addEventListener("click", retry);
  els.speakBtn.addEventListener("click", speakCurrent);

  els.stopBtn.addEventListener("click", () => {
    if (window.AudioPack) window.AudioPack.stop();
    Speech.stop();
    els.stopBtn.hidden = true;
    dispatch("SPEECH_END");
  });

  document.querySelectorAll("[data-demo]").forEach((button) => {
    button.addEventListener("click", () => runPreset(button.dataset.demo));
  });

  els.language.addEventListener("change", () => {
    language = els.language.value;
    document.documentElement.lang = language;
    Speech.stop();
    els.retryBtn.textContent = State.RETRY_COPY[language] || State.RETRY_COPY.en;
    applyStepLabels();
    if (lastPayload) renderResult(lastPayload);
    else setStatus("", null);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) Speech.stop();
  });

  // Global error boundary: an unexpected throw shows the localised card and
  // leaves the rest of the page usable, instead of dying silently.
  window.addEventListener("error", (event) => {
    if (event && event.message) failWith("FATAL", event.error || new Error(event.message));
  });
  window.addEventListener("unhandledrejection", (event) => {
    failWith("FATAL", event.reason || new Error("unhandled rejection"));
  });

  // Connectivity changes surface immediately instead of at the next timeout.
  window.addEventListener("offline", () => {
    setStatus(State.errorCopy("offline", language), "error");
  });
  window.addEventListener("online", () => {
    if (state.name !== "error") setStatus("", null);
  });

  // Warm the shipped clip manifest so the first warning of the session is not
  // forced onto the device voice while the pack is still unloaded. Best-effort:
  // an empty or missing pack simply leaves the fallback chain untouched.
  if (window.AudioPack && typeof window.AudioPack.load === "function") {
    window.AudioPack.load().catch(() => undefined);
  }

  // Offline shell (roadmap item 6): cache the UI + taxonomy so a pharmacy with
  // one bar of signal still gets an instant paint. Best-effort: a browser that
  // refuses service workers (private mode, older WebView) must lose nothing.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    });
  }

  // Initial paint
  els.retryBtn.textContent = State.RETRY_COPY[language] || State.RETRY_COPY.en;
  applyStepLabels();
  render(state);
})();
