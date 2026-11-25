/* KathaPulse AI — dose-reminder clock.
 *
 * Pure date arithmetic, no DOM and no storage, so it can be unit-tested in Node
 * exactly as the browser runs it:
 *
 *   nextDose(slots, now)   the next upcoming HH:MM, tomorrow if it has passed
 *   formatLeft(ms, units)  "3 h 12 min" in the selected language
 *   isDue(next, now)       whether that dose has been reached
 *
 * The plan itself lives in a variable inside app.js and dies with the tab. There
 * is no localStorage here on purpose: a dose schedule is health data, and this
 * build keeps it in volatile memory only (matching the server's zero-persistence
 * posture). A browser cannot wake a closed tab, so the UI says "keep this page
 * open" rather than pretending it has a push service.
 */

(function (global) {
  "use strict";

  const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/;

  function parseTime(time) {
    const match = HHMM.exec(String(time || ""));
    if (!match) return null;
    return { hours: Number(match[1]), minutes: Number(match[2]) };
  }

  /**
   * Next upcoming dose from `slots` at or after `now`.
   * A slot earlier today rolls to tomorrow, so a 24-hour rotation works.
   * @param {Array<{time: string}>} slots
   * @param {number} now epoch milliseconds
   * @returns {{slot: object, at: number, inMs: number} | null}
   */
  function nextDose(slots, now) {
    if (!Array.isArray(slots) || !slots.length) return null;
    const base = new Date(now);
    let best = null;

    for (const slot of slots) {
      const parsed = parseTime(slot && slot.time);
      if (!parsed) continue;
      const at = new Date(base.getTime());
      at.setHours(parsed.hours, parsed.minutes, 0, 0);
      if (at.getTime() <= now) at.setDate(at.getDate() + 1);
      if (!best || at.getTime() < best.at) {
        best = { slot, at: at.getTime() };
      }
    }

    if (!best) return null;
    return { slot: best.slot, at: best.at, inMs: best.at - now };
  }

  /** "3 h 12 min" / "3 മണിക്കൂർ 12 മിനിറ്റ്" — units come from the UI copy. */
  function formatLeft(ms, units) {
    const labels = units || {};
    const hourWord = typeof labels.h === "string" ? labels.h : "h";
    const minuteWord = typeof labels.m === "string" ? labels.m : "min";
    const totalMinutes = Math.max(0, Math.round(Number(ms || 0) / 60000));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours <= 0) return `${minutes}${minuteWord}`;
    return `${hours}${hourWord} ${minutes}${minuteWord}`;
  }

  /** True when the dose time has been reached (one second of tolerance). */
  function isDue(next, now) {
    if (!next || typeof next.at !== "number") return false;
    return now >= next.at - 1000;
  }

  /**
   * Which language and text a due dose should be announced in.
   *
   * A phone with no Malayalam/Hindi voice used to make the reminder silent,
   * which is the one failure a dose alarm cannot have. When the selected
   * language has no installed voice, the English recording is used instead; the
   * caller still prints the text, so the dose is heard or read either way. The
   * language is only relabelled when that fallback text really is English.
   *
   * @param {object} speech slot.speech: { en, ml, hi }
   * @param {string} lang selected language code
   * @param {boolean} hasVoice whether the device has a voice for `lang`
   * @returns {{language: string, text: string} | null}
   */
  function doseAnnouncement(speech, lang, hasVoice) {
    if (!speech) return null;
    const voiceReady = lang === "en" || Boolean(hasVoice);
    // Preferred order: the selected language; English when its voice is
    // missing; then whatever the plan actually carries. The returned language
    // always matches the text, so the synthesizer is never told to read
    // Malayalam with a Hindi voice.
    const order = voiceReady
      ? [lang, "en", "ml", "hi"]
      : ["en", lang, "ml", "hi"];
    for (const code of order) {
      if (speech[code]) return { language: code, text: speech[code] };
    }
    return null;
  }

  global.KathaPulseReminders = {
    nextDose,
    formatLeft,
    isDue,
    parseTime,
    doseAnnouncement,
  };
})(window);
