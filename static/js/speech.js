/* KathaPulse AI — Web Speech API layer for Malayalam and Hindi hazard alerts.
 *
 * Practical notes for low-end Android
 * -----------------------------------
 * 1. `speechSynthesis` exists on almost every Android Chrome build, but the
 *    *voice* for ml-IN / hi-IN may be missing.  We detect that and tell the
 *    user to install the language voice instead of silently reading English
 *    text with a Malayalam flag on screen.
 * 2. Android cuts off a single long utterance (roughly >200 characters).
 *    We split on sentence boundaries and queue chunks with a short gap,
 *    which also gives the listener breathing room between warnings.
 * 3. Text is read at 0.85x — elderly listeners need the slower pace, and
 *    drug names are unfamiliar words, not conversational ones.
 */

(function () {
  "use strict";

  const CHUNK_TARGET = 170; // characters per utterance
  const RATE = 0.85;

  const LANG_TAG = {
    ml: "ml-IN",
    hi: "hi-IN",
    en: "en-IN",
  };
  const LANG_PREFIX = { ml: "ml", hi: "hi", en: "en" };

  let queue = [];
  let speaking = false;

  function isSupported() {
    return typeof window !== "undefined" && "speechSynthesis" in window;
  }

  function voicesFor(lang) {
    if (!isSupported()) return [];
    const tag = LANG_TAG[lang] || lang;
    const prefix = LANG_PREFIX[lang] || lang;
    return window.speechSynthesis
      .getVoices()
      .filter(
        (voice) =>
          voice.lang &&
          (voice.lang.toLowerCase() === tag.toLowerCase() ||
            voice.lang.toLowerCase().startsWith(prefix + "-") ||
            voice.lang.toLowerCase() === prefix)
      );
  }

  /** True when a device voice matching the requested language is installed. */
  function hasVoiceFor(lang) {
    if (!isSupported()) return false;
    if (lang === "en") return true;
    return voicesFor(lang).length > 0;
  }

  /** Split long text on sentence ends, then on commas, never mid-word. */
  function chunkText(text) {
    const sentences = String(text)
      .replace(/\s+/g, " ")
      .match(/[^.!?।]+[.!?।]?/g) || [text];

    const chunks = [];
    let current = "";

    for (const sentence of sentences) {
      const piece = sentence.trim();
      if (!piece) continue;
      if ((current + " " + piece).trim().length <= CHUNK_TARGET) {
        current = (current + " " + piece).trim();
        continue;
      }
      if (current) chunks.push(current);
      if (piece.length <= CHUNK_TARGET) {
        current = piece;
      } else {
        // Long sentence: fall back to word packing.
        current = "";
        let line = "";
        for (const word of piece.split(" ")) {
          if ((line + " " + word).trim().length > CHUNK_TARGET) {
            if (line) chunks.push(line);
            line = word;
          } else {
            line = (line + " " + word).trim();
          }
        }
        current = line;
      }
    }
    if (current) chunks.push(current);
    return chunks;
  }

  function pickVoice(lang) {
    const candidates = voicesFor(lang);
    if (!candidates.length) return null;
    // Prefer a local (on-device, works offline) voice.
    return candidates.find((v) => v.localService) || candidates[0];
  }

  function speakChunk(chunk, lang) {
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = LANG_TAG[lang] || lang;
      utterance.rate = RATE;
      utterance.pitch = 1;
      utterance.volume = 1;

      const voice = pickVoice(lang);
      if (voice) utterance.voice = voice;

      utterance.onend = () => setTimeout(resolve, 220);
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    });
  }

  /**
   * Speak `text` in `lang`.
   * Returns { ok: boolean, reason?: "unsupported" | "no-voice" }.
   */
  async function speak(text, lang) {
    if (!isSupported()) return { ok: false, reason: "unsupported" };
    if (lang !== "en" && !hasVoiceFor(lang)) {
      return { ok: false, reason: "no-voice" };
    }

    stop();
    queue = chunkText(text);
    speaking = true;

    for (let i = 0; i < queue.length && speaking; i += 1) {
      await speakChunk(queue[i], lang);
    }
    speaking = false;
    return { ok: true };
  }

  function stop() {
    if (!isSupported()) return;
    queue = [];
    speaking = false;
    window.speechSynthesis.cancel();
  }

  function isSpeaking() {
    return isSupported() && (window.speechSynthesis.speaking || speaking);
  }

  // Voice lists load asynchronously on Chrome; warm them up early.
  if (isSupported()) {
    window.speechSynthesis.getVoices();
    if (typeof window.speechSynthesis.addEventListener === "function") {
      window.speechSynthesis.addEventListener("voiceschanged", () => {
        window.speechSynthesis.getVoices();
      });
    }
  }

  window.KathaPulseSpeech = {
    speak,
    stop,
    hasVoiceFor,
    isSupported,
    isSpeaking,
    chunkText,
    LANG_TAG,
  };
})();
