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
  // A cached bundle may predate reminders.js; degrade to "no clock" rather than
  // throwing inside the render path.
  const Reminders = window.KathaPulseReminders || {
    nextDose: () => null,
    formatLeft: () => "",
    isDue: () => false,
  };

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
    batchBanner: document.getElementById("batch-banner"),
    batchBannerLabel: document.getElementById("batch-banner-label"),
    batchBannerList: document.getElementById("batch-banner-list"),
    batchInput: document.getElementById("batch-input"),
    expiryInput: document.getElementById("expiry-input"),
    ageInput: document.getElementById("age-input"),
    gtBadge: document.getElementById("gt-badge"),
    gtText: document.getElementById("gt-text"),
    reminderPanel: document.getElementById("reminder-panel"),
    pattern: document.getElementById("pattern"),
    scheduleBtn: document.getElementById("schedule"),
    reminderHelp: document.getElementById("reminder-help"),
    reminderMsg: document.getElementById("reminder-msg"),
    reminderBanner: document.getElementById("reminder-banner"),
    reminderNext: document.getElementById("reminder-next"),
    cancelReminderBtn: document.getElementById("cancel-reminder"),
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
      batchLabel: "ബാച്ച്, കാലഹരണ പരിശോധന",
      groundTruth: "ഗ്രൗണ്ട് ട്രൂത്ത് ഉറപ്പിച്ചത് · verified locally",
      reminder: {
        title: "ഡോസ് ഓർമ്മപ്പെടുത്തൽ",
        help:
          "കുറിപ്പടിയിലെ നേരങ്ങൾ തിരഞ്ഞെടുക്കുക. ഈ പേജ് തുറന്നിരിക്കുമ്പോൾ മാത്രം ഓർമ്മപ്പെടുത്തൽ പ്രവർത്തിക്കും.",
        next: (time, left) => `അടുത്ത ഡോസ് ${time} · ${left} കഴിഞ്ഞ്`,
        due: (time) => `${time} ആയി — ഡോസ് സമയമായി.`,
        h: " മണിക്കൂർ",
        m: " മിനിറ്റ്",
      },
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
      batchLabel: "बैच और एक्सपायरी जाँच",
      groundTruth: "ग्राउंड-ट्रूथ से सत्यापित · verified locally",
      reminder: {
        title: "खुराक की याद",
        help:
          "पर्चे के समय चुनें। यह पेज खुला रहने पर ही याद चलेगी।",
        next: (time, left) => `अगली खुराक ${time} · ${left} बाद`,
        due: (time) => `${time} हो गया — खुराक का समय।`,
        h: " घंटे",
        m: " मिनट",
      },
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
      batchLabel: "Batch & expiry check",
      groundTruth: "Ground-Truth verified · offline database",
      reminder: {
        title: "Dose reminder",
        help:
          "Choose the times from the prescription. The reminder runs while this page stays open.",
        next: (time, left) => `Next dose ${time} · in ${left}`,
        due: (time) => `${time} — time for your dose.`,
        h: " h",
        m: " min",
      },
    },
  };

  const t = () => UI[language] || UI.ml;

  // ---------------------------------------------------------------------
  // State → screen
  // ---------------------------------------------------------------------
  const VERDICT_ICON = { critical: "⛔", caution: "⚠️", safe: "✅", unknown: "❓" };

  /** Box-level finding codes: these render in the banner above the verdict.
   *  Anything else is a combination warning and stays in the findings list. */
  const BATCH_CODES = {
    RECALLED_BATCH: "recall",
    EXPIRED_STOCK: "expired",
    EXPIRY_SOON: "expiring",
    EXPIRY_UNREADABLE: "unreadable",
    COLD_CHAIN_RISK: "cold",
  };

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

  /** A backend text object, in the language on screen. */
  function localised(text) {
    if (!text) return "";
    return text[language] || text.en || "";
  }

  /**
   * One card for one finding.
   *
   * The recall banner and the findings list render the same five elements with
   * different class prefixes (`batch-item` / `finding`), so they share a
   * builder: a warning cannot look or read differently depending on which list
   * it lands in, and there is one place to change if the card design does.
   */
  function findingNode(finding, prefix, options) {
    const settings = options || {};
    const item = document.createElement("li");
    item.className = [prefix, settings.severity ? finding.severity : "", settings.extraClass || ""]
      .filter(Boolean)
      .join(" ");

    const head = document.createElement("div");
    head.className = prefix + "-head";

    const badge = document.createElement("span");
    badge.className = "finding-badge";
    badge.textContent = (t().badge[finding.severity] || finding.severity).toUpperCase();

    const title = document.createElement("h3");
    title.className = prefix + "-title";
    title.textContent = localised(finding.title);

    head.appendChild(badge);
    head.appendChild(title);

    const message = document.createElement("p");
    message.className = prefix + "-message";
    message.textContent = localised(finding.message);

    const action = document.createElement("p");
    action.className = prefix + "-action";
    action.textContent = localised(finding.action);

    item.appendChild(head);
    item.appendChild(message);
    item.appendChild(action);

    if (settings.anchors && finding.anchors && finding.anchors.length) {
      const chipRow = document.createElement("div");
      chipRow.className = "anchors";
      finding.anchors.forEach((anchor) => {
        const chip = document.createElement("span");
        chip.className = "anchor-chip";
        const entry = settings.names && settings.names[anchor];
        // LASA anchors are printed labels, not molecules — show them verbatim.
        chip.textContent = entry ? entry[language] || entry.en : anchor;
        chipRow.appendChild(chip);
      });
      item.appendChild(chipRow);
    }

    return item;
  }

  /**
   * Render the batch/expiry banner.
   *
   * A recalled batch or an expired foil is not one warning among many: it is a
   * reason not to hand the box over at all, so it goes above the verdict, in
   * crimson, with its own action line — and the device voice reads it first
   * because it appears first in the findings the server spoke.
   */
  function renderBatchBanner(findings) {
    if (!els.batchBanner) return;
    els.batchBanner.hidden = !findings.length;
    els.batchBannerList.textContent = "";
    if (!findings.length) {
      els.batchBanner.className = "batch-banner";
      return;
    }
    const critical = findings.some((finding) => finding.severity === "critical");
    els.batchBanner.className = "batch-banner " + (critical ? "critical" : "warning");
    els.batchBannerLabel.textContent = t().batchLabel;

    findings.forEach((finding) => {
      els.batchBannerList.appendChild(
        findingNode(finding, "batch-item", { extraClass: BATCH_CODES[finding.code] })
      );
    });
  }

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

    // Box-level findings (recall, expiry, cold chain) live in the banner above
    // the verdict; everything else stays in the findings list below it.
    const allFindings = safety.findings || [];
    renderBatchBanner(allFindings.filter((finding) => BATCH_CODES[finding.code]));

    els.findings.textContent = "";
    allFindings
      .filter((finding) => !BATCH_CODES[finding.code])
      .forEach((finding) => {
        els.findings.appendChild(
          findingNode(finding, "finding", { severity: true, anchors: true, names })
        );
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

    // Provenance: the local ground truth answered this box, not the model. Only
    // shown when it actually happened, so the badge means something.
    if (els.gtBadge) {
      const verified = Boolean(payload.ground_truth_verified);
      els.gtBadge.hidden = !verified;
      els.gtText.textContent = verified ? t().groundTruth : "";
    }

    // Dose reminders belong to this scan: a different set of medicines drops the
    // previous in-memory plan, so a stale reminder can never name the wrong drug.
    if (reminderPlan && reminderLabels !== reminderLabelsFor(payload)) {
      clearReminder();
      if (els.reminderMsg) {
        els.reminderMsg.hidden = true;
        els.reminderMsg.textContent = "";
      }
    }
    if (els.reminderPanel) {
      const canRemind = medicines.some((medicine) => medicine.matched);
      els.reminderPanel.hidden = !canRemind;
      if (els.reminderHelp) {
        els.reminderHelp.textContent = canRemind ? t().reminder.help : "";
      }
      if (!canRemind) clearReminder();
    }
    renderReminderBanner();

    els.disclaimer.textContent = localised(payload.disclaimer);
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
  // Dose reminders: the server builds the plan, this tab keeps the clock
  // ---------------------------------------------------------------------
  let reminderPlan = null;
  let reminderLabels = "";
  let reminderTimer = null;
  let reminderDueAt = 0;

  function reminderLabelsFor(payload) {
    return ((payload && payload.medicines) || [])
      .map((medicine) => medicine.label)
      .filter(Boolean)
      .join("|");
  }

  function stopReminderClock() {
    if (reminderTimer) clearInterval(reminderTimer);
    reminderTimer = null;
  }

  /** Forget the plan: in-memory only, so this really is the end of it. */
  function clearReminder() {
    stopReminderClock();
    reminderPlan = null;
    reminderLabels = "";
    reminderDueAt = 0;
    if (els.reminderBanner) els.reminderBanner.hidden = true;
  }

  /** Show (or refresh) the countdown to the next dose, in the chosen language. */
  function renderReminderBanner() {
    if (!els.reminderBanner) return;
    if (!reminderPlan) {
      els.reminderBanner.hidden = true;
      return;
    }
    const next = Reminders.nextDose(reminderPlan.slots, Date.now());
    if (!next) {
      els.reminderBanner.hidden = true;
      return;
    }
    els.reminderBanner.hidden = false;
    els.reminderNext.textContent = t().reminder.next(
      next.slot.time,
      Reminders.formatLeft(next.inMs, t().reminder)
    );
    reminderDueAt = next.at;
  }

  /** Speak the dose and, when the phone allows it, post a local notification. */
  function announceDose(slot) {
    const speech = slot && slot.speech;
    const text = speech ? speech[language] || speech.en : "";
    if (!text) return;
    Promise.resolve(Speech.speak(text, language)).catch(() => undefined);
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        new Notification(t().reminder.title, { body: text, tag: "kathapulse-dose" });
      } catch (err) {
        // A browser that refuses notifications still gets the spoken reminder.
      }
    }
  }

  function reminderTick() {
    if (!reminderPlan) return;
    const now = Date.now();
    const next = Reminders.nextDose(reminderPlan.slots, now);
    if (!next) return;
    if (reminderDueAt && now >= reminderDueAt - 1000) announceDose(next.slot);
    renderReminderBanner();
  }

  function startReminderClock() {
    stopReminderClock();
    renderReminderBanner();
    reminderTimer = setInterval(reminderTick, 15000);
  }

  /** Ask the server for a plan (it stores nothing) and start the local clock. */
  async function scheduleReminder() {
    if (!lastPayload) return;
    const names = (lastPayload.medicines || [])
      .filter((medicine) => medicine.matched && medicine.label)
      .map((medicine) => medicine.label);
    if (!names.length) return;

    const pattern = els.pattern ? els.pattern.value : "1-0-1";
    if (els.scheduleBtn) els.scheduleBtn.disabled = true;
    els.reminderMsg.hidden = false;
    els.reminderMsg.textContent = t().busyCheck;

    try {
      const plan = await requestWithTimeout("/reminders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          medicines: names.map((name) => ({ name })),
          pattern,
          language,
        }),
      });

      if (!plan || !plan.scheduled) {
        clearReminder();
        els.reminderMsg.textContent =
          (plan && plan.message && (plan.message[language] || plan.message.en)) || "";
        return;
      }

      reminderPlan = plan;
      reminderLabels = reminderLabelsFor(lastPayload);
      els.reminderMsg.textContent = plan.message[language] || plan.message.en || "";
      startReminderClock();

      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "default" &&
        typeof Notification.requestPermission === "function"
      ) {
        Promise.resolve(Notification.requestPermission()).catch(() => undefined);
      }
    } catch (err) {
      const code = State.classifyError(err, { online: navigator.onLine !== false });
      els.reminderMsg.textContent = State.errorCopy(code, language);
      clearReminder();
    } finally {
      if (els.scheduleBtn) els.scheduleBtn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Speech
  // ---------------------------------------------------------------------

  /** Prefer the backend's flat contract, then the tri-lingual speech payload. */
  function spokenTextFor(payload) {
    if (!payload) return "";
    if (language === "ml" && payload.safety_message_ml) return payload.safety_message_ml;
    if (language === "hi" && payload.safety_message_hi) return payload.safety_message_hi;
    // English has its own flat script: falling back to `speech.text` here would
    // read the language the scan was taken in, even after an ml -> en switch.
    if (language === "en" && payload.safety_message_en) return payload.safety_message_en;
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

  /** Batch and expiry as typed by a pharmacist (empty strings when unused). */
  function manualBatch() {
    const value = (input) => (input && input.value ? input.value.trim() : "");
    return { batch_no: value(els.batchInput), expiry: value(els.expiryInput) };
  }

  /** Patient age, only when a sane number was typed: it enables the age rule. */
  function manualAge() {
    const raw = els.ageInput && els.ageInput.value ? els.ageInput.value.trim() : "";
    const years = Number(raw);
    if (!raw || !Number.isFinite(years) || years < 0 || years > 120) return {};
    return { age_years: Math.round(years) };
  }

  /**
   * Scan a list of medicine names and render (or fail) exactly like a photo.
   *
   * @param {string[]} names printed names, as typed or preset
   * @param {() => unknown} [onRetry] what Retry should run; repeating this
   *        same scan by default.
   * @param {{batch_no: string, expiry: string}} [batch] printed batch/expiry,
   *        applied to every name in this scan (one shelf box, one batch).
   * @param {object} [extra] request-level fields (age), never per medicine.
   */
  async function runNamedScan(names, onRetry, batch, extra) {
    if (State.isBusy(state) || !names || !names.length) return;
    const box = batch || { batch_no: "", expiry: "" };

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
        body: JSON.stringify({
          medicines: names.map((name) => ({ name, ...box })),
          language,
          ...(extra || {}),
        }),
      });
      dispatch("UPLOAD_OK");
      renderResult(payload);
    } catch (err) {
      failWith(
        "UPLOAD_FAIL",
        err,
        onRetry || (() => runNamedScan(names, undefined, box, extra))
      );
    }
  }

  function submitManual(event) {
    event.preventDefault();
    const names = parseManualNames();
    if (!names.length) return;
    // Retry re-submits the form, so an edit made after the failure is honoured.
    return runNamedScan(
      names,
      () => els.manualForm.requestSubmit(),
      manualBatch(),
      manualAge()
    );
  }

  // ---------------------------------------------------------------------
  // Demo presets: a live pitch cannot depend on a camera or a physical strip
  // ---------------------------------------------------------------------
  const DEMO_PRESETS = {
    "dup-lasa": { names: ["Telma 40", "Telma-H 40/12.5"] },
    "dup-para": { names: ["Dolo 650", "Crocin Cold & Flu"] },
    "lasa-alone": { names: ["Amaryl 1 mg"] },
    // Pharmacy audit: a recalled metformin batch that has also passed its date.
    "batch-recall": {
      names: ["Glycomet 500"],
      batch_no: "GM2407A",
      expiry: "09/2026",
    },
    // Ground truth: the alias table alone would answer "metformin" and drop the
    // glimepiride, so the verified-database badge appears here.
    "ground-truth": { names: ["Glycomet GP"] },
  };

  /** Run the preset behind a `data-demo` id; unknown ids are ignored. */
  function runPreset(id) {
    const preset = DEMO_PRESETS[id];
    if (!preset) return undefined;
    return runNamedScan(preset.names, () => runPreset(id), {
      batch_no: preset.batch_no || "",
      expiry: preset.expiry || "",
    });
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

  // Dose reminders: schedule for the scan on screen, cancel at any time.
  if (els.scheduleBtn) els.scheduleBtn.addEventListener("click", scheduleReminder);
  if (els.cancelReminderBtn) {
    els.cancelReminderBtn.addEventListener("click", () => {
      clearReminder();
      if (els.reminderMsg) {
        els.reminderMsg.hidden = false;
        els.reminderMsg.textContent = "";
      }
    });
  }
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
