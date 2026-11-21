/* KathaPulse AI — local audio pack (draft tier).
 *
 * Why this file exists
 * --------------------
 * `speech.js` reads warnings with the Web Speech API. That works only when the
 * phone has a Malayalam or Hindi voice installed; on the cheapest Android
 * builds it does not, and the app degrades to "install the voice" text. The
 * local audio pack removes that dependency: short, human-recorded (later: WASM
 * synthesised) clips shipped with the app and played through <audio>.
 *
 * What is here now
 * ----------------
 * The loader, the manifest contract and the playback tier. The manifest at
 * `/static/audio/manifest.json` ships with **zero clips**, so `play()` answers
 * `unavailable` and the caller keeps its current fallback chain. Nothing about
 * today's behaviour changes until real clips are added — that is deliberate, so
 * the safety path never depends on an empty pack.
 *
 * Manifest contract (schema 1)
 * ----------------------------
 *   {
 *     "schema": 1,
 *     "version": "3",                  // bump when any clip changes
 *     "voice": {"name": "...", "license": "..."},
 *     "clips": { "ml:DUPLICATE_SALT": "/static/audio/ml/DUPLICATE_SALT.webm" }
 *   }
 *
 * Keys are `<language>:<finding.code>`, plus `<language>:intro` and
 * `<language>:outro` for the speech frame. Format: Opus in WebM, mono, 24 kbps.
 *
 * Fallback order the caller should use:
 *   AudioPack.play(...)      → "played"
 *   Speech.speak(...)        → device voice
 *   reversed.danger.warning  → the written warning already on screen
 */

(function (global) {
  "use strict";

  const MANIFEST_URL = "/static/audio/manifest.json";

  let manifest = null;
  let pending = null;
  let lastError = null;
  let current = null;

  function emptyManifest(reason) {
    return { schema: 0, version: "0", voice: null, clips: {}, reason: reason || "unavailable" };
  }

  /** Keep only plausible relative clip paths; a manifest is still input. */
  function cleanClips(clips) {
    const clean = {};
    if (!clips || typeof clips !== "object") return clean;
    Object.keys(clips).forEach(function (key) {
      const value = clips[key];
      if (typeof value === "string" && value && !value.includes("..")) clean[key] = value;
    });
    return clean;
  }

  function load(url) {
    if (manifest) return Promise.resolve(manifest);
    if (pending) return pending;

    pending = (function () {
      const target = url || MANIFEST_URL;
      if (typeof global.fetch !== "function") {
        lastError = new Error("fetch unavailable");
        manifest = emptyManifest("fetch unavailable");
        pending = null;
        return Promise.resolve(manifest);
      }
      return global
        .fetch(target, { cache: "force-cache" })
        .then(function (response) {
          if (!response || !response.ok) {
            throw new Error("manifest " + (response ? response.status : "error"));
          }
          return response.json();
        })
        .then(function (data) {
          if (!data || typeof data !== "object") throw new Error("manifest shape");
          manifest = {
            schema: Number(data.schema) || 0,
            version: String(data.version || "0"),
            voice: data.voice || null,
            clips: cleanClips(data.clips),
          };
          lastError = null;
          return manifest;
        })
        .catch(function (err) {
          // A broken or absent pack must never break the warning path.
          lastError = err;
          manifest = emptyManifest(err && err.message);
          return manifest;
        })
        .then(function (result) {
          pending = null;
          return result;
        });
    })();

    return pending;
  }

  function key(lang, code) {
    return String(lang) + ":" + String(code);
  }

  function clipFor(lang, code) {
    return load().then(function (data) {
      return data.clips[key(lang, code)] || null;
    });
  }

  function canPlay(lang, code) {
    return clipFor(lang, code).then(function (path) {
      return path !== null;
    });
  }

  function stop() {
    if (!current) return;
    try {
      current.audio.pause();
    } catch (err) {
      /* a paused/dead element is not an error worth surfacing */
    }
    current = null;
  }

  /**
   * Play one clip. Never throws: resolves
   *   {status: "played"|"unavailable"|"blocked"|"unsupported", clip?, reason?}
   * so the caller can walk its fallback chain without try/catch.
   */
  function play(lang, code, options) {
    return clipFor(lang, code).then(function (path) {
      if (!path) {
        return {
          status: "unavailable",
          reason: lastError ? String(lastError.message) : "no clip for " + key(lang, code),
        };
      }
      if (typeof global.Audio !== "function") {
        return { status: "unsupported", clip: path };
      }

      stop();
      const audio = new global.Audio(path);
      audio.preload = "auto";
      if (options && typeof options.rate === "number" && "playbackRate" in audio) {
        audio.playbackRate = options.rate;
      }
      current = { audio: audio, src: path };

      let started;
      try {
        started = audio.play();
      } catch (err) {
        current = null;
        return { status: "blocked", clip: path, reason: String((err && err.message) || err) };
      }

      return Promise.resolve(started)
        .then(function () {
          return { status: "played", clip: path };
        })
        .catch(function (err) {
          // Autoplay policy rejects until the user has interacted; the caller
          // still has SpeechSynthesis and the on-screen warning.
          current = null;
          return { status: "blocked", clip: path, reason: String((err && err.message) || err) };
        });
    });
  }

  /**
   * Play one clip and wait for it to finish before resolving, so a script of
   * several clips is a script and not a pile-up. Resolves the same statuses as
   * play(), plus "timeout"/"failed" if the element never reports an end.
   */
  function playToEnd(lang, code, options) {
    return play(lang, code, options).then(function (result) {
      if (result.status !== "played") return result;
      const audio = current && current.audio;
      if (!audio || typeof audio.addEventListener !== "function") return result;
      return new Promise(function (resolve) {
        let settled = false;
        const finish = function (status) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve({ status: status, clip: result.clip });
        };
        // A clip that never fires `ended` must not hang the warning path.
        const timer = setTimeout(function () {
          finish("timeout");
        }, 15000);
        audio.addEventListener("ended", function () {
          finish("played");
        });
        audio.addEventListener("error", function () {
          finish("failed");
        });
      });
    });
  }

  /**
   * Play intro → one clip per finding code → outro.
   *
   * All-or-nothing: if any clip is missing, nothing is played and the caller
   * keeps its device-voice fallback. A half-spoken warning (intro then silence)
   * is worse than a synthetic one that reads the whole thing.
   */
  async function playScript(lang, codes, options) {
    const sequence = ["intro"].concat(codes || [], ["outro"]);
    const available = await Promise.all(
      sequence.map(function (keyOrCode) {
        return canPlay(lang, keyOrCode);
      })
    );
    const missing = sequence.filter(function (_, index) {
      return !available[index];
    });
    if (missing.length) {
      return { status: "unavailable", missing: missing, played: 0 };
    }
    for (let index = 0; index < sequence.length; index += 1) {
      const result = await playToEnd(lang, sequence[index], options);
      if (result.status !== "played") {
        return {
          status: result.status,
          clip: result.clip || null,
          played: index,
          reason: result.reason || null,
        };
      }
    }
    return { status: "played", played: sequence.length };
  }

  function status() {
    return {
      loaded: manifest !== null,
      version: manifest ? manifest.version : null,
      clips: manifest ? Object.keys(manifest.clips).length : 0,
      error: lastError ? String(lastError.message) : null,
    };
  }

  global.AudioPack = {
    MANIFEST_URL: MANIFEST_URL,
    load: load,
    canPlay: canPlay,
    play: play,
    playToEnd: playToEnd,
    playScript: playScript,
    stop: stop,
    status: status,
    key: key,
  };
})(typeof window !== "undefined" ? window : globalThis);
