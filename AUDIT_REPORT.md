# KathaPulse AI — Pass 24 Audit Report

**Scope:** end-to-end audit of the running prototype (`0.0.0.0:3004`), plus a new
permanent DOM-level integration test for the local audio pack.
**Date:** 21 November 2026
**Build audited:** `v1.1.6` (from `v1.1.5`), branch `freebuff/634aa3b468f03b91c44ddefa`

---

## 1. Summary

| Area | Result |
|---|---|
| New DOM audio test `tests/js/audiopack.test.mjs` | **14/14 checks pass** |
| Defects found by that test and fixed | **2** (dead tier 0 on cold start; no STOP during clip playback) |
| Backend suite | **132 passed** |
| Frontend suites (6 files) | **70 checks passed** |
| Disk writes attributable to any request path | **0** |
| Responsive audit (3 languages × 4 widths) | **12/12 clean**, 0 overflow, 0 tap targets under 44 px |
| Vision tier | **still unverified against Groq** — `KATHA_VISION_API_KEY` is empty in this environment |

The two most important findings were not cosmetic: the shipped audio tier could
never run on a real page load, and a warning played from clips had no way to be
stopped.

---

## 2. DOM-level audio integration test

`tests/js/audiopack.test.mjs` — 14 checks, no server, no network, ~1 s.

It boots the **real** `static/index.html`, `state.js`, `audio-pack.js` and
`app.js` in jsdom. Only the edges are faked: `fetch` (manifest + one payload
captured from `POST /verify-medicines`, in `tests/js/fixtures/duplasa.json`), the
`<audio>` element, device speech and the camera. Nothing about the code under
test is stubbed — in particular `AudioPack` is the shipped module, not a fake,
and `app.js` is what decides whether to call it.

| # | Check | What it pins |
|---|---|---|
| 1 | manifest fetched at boot, before the first LISTEN | tier 0 is warm on a cold page |
| 2 | `playScript` called with `ml` + `["DUPLICATE_SALT","LASA_RISK"]` | the app→pack contract |
| 3 | intro → finding → finding → outro order, device voice silent | sequencing, no double speech |
| 4 | Hindi selection requests Hindi clips | language is not hardcoded |
| 5 | a playing script offers STOP, and STOP stops the pack | a 30 s warning is interruptible |
| 6 | LISTEN replays the whole script | replay path |
| 7 | empty manifest → `playScript` skipped, device voice speaks the API script | fallback tier 1 |
| 8 | manifest missing only `outro` → nothing plays, device voice takes over | all-or-nothing script |
| 9 | pack that throws → warning still spoken, no unhandled error | a broken pack cannot silence a warning |
| 10 | no `AudioPack` at all (stale cached bundle) → speech still works | forward/backward compatibility |
| 11 | no pack + no speech support → written warning promoted | terminal fallback |
| 12 | no Malayalam voice → text fallback, never English audio | no wrong-language speech |
| 13 | offline manifest fetch → device voice | offline behaviour |
| 14 | warm-up + scan raise nothing unhandled | no error leaks |

### Defects the test found (both fixed)

1. **Tier 0 was unreachable on a cold page.** `tryAudioPack()` returned early
   when `AudioPack.status().clips === 0`, but nothing ever called
   `AudioPack.load()`, so `clips` was always 0 until *after* the first attempt.
   A populated manifest would therefore have played zero clips forever.
   *Fix:* warm the manifest at boot (`app.js`, best-effort, failures ignored) and
   skip only an **already-loaded empty** pack. `playScript` still loads lazily.
2. **No STOP while clips played.** The pack branch returned before
   `stopBtn.hidden = false`, so a user could not interrupt a playing warning —
   an accessibility regression against the elderly-use requirement.
   *Fix:* offer STOP for the duration of a clip script and hide it afterwards.

Both are now pinned by the test (checks 1 and 5), which fails 5/14 against the
pre-fix code and 14/14 after it.

Supporting change: `static/sw.js` cache bumped `kathapulse-v3` → `v4` so phones
pick up the patched `app.js`. `tests/test_audio_pack.py` now asserts a version
**floor** (`>= 3`) instead of a literal, so a legitimate bump stops breaking the
suite while the invariant (a versioned cache that carries the pack) is kept.

---

## 3. Security & privacy

### 3.1 Zero-persistence image handling

Every request path was executed with a filesystem marker taken first, then
compared:

| Path | Probes |
|---|---|
| `POST /verify-strip` | real JPEG upload |
| `POST /verify-strips/batch` | 2-strip basket |
| `POST /verify-medicines` | typed names |
| Rejected inputs | bad language, out-of-range paracetamol, empty list, wrong MIME, 6-strip basket |

Result: **no new file under `/tmp`, no new file in the project tree, 0
deleted-but-open file descriptors** on the serving process. `tempfile`,
`NamedTemporaryFile` and `mkstemp` do not appear anywhere in `app/`; the only
image decode is `PIL.Image.open(io.BytesIO(...))` in the OCR tier. Uploads are
read into `bytes`, analysed, and dropped with the request.

### 3.2 Schema enforcement (Pydantic, measured live)

| Probe | Status | Meaning |
|---|---|---|
| `language: "zz"` | **422** | enum rejects unknown languages |
| `paracetamol_taken_today_mg: 99999` | **422** | `le=20000` cap holds |
| `medicines: []` | **422** | an empty scan is not a "safe" verdict |
| `image` as `text/plain` | **415** | content-type allowlist |
| 6-strip basket | **413** | `MAX_STRIPS_PER_BATCH = 5` |

Vision output is likewise treated as untrusted: `parse_model_json` tolerates
fences but requires a JSON object, `_VisionResult`/`_VisionMedicine` cap list
lengths and string lengths, and `_clean()` strips control characters.

### 3.3 Secret hygiene

`KATHA_VISION_API_KEY` is read per request, never logged, never returned;
`/health` exposes only whether a tier is configured. `.env` is gitignored
(`git check-ignore -v .env` → `.gitignore:5`). No key value appears in any
tracked file, and the Pass 23 stand-in used a throwaway in-process value that
was never written to disk.

**Caveat, unchanged from Pass 23:** this deployment's key is empty
(`KATHA_VISION_API_KEY=`), so `/health` reports `vision_model: null` and photo
scans return `manual_required`. The tier has been proven over real HTTP against
a local Groq-shaped endpoint, not against Groq itself.

### 3.4 Surface reduction

`/docs`, `/redoc`, `/openapi.json` return `404` with `no-store` unless
`KATHA_DOCS_ENABLED=1` (verified live: all three 404). A sliding-window limiter
exists in-process but defaults off (`KATHA_RATE_LIMIT_PER_MIN=0`) because the
edge owns the budget; `deploy/nginx.kathapulse.conf` sets `limit_req 30r/m`.

---

## 4. PWA offline caching

`static/sw.js` (`kathapulse-v4`) precaches the shell, CSS, the five JS modules,
the taxonomy feed and the audio manifest. Navigations are network-first with a
cached fallback; static assets are stale-while-revalidate; non-GET requests
bypass the cache entirely, so no scan is ever written to Cache Storage. Old
caches are deleted on activation.

Verified in this pass: after clearing every cache and unregistering the old
worker, the app reloaded, re-registered and rendered — the multi-strip and
speech paths worked from the fresh code.

---

## 5. Multi-strip parsing

`POST /verify-strips/batch` accepts 1–5 uploads, analyses each in RAM, and
returns per-strip reports plus a combined verdict.

* 5 strips → `200`, `strip_count: 5`
* 6 strips → `413`
* 2 identical Telma photos → combined `critical`, flags `[DUPLICATE_SALT, LASA_RISK]`
* Extraction concurrency is capped at 3 so a cheap phone cannot open five
  simultaneous vision calls
* Each upload is validated by the same in-memory path as a single scan; total
  bytes received is echoed as `image_bytes_received`

---

## 6. Bilingual & accessibility

Measured in a real browser (Chromium, no service-worker cache) at 320, 414, 768
and 1000 px, for each language, after running the Telma preset:

| Language | Verdict label | Findings | Speech script | Overflow | Targets < 44 px |
|---|---|---|---|---|---|
| Malayalam | അപകടം — ഉടൻ നിർത്തുക | 2 | 587 chars, Malayalam | 0 px at all widths | 0 |
| Hindi | खतरा — तुरंत रोकें | 2 | 472 chars, Devanagari | 0 px at all widths | 0 |
| English | Danger — stop | 2 | 526 chars, Latin | 0 px at all widths | 0 |

One accessibility fix came out of this sweep: the "Detected medicines"
disclosure was a 34 px tap target at ≥768 px. It is now `min-height: 44px`.

Known cosmetic gap (unchanged): with Hindi selected, the LISTEN/STOP labels stay
bilingual Malayalam/English — they are fixed chrome, while the speech itself and
all warning copy follow the selected language.

Speech reality on this machine: no `ml-IN` voice exists in the headless browser,
so Malayalam correctly shows the "install a Malayalam voice" notice, while Hindi
plays (`speechSynthesis.speaking === true`). That is the exact gap the local
audio pack exists to close.

---

## 7. Test inventory (this run)

| Suite | Command | Result |
|---|---|---|
| Backend | `./.venv/bin/pytest` | **132 passed** |
| State machine | `node state.test.mjs` | 18/18 |
| Retry (DOM) | `node retry.test.mjs` | 4/4 |
| EXIF scrub | `node exif-scrub.test.mjs` | 15/15 |
| Live presets | `node presets.test.mjs` | 9/9 |
| Audio pack unit | `node audio-pack.test.mjs` | 10/10 |
| **Audio pack DOM (new)** | `node audiopack.test.mjs` | **14/14** |
| **Total** | | **132 backend + 70 frontend** |

---

## 8. Remaining gaps (not addressed in this pass)

* **Live vision unverified** — no provider key in this environment.
* **No real audio clips** — `static/audio/manifest.json` is intentionally empty;
  playback is proven with injected manifests and a mock `<audio>`, not audible
  sound. The pack has no WASM synthesis yet (Piper/sherpa-onnx, 20–60 MB).
* **Container/proxy untested here** — no Docker socket and no `nginx` binary in
  the sandbox, so `docker build` and `nginx -t` have never run.
* **Taxonomy is a 48-molecule pilot subset**, not a licensed drug database.
* **Hindi button labels** — the cosmetic gap in §6.
* CI pipeline, a built image, deployed edge rules and a licensed drug feed remain
  P0 before a public URL.

---

## 9. Scorecard against the Pass 24 checklist

| Criterion | Verdict |
|---|---|
| DOM audio test passes 100%, proving `playScript` invocation **and** speech fallback | **Pass** — 14/14, and it caught two real defects |
| Full test suite green (backend + frontend, 0 errors) | **Pass** — 132 + 70 |
| RAM ephemerality across all request paths | **Pass** — 0 files, 0 deleted fds |
| Bilingual consistency (en/ml/hi error states + speech triggers) | **Pass** — 12/12 layout combinations, correct scripts |
| `AUDIT_REPORT.md` generated and accurate | **Pass** |

**Overall: 9/10.** Points withheld for the two things this environment cannot
certify: a live Groq extraction and audible playback of real clips. Both are
documented above rather than presented as verified.
