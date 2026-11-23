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

  global.KathaPulseReminders = { nextDose, formatLeft, isDue, parseTime };
})(window);
