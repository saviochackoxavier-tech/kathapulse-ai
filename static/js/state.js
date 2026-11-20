/* KathaPulse AI — client state machine and error classification.
 *
 * Deliberately pure: no DOM, no fetch, no globals.  That makes the whole scan
 * lifecycle testable in Node (tests/js/state.test.mjs) and keeps the screen
 * logic in app.js to "render what the state says".
 *
 * Lifecycle:
 *
 *   idle ──CAMERA_OPENED──▶ camera_ready ──CAPTURE_START──▶ capturing
 *     ▲                            │                              │
 *     │                            └──────────CAMERA_CLOSED──────┘
 *     │                                                           │
 *     │                                                    CAPTURE_DONE
 *     │                                                           ▼
 *     │   FILE_SELECTED ─────────────────────────────────────▶ scrubbing
 *     │                                                           │
 *     │                                                      SCRUB_DONE
 *     │                                                           ▼
 *     │                                                       uploading
 *     │                                                           │
 *     │                          UPLOAD_FAIL                 UPLOAD_OK
 *     │                                │                          │
 *     │                                ▼                          ▼
 *     │                             error ◀──(any failure)──  rendering ──▶ speaking ──▶ idle
 *     │                                └──────RETRY──────▶ idle
 */

(function () {
  "use strict";

  const STATES = Object.freeze({
    IDLE: "idle",
    CAMERA_READY: "camera_ready",
    CAPTURING: "capturing",
    SCRUBBING: "scrubbing",
    UPLOADING: "uploading",
    RENDERING: "rendering",
    SPEAKING: "speaking",
    ERROR: "error",
  });

  // Transition table. Anything not listed is a no-op, which keeps a late event
  // (a stray shutter tap, a resolved promise after reset) from corrupting the
  // screen.
  const TRANSITIONS = Object.freeze({
    idle: {
      CAMERA_OPENED: STATES.CAMERA_READY,
      CAMERA_FAILED: STATES.ERROR,
      FILE_SELECTED: STATES.SCRUBBING,
    },
    camera_ready: {
      CAPTURE_START: STATES.CAPTURING,
      CAMERA_CLOSED: STATES.IDLE,
      CAMERA_FAILED: STATES.ERROR,
      FILE_SELECTED: STATES.SCRUBBING,
    },
    capturing: {
      CAPTURE_DONE: STATES.SCRUBBING,
      CAPTURE_FAILED: STATES.ERROR,
      CAMERA_CLOSED: STATES.IDLE,
    },
    scrubbing: {
      SCRUB_DONE: STATES.UPLOADING,
      SCRUB_FAILED: STATES.ERROR,
      RESET: STATES.IDLE,
    },
    uploading: {
      UPLOAD_OK: STATES.RENDERING,
      UPLOAD_FAIL: STATES.ERROR,
      RESET: STATES.IDLE,
    },
    rendering: {
      SPEECH_START: STATES.SPEAKING,
      SPEECH_SKIPPED: STATES.IDLE,
      FILE_SELECTED: STATES.SCRUBBING,
      RESET: STATES.IDLE,
    },
    speaking: {
      SPEECH_END: STATES.IDLE,
      FILE_SELECTED: STATES.SCRUBBING,
      CAPTURE_START: STATES.CAPTURING,
      CAMERA_OPENED: STATES.CAMERA_READY,
      RESET: STATES.IDLE,
    },
    error: {
      RETRY: STATES.IDLE,
      FILE_SELECTED: STATES.SCRUBBING,
      CAMERA_OPENED: STATES.CAMERA_READY,
      RESET: STATES.IDLE,
    },
    // Wildcard: true emergencies (an uncaught throw, an unhandled rejection)
    // must reach the error screen from any state, including idle.
    "*": {
      FATAL: STATES.ERROR,
    },
  });

  const BUSY_STATES = new Set([STATES.CAPTURING, STATES.SCRUBBING, STATES.UPLOADING]);

  //: Which progress step the UI highlights, 0-based. -1 hides the stepper.
  const STEP_INDEX = {
    idle: -1,
    camera_ready: -1,
    capturing: 0,
    scrubbing: 0,
    uploading: 1,
    rendering: 2,
    speaking: 2,
    error: -1,
  };

  function create() {
    return { name: STATES.IDLE, error: null, lastEvent: null };
  }

  /** Apply an event. Returns a new state object; never throws. */
  function transition(state, event, error) {
    const current = state && state.name ? state.name : STATES.IDLE;
    const map = TRANSITIONS[current] || {};
    const next = map[event] || (TRANSITIONS["*"] || {})[event];

    if (!next) {
      // Unknown or out-of-order event: keep the current screen, but remember
      // it so debugging a stuck UI is possible from the console.
      return { name: current, error: state ? state.error : null, lastEvent: event };
    }

    return {
      name: next,
      error: next === STATES.ERROR ? error || state?.error || null : null,
      lastEvent: event,
    };
  }

  function isBusy(state) {
    return !!state && BUSY_STATES.has(state.name);
  }

  function stepIndex(state) {
    if (!state) return -1;
    const index = STEP_INDEX[state.name];
    return typeof index === "number" ? index : -1;
  }

  // ---------------------------------------------------------------------
  // Error classification -> a stable code the UI can localise
  // ---------------------------------------------------------------------

  /**
   * Turn a thrown fetch/encode error into one of a fixed set of codes.
   * Pure: the network state is passed in, not read from navigator.
   *
   * @param {Error & {status?: number}} error
   * @param {{online?: boolean}} context
   * @returns {string}
   */
  function classifyError(error, context) {
    const online = !context || context.online !== false;
    const name = error && error.name;
    const status = error && error.status;

    if (name === "AbortError") return "timeout";
    if (!online) return "offline";
    if (status === 413) return "too_large";
    if (status === 415) return "bad_type";
    if (status === 400 || status === 422) return "bad_request";
    if (typeof status === "number" && status >= 500) return "server";
    if (name === "TypeError") return "network"; // fetch rejected: no connection
    if (name === "KathaImageError") return "image_failed";
    return "unknown";
  }

  // ---------------------------------------------------------------------
  // Localised copy for every failure — the offline fallback the Inspector asks
  // for. Never falls back to English-only.
  // ---------------------------------------------------------------------

  const ERROR_COPY = {
    timeout: {
      ml: "സർവർ സമയത്തിനുള്ളിൽ മറുപടി നൽകിയില്ല. ഇന്റർനെറ്റ് പരിശോധിച്ച് വീണ്ടും ശ്രമിക്കുക.",
      hi: "सर्वर ने समय पर जवाब नहीं दिया। इंटरनेट जाँचकर फिर कोशिश करें।",
      en: "The server did not answer in time. Check your connection and try again.",
    },
    offline: {
      ml: "ഇന്റർനെറ്റ് ഇല്ല. കണക്ഷൻ വന്നതിന് ശേഷം വീണ്ടും ശ്രമിക്കുക.",
      hi: "इंटरनेट नहीं है। कनेक्शन आने पर फिर कोशिश करें।",
      en: "You are offline. Try again once the connection is back.",
    },
    network: {
      ml: "സർവറുമായി ബന്ധപ്പെടാനായില്ല. വീണ്ടും ശ്രമിക്കുക.",
      hi: "सर्वर से संपर्क नहीं हुआ। फिर कोशिश करें।",
      en: "Could not reach the server. Please try again.",
    },
    too_large: {
      ml: "ഫോട്ടോ വളരെ വലുതാണ്. അൽപ്പം അടുത്തുനിന്ന് വീണ്ടും എടുക്കുക.",
      hi: "फ़ोटो बहुत बड़ी है। थोड़ा पास से फिर लें।",
      en: "That photo is too large. Move a little closer and take it again.",
    },
    bad_type: {
      ml: "ഈ ഫയൽ ഒരു ചിത്രമല്ല. JPEG അല്ലെങ്കിൽ PNG ഫോട്ടോ ഉപയോഗിക്കുക.",
      hi: "यह फ़ाइल तस्वीर नहीं है। JPEG या PNG फ़ोटो इस्तेमाल करें।",
      en: "That file is not an image. Use a JPEG or PNG photo.",
    },
    bad_request: {
      ml: "അയച്ച വിവരങ്ങൾ സ്വീകരിച്ചില്ല. പേര് വീണ്ടും പരിശോധിക്കുക.",
      hi: "भेजी गई जानकारी स्वीकार नहीं हुई। नाम फिर जाँचें।",
      en: "The request was rejected. Check the medicine name and try again.",
    },
    server: {
      ml: "സർവറിൽ തകരാർ. അൽപ്പസമയത്തിന് ശേഷം വീണ്ടും ശ്രമിക്കുക.",
      hi: "सर्वर में गड़बड़ी है। थोड़ी देर बाद फिर कोशिश करें।",
      en: "The server had a problem. Try again in a moment.",
    },
    image_failed: {
      ml: "ചിത്രം തയ്യാറാക്കാനായില്ല. വീണ്ടും ഫോട്ടോ എടുക്കുക.",
      hi: "तस्वीर तैयार नहीं हो सकी। फिर फ़ोटो लें।",
      en: "The photo could not be prepared. Please take it again.",
    },
    camera_denied: {
      ml: "ക്യാമറ അനുവാദം ലഭിച്ചില്ല. ബ്രൗസർ സെറ്റിംഗ്സിൽ ക്യാമറ അനുവദിക്കുക, അല്ലെങ്കിൽ ‘ചിത്രം തിരഞ്ഞെടുക്കുക’ ഉപയോഗിക്കുക.",
      hi: "कैमरा की अनुमति नहीं मिली। ब्राउज़र सेटिंग्स में कैमरा चालू करें, या ‘फ़ोटो चुनें’ इस्तेमाल करें।",
      en: "Camera permission was refused. Allow the camera in browser settings, or use ‘Choose photo’.",
    },
    unknown: {
      ml: "എന്തോ കുഴപ്പം സംഭവിച്ചു. വീണ്ടും ശ്രമിക്കുക.",
      hi: "कुछ गड़बड़ हुई। फिर कोशिश करें।",
      en: "Something went wrong. Please try again.",
    },
  };

  /** Localised message for an error code, with an English floor. */
  function errorCopy(code, language) {
    const entry = ERROR_COPY[code] || ERROR_COPY.unknown;
    return entry[language] || entry.en;
  }

  /** Short, localised label for the retry button. */
  const RETRY_COPY = {
    ml: "വീണ്ടും ശ്രമിക്കുക",
    hi: "फिर कोशिश करें",
    en: "Try again",
  };

  window.KathaPulseState = {
    STATES,
    TRANSITIONS,
    BUSY_STATES,
    create,
    transition,
    isBusy,
    stepIndex,
    classifyError,
    errorCopy,
    RETRY_COPY,
    ERROR_COPY,
  };
})();
