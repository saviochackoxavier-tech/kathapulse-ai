# KathaPulse AI — Pass 24 Audit Report

**Scope:** end-to-end audit of the running prototype (`0.0.0.0:3004`), plus a new
permanent DOM-level integration test for the local audio pack.
**Date:** 23 November 2026
**Build audited:** `v1.5.0` (Pass 30: `v1.4.0`), branch `freebuff/634aa3b468f03b91c44ddefa`

---

## 1. Summary

| Area | Result |
|---|---|
| DOM audio test `tests/js/audiopack.test.mjs` | **17/17 checks pass** |
| Defects found by that test and fixed | **3** (dead tier 0 on cold start; no STOP during clip playback; English read the Malayalam script after a language switch) |
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
| 15 | empty manifest + **English** scan → English script spoken, no Malayalam | en fallback |
| 16 | empty manifest + **Hindi** scan → Devanagari script spoken | hi fallback |
| 17 | Malayalam scan switched to English → English script, not the scan-time one | `safety_message_en` |

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

Both are pinned by the test (checks 1 and 5), which fails 5/14 against the
pre-fix code and passes after it.

3. **English re-read the Malayalam script** (found by extending the test to all
   three languages). `spokenTextFor()` fell through to `safety.speech.text` for
   English, and that field carries whatever language the scan was taken in — so
   scanning in Malayalam and switching to English spoke Malayalam text through an
   English voice. The API now returns `safety_message_en` alongside
   `_ml`/`_hi` (`app/main.py::_flatten_flags`, both response schemas), and the
   client prefers it for `en`. Check 17 pins it.

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
| **Audio pack DOM** | `node audiopack.test.mjs` | **17/17** |
| **Total** | | **132 backend + 73 frontend** |

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
| Full test suite green (backend + frontend, 0 errors) | **Pass** — 132 + 73 |
| RAM ephemerality across all request paths | **Pass** — 0 files, 0 deleted fds |
| Bilingual consistency (en/ml/hi error states + speech triggers) | **Pass** — 12/12 layout combinations, correct scripts, and a language switch now speaks the selected language |
| `AUDIT_REPORT.md` generated and accurate | **Pass** |

---

## 10. Pass 26 — live vision pre-flight (blocked, not failed)

The brief for this pass stated that a Groq key (`gsk_...`) had been injected.
It had not. Measured state:

| Probe | Result |
|---|---|
| `.env` value length for `KATHA_VISION_API_KEY` | **0 characters** (line present, value empty) |
| Key present in the process/shell environment | **no** |
| `/health` from the running service | `vision_model: null` → tier disabled |
| `GET https://api.groq.com/openai/v1/models` from this sandbox, no credentials | **HTTP 401 `invalid_api_key`**, TLS connect 13 ms |
| `scripts/check_vision.py` | `server tier : disabled` → `RESULT: FAIL — manual_required` |

The 401 is the informative part: the sandbox **can** reach Groq over TLS, so once
the key is set, the only remaining variable is the provider's answer — not
network, DNS or proxy configuration.

### What is verified regardless

* **Graceful degradation** — with no key, `POST /verify-strip` returns `200`,
  `extraction_status: manual_required`, `extraction_source: none`,
  `verdict: unknown`, a Malayalam read-aloud prompt and
  `processed_in_memory: true`. It never guesses a medicine and never 500s.
* **Secret hygiene** — `.env` is gitignored and untracked; no tracked file
  contains `gsk_` or a `Bearer` token; no file served from `static/` references
  a key or `KATHA_VISION_*`; `/health` exposes only whether the tier is on; the
  415 error body contains no environment data; `.env.example` now shows the
  `gsk_` prefix as a placeholder.
* **Sample legibility** — `samples/strip-dolo.jpg` is a clean, high-contrast
  "DOLO 650 / PARACETAMOL 650 mg" strip, so the first live run will be a fair
  test of the model rather than of the fixture.
* **No regressions** — 132 pytest + 73 frontend checks still pass.

`scripts/check_vision.py` was corrected in this pass: it used to print
"NOT configured" from its own shell even when the server was configured (the key
may live only in the service's environment). It now reports the server's tier by
asking `/health`, so a judge reading the output is not misled.

### To finish this pass

Set `KATHA_VISION_API_KEY=gsk_...` in **Settings → Project settings → Secrets**
(never in chat), restart the server, then:

```bash
./.venv/bin/python scripts/check_vision.py     # exit 0 = live extraction worked
```

Expected result against the bundled sample: `extraction_status: ok`,
`extraction_source: vision_llm`, Paracetamol 650 mg resolved, verdict `safe`
for a single strip.

---

## 11. Pass 27 — dual-key rotation (built and verified here)

The brief described a "newly implemented Dual-Key Groq API Rotator" and a
`tests/test_failover.py`. Neither existed, and no second key was configured, so
this pass implemented them rather than reporting a passing test that did not
exist.

### What was added

* `app/config.py` — `KATHA_VISION_API_KEY_FALLBACK`, plus `api_keys()` (primary
  first, blanks dropped, duplicates merged) and `key_count`.
* `app/extraction.py` — the vision call now walks the key list. A response of
  **429, 401 or 403** means "this key cannot serve us": the key is dropped and
  the *same* request is retried with the next one. A lone key keeps the previous
  behaviour exactly (one quiet retry on 429, then degrade). Failures are logged
  by status and key index only — never the key, never the body.
* `app/schemas.py` / `app/main.py` — `/health` now reports `vision_keys` and
  `vision_fallback` (count + boolean, no material).
* `tests/test_failover.py` — 15 tests, no network, no real key.

### Automated verification

```
$ ./.venv/bin/pytest tests/test_failover.py
15 passed
$ ./.venv/bin/pytest
147 passed
```

Covered: 429/401/403 each rotate and still extract Paracetamol 650 mg; the retry
carries the *other* key; failover takes < 1 s and never waits on the rejected
key; both keys rejected → `manual_required` with no exception; duplicate keys are
not tried twice; single-key behaviour unchanged; fallback-only configuration
works; no keys → no network call; `/health` counts are correct at 0, 1 and 2 keys
and contain neither key; neither key appears in the logs; failover writes nothing
to the temp directory.

### Live verification over real HTTP

A local two-key stand-in (`scripts/_stub_vision.py 3011 reject-primary`) returned
`429` for `primary-demo-key` and `200` for `fallback-demo-key`. The server was
restarted with both keys set:

| Step | Observed |
|---|---|
| `GET /health` | `vision_keys: 2`, `vision_fallback: true`, `vision_model: stub/two-key` |
| `POST /verify-strip` | `200`, `extraction_status: ok`, `extraction_source: vision_llm`, Telmisartan 40 + HCTZ 12.5, `verdict: safe` |
| Stub request log | `429` then `200` — the primary was refused, the fallback served |
| Disk | no file created by the request; the only new file was the curl output this audit wrote |
| Speech | `safety_message_ml`, `_hi` and `_en` all present in one response |

Afterwards the server was restored to its real configuration:
`vision_keys: 0`, `vision_fallback: false`, `vision_model: null` — the preview
never serves from the stub.

### Honest status

No real Groq key exists in this environment (`.env` value is empty; Pass 26
records the same). Rotation is therefore proven against mocks and against a
local two-key endpoint, **not** against Groq itself. The mechanism is
provider-agnostic — it reacts to status codes, not to Groq's error text — so the
remaining risk is credential-level, not code-level.

---

## 12. Pass 28 — failover refactor and CI

### 12.1 The failover loop, split in two

Pass 27's loop nested three concerns in one block: the key walk, the per-key
retry policy and the HTTP call. The retry policy was expressed as a four-clause
condition inside the loop (`last_key and status == 429 and attempt == 0`), which
is exactly the shape that grows a bug later — the single-key rule and the
multi-key rule were entangled in one boolean.

`app/extraction.py` now has `_read_with_key()`: **one key's turn**, returning the
model's content or `None` when that key cannot serve us. `_vision_extract()`
keeps only the walk:

```python
for position, key in enumerate(keys, start=1):
    content = await _read_with_key(
        client, cfg, key, payload,
        has_fallback=position < len(keys),
        key_position=(position, len(keys)),
    )
    if content:
        break
```

Inside the helper the two policies are now separate statements rather than one
compound condition:

| Key's situation | 429 | 401 / 403 | 5xx / malformed |
|---|---|---|---|
| another key behind it | log, rotate **immediately** | log, rotate | abort the tier |
| nothing behind it (lone, or last in the chain) | sleep 1.2 s, retry **once**, then log + give up | log, give up | abort the tier |

Provider errors are still deliberately outside the rotation: a 5xx is not the
key's fault, so walking a second key would only repeat the same failure and
spend the request budget. Behaviour is unchanged for every case the Pass 27
tests pinned, and the one previously untested boundary — *both* keys answering
429 — is now pinned too (3 calls: primary once, last key twice, then success).

### 12.2 CI

`.github/workflows/ci.yml` — two jobs, `contents: read`, per-ref concurrency
cancel, on every push and pull request:

* **backend** — Python 3.12, `pip install -r requirements.txt`, `pytest`;
* **frontend** — Python 3.12 + Node 20 (`npm ci` with the npm cache), then
  uvicorn on `127.0.0.1:3004`, a bounded `/health` poll, and the six Node suites
  as separate steps, with a server-log tail on failure.

The frontend job runs with both vision keys explicitly empty, so CI proves the
keyless path and cannot leak or depend on a credential. `tests/js/package-lock.json`
is now committed (the only lockfile that is) so `npm ci` is reproducible.

Honest scope: the YAML parses (`yaml.safe_load`, 2 jobs / 4 + 13 steps) and
every command in it was run locally in this pass — **GitHub's runner has not
executed it**, because that requires a push, which was not authorised.

### 12.3 Verification

```
$ ./.venv/bin/pytest -o addopts="" -q
148 passed, 1 warning in 5.05s       # 147 + the new both-429 boundary
$ cd tests/js && node state.test.mjs     → 18/18
$ node retry.test.mjs                    → 4/4
$ node exif-scrub.test.mjs               → 15/15
$ node audio-pack.test.mjs               → 10/10
$ node audiopack.test.mjs                → 17/17
$ node presets.test.mjs                  → 9/9   (live server, keyless)
```

The refactor moved no clinical code: `app/clinical.py`, `app/taxonomy.py` and
`app/main.py` are untouched, so the 44-case corpus and the preset verdicts are
unchanged by construction and by test.

---

## 13. Scorecard against the Pass 28 checklist

| Criterion | Verdict |
|---|---|
| Code cleanliness — failover simplified, single-key path preserved | **Pass** — one helper per key, one walk in the caller; the single-key retry is now a named constant and a single `if`, and all 16 failover tests (including the new both-429 boundary) pass |
| CI automation — workflow validates backend and frontend | **Pass (locally executed)** — `.github/workflows/ci.yml` runs pytest and all six Node suites against a real server; YAML validated and every command run here, but not yet by GitHub's runner |
| Zero regressions — 147+ backend and 73 frontend checks green | **Pass** — 148 backend, 73 frontend, 0 failures, 0 skipped |
| Production stability /10 | **9/10** — server serves `/`, `/health` and every asset; degraded keyless scan is correct; nothing in this pass touches the request path's zero-persistence guarantees |

---

## 14. Pass 29 — batch recall & expiry auditor

The brief listed `app/recall.py` as existing. It did not, and nothing in the
build read a batch number or an expiry date, so this pass built the module and
wired it through extraction, the clinical pipeline, the API and the UI.

### 14.1 What was added

| Layer | Change |
|---|---|
| `app/recall.py` **(new)** | Expiry parser, batch matcher, four pilot recall notices, cold-chain table, and `audit(medicines, as_of)` returning localised findings |
| `app/schemas.py` | `batch_no` / `expiry` on `ManualMedicine` and `ScannedMedicine` (validated, length-capped); `recall_warning` / `expiry_warning` on both responses; `recall_notices` on `/health` |
| `tests/test_recall.py` **(new)** | 56 checks: parsing, matching, cold chain, copy, determinism, disk, API contract, validation |
| `tests/js/recall.test.mjs` **(new)** | 13 DOM checks: banner order/colour/copy, ml+hi, no duplication, audio slot per code, typed batch |
| `app/extraction.py` | The vision prompt now asks for `batch_number` and `expiry_date`; `_code()` clamps untrusted text to `[A-Z0-9 ./_-]`; reads carry both fields to the medicine |
| `app/clinical.py` | One new rules pass, `recall.audit()` in `analyse()` (after the interaction table), plus an injectable `as_of` for tests |
| `app/main.py` | `_flatten_flags` derives both booleans from the same findings tree; manual entry passes typed batch/expiry |
| `static/index.html`, `app.js`, `styles.css` | Crimson/amber banner **above** the verdict (`role="alert"`), batch/expiry inputs on the manual form, a fourth demo preset |
| `static/sw.js` | Cache `kathapulse-v5` → `v6` so phones pick up the new shell |

Codes: `RECALLED_BATCH` (critical), `EXPIRED_STOCK` (critical), `EXPIRY_SOON`,
`EXPIRY_UNREADABLE`, `COLD_CHAIN_RISK` (warning).

### 14.2 Why this is not a duplicate of an existing check

Every earlier rule operates on **molecules** — same salt, cumulative dose,
interaction, class overlap, sound-alike. None of them can see the box: a
perfectly legitimate, correctly dosed strip can still be a recalled lot or a
foil that expired last year. The audit is also the only pass whose evidence is
the printed batch and date rather than the composition, and the only one that
fires on a single strip with no clinical finding at all.

### 14.3 Measured behaviour

| Probe | Result |
|---|---|
| `Glycomet 500`, batch `GM2407A`, expiry `09/2026` | `200`, verdict `critical`, findings `[RECALLED_BATCH, EXPIRED_STOCK]`, `recall_warning: true`, `expiry_warning: true` |
| `Dolo 650`, batch `DL2511`, expiry `12/2026` | `200`, verdict `caution`, findings `[EXPIRY_SOON]` |
| `Dolo 650`, no batch/expiry | no audit finding, no flag — unchanged for every existing client |
| Batch `<script>alert(1)</script>` | `422` |
| `expiry: "04/2026; DROP TABLE"` | `422` |
| `/health` | `recall_notices: 4`, no feed body, no key material |
| Banner in the DOM | crimson `role="alert"` block above the verdict, two items, Malayalam by default, Devanagari after a Hindi switch, absent on the Telma preset |
| Speech | `safety_message_ml` / `_hi` / `_en` all carry the recall sentence; the pack is asked for `RECALLED_BATCH` and `EXPIRED_STOCK` clips per language |

### 14.4 Verification

```
$ ./.venv/bin/pytest -o addopts="" -q
206 passed, 1 warning in 5.00s
$ cd tests/js
state 18/18 · retry 4/4 · exif-scrub 15/15 · audio-pack 10/10
AUDIOPACK 17/17 · presets 9/9 · recall 13/13        (86 frontend checks)
```

No pre-existing test was weakened to make room: the one test that changed
(`test_vision.py`) failed because the vision read gained two fields, and it now
asserts those fields explicitly, plus two new tests for a normalised batch and
for control-character scrubbing.

### 14.5 Scorecard against the Pass 29 checklist

| Criterion | Verdict |
|---|---|
| Feature uniqueness — real clinical utility, no duplicate of existing checks | **Pass** — operates on the batch/date, which no molecule rule can see, and fires on single-strip cases the other passes ignore |
| Zero disk persistence | **Pass** — batch/expiry ride the same in-RAM `bytes` request; `recall.audit` is a pure function and a test pins an empty temp directory after a full audit |
| Zero regressions | **Pass** — 206 backend + 86 frontend, 0 failures, 0 skipped |
| Multilingual audio | **Pass** — all five codes have ml/hi/en title, message and action; the script is spoken in the selected language and the pack has a clip key per `<lang>:<code>` |
| Production readiness | **9/10** |

### Honest limits of this pass

* The recall feed is **four curated pilot notices** with local trace labels
  (`PILOT-RCL-01`), not a CDSCO feed and not regulatory citations. The engine is
  finished; the data is illustrative. That is stated in the module docstring,
  the UI copy ("recall list"), the README and here.
* Batch/expiry are only as good as what the vision tier reads. With no key in
  this environment the photo path still degrades to manual entry, so the audit
  is exercised through API and preset data — not through a photograph.
* The banner was verified in a DOM (classes, order, copy, `role`) but **not
  visually reviewed in a browser** in this pass.

---

## 15. Pass 30 — Kerala ground-truth knowledge base & local fallback

The brief listed `app/knowledge_base.py` as existing. It did not, and the alias
table could not answer the case the brief cares about, so this pass built the
module and wired it into extraction, the clinical rules, the API and the UI.

### 15.1 The bug it was written for (measured before the fix)

```
$ python -c "from app import taxonomy; print([d.canonical for d in taxonomy.lookup('Glycomet GP')])"
['metformin']                       # the glimepiride is silently dropped
```

`Glycomet GP` contains the alias `glycomet`, so the taxonomy answered *metformin
only*. A pharmacist reading that screen would hand over a plain Glycomet, and the
patient would lose their sulfonylurea — the exact class of error this product
exists to prevent. After the change:

```
$ python -c "... resolve_medicine('Glycomet GP') ..."
matched=True verified_by=ground_truth [('metformin',500.0), ('glimepiride',1.0)]
```

### 15.2 What was added

| Layer | Change |
|---|---|
| `app/knowledge_base.py` **(new)** | 48 curated Kerala products, class-level cautions and age bands, a 256-key compact index, containment + similarity matching with a hard floor, `catalogue()` for the public feed |
| `app/extraction.py` | A KB resolution that wins only when it is a **proper superset** of the alias table's molecules, so a half-answer cannot survive; `verified_by` on every medicine |
| `app/clinical.py` | `AGE_WARNING` from the KB's age bands, emitted only when the request supplies an age |
| `app/schemas.py`, `app/main.py` | `age_years` on both request paths, `ground_truth_verified` on both responses, `knowledge_base_*` on `/health`, and `GET /knowledge.json` |
| `app/i18n.py` | 17 new keys: age title/body/action, the verified badge, and 10 catalogue cautions, each in en/ml/hi |
| `static/*` | Green "Ground-Truth verified" line above LISTEN, an age field on the manual form, a fifth demo preset; cache `kathapulse-v6` → `v7` |
| Tests | `tests/test_knowledge_base.py` (59) and `tests/js/groundtruth.test.mjs` (12) |

### 15.3 Measured behaviour

| Probe | Result |
|---|---|
| `GET /health` | `knowledge_base_entries: 256`, `knowledge_base_brands: 48` |
| `GET /knowledge.json` | `200`, 48+ catalogue entries, Telma-H → telmisartan + HCTZ, localised cautions, no patient data, no key names |
| `Glycomet GP` via `POST /verify-medicines` | `200`, ingredients metformin + glimepiride, `verified_by: ground_truth`, `ground_truth_verified: true`, verdict `safe` |
| `PAN D`, `Telma H`, `Augmentn 625` | all resolve to **two** molecules (alias table: zero, one, one) |
| `SMUDGED FOIL` | `matched: false`, no ingredients, `verified_by: ""` — never a guess |
| `Amaryl 1` + `age_years: 72` | findings `[AGE_WARNING, LASA_RISK]`, Malayalam and Hindi scripts carry the age sentence |
| `age_years: 500` | `422` |
| Provider raises `ConnectError` on `/verify-strip` | `200`, `manual_required`, `verdict: unknown`, `processed_in_memory: true`, 0 files in the temp dir |
| Badge in the DOM | shown for Glycomet GP in Malayalam and Devanagari, absent for the Telma pair, above the LISTEN button |

### 15.4 Verification

```
$ ./.venv/bin/pytest -o addopts="" -q
265 passed, 1 warning in 5.03s
$ cd tests/js
state 18/18 · retry 4/4 · exif-scrub 15/15 · audio-pack 10/10 · audiopack 17/17
presets 9/9 · recall 13/13 · groundtruth 12/12            (98 frontend checks)
```

One existing test file changed: nothing. The 206 checks from Pass 29 pass
unmodified, which is the strongest available evidence that a ≥superset rule did
not disturb any clinical answer.

### 15.5 Scorecard against the Pass 30 checklist

| Criterion | Verdict |
|---|---|
| Ground-truth accuracy | **Pass** — 256 indexed names; the `Glycomet GP` half-answer is fixed; OCR slips resolve; nonsense returns nothing; every molecule validated against the taxonomy |
| Autonomous fallback resilience | **Pass** — provider `ConnectError` still yields `200` with a localised, structured, speakable answer; the knowledge base itself never touches the network |
| Zero disk persistence | **Pass** — pure functions over a `bytes` request; empty temp dir asserted after matching, catalogue build and analysis |
| Zero regressions | **Pass** — 265 backend + 98 frontend, 0 failures, 0 skipped |
| Hackathon excellence | **9/10** |

### Honest limits of this pass

* The catalogue is **curated pilot data**: 48 products, 256 names, Indian pack
  strengths. Cautions and age bands are label-derived advisories that a
  pharmacist should review before a pilot depends on them.
* The fallback resolves *text*. With no vision key and no tesseract, a photo still
  cannot be read locally — the app degrades to the localised manual prompt, which
  is what the uptime test asserts. Claiming otherwise would be false.
* The badge and the age finding were verified in a DOM (order, classes, copy,
  speech, wire format), **not visually reviewed in a browser** this pass.

---

## 16. Pass 31 — voice-first dose reminders and a local countdown

The brief listed `app/audio_reminders.py` as existing. It did not exist, so this
pass wrote it, wired it to the clinical strengths, and put the clock in the
browser.

### 16.1 What was added

| Layer | Change |
|---|---|
| `app/audio_reminders.py` **(new)** | `parse_schedule()` for `1-0-1` / `0-1-0` / `twice daily` / `BD` / `TDS` / `QID` / `every 8|12 hours`, `slot_for_time()`, `_daily_paracetamol_mg()`, `build_plan()`, Pydantic request/response models |
| `app/main.py` | `POST /reminders` — a thread-pool call, `no-store`, no id, no table |
| `app/i18n.py` | 17 keys: intro, four parts of day, the `{time} — {medicines}, {amount}` sentence, singular/plural tablet units, the caveat, the confirmation and four refusal reasons, each in en/ml/hi |
| `static/js/reminders.js` **(new)** | `nextDose()` (rolls to tomorrow), `formatLeft()`, `isDue()` — pure, DOM-free, unit-tested in Node |
| `static/js/app.js` | Panel gating on `matched`, `POST /reminders`, banner, a 15 s `setInterval`, `Notification` when granted, cancel, and invalidation when a different set of medicines is scanned |
| `static/index.html`, `styles.css` | Reminder panel + emerald countdown banner, 44 px controls, bilingual labels |
| `static/sw.js` | Precache `reminders.js` and `knowledge.json`; `kathapulse-v7` → `v8` |
| Tests | `tests/test_audio_reminders.py` (67) and `tests/js/reminders.test.mjs` (16); CI gains a ninth suite |

### 16.2 Why it is not a duplicate

Passes 29-30 answer *is this box safe to hand over*; this pass answers *when does
the patient take it*, which neither the recall audit nor the KB touched. The
design decision that keeps it inside the product's safety posture: the server
**derives** a plan and forgets it. There is no scheduler, no job table, no push
key, no `localStorage` — the plan is a variable in the tab. A browser cannot wake
a closed tab, so the UI states the limitation ("works while this page stays
open") rather than implying a background service that does not exist.

The refusal paths are the same policy as everywhere else in this build: `SOS`
returns `as_needed` and tells the patient to follow the doctor, unreadable text
returns `unsupported` with the `1-0-1` example, five tablets in a slot returns
`too_many`, and a schedule that would exceed 4000 mg/day of paracetamol returns
`paracetamol_limit` **with the computed total in the sentence**. That last check
reuses `extraction.resolve_medicine` and the KB strengths, so a reminder can
never quietly prescribe more paracetamol than the clinical rules allow.

### 16.3 Measured behaviour

| Probe | Result |
|---|---|
| `1-0-1` | `08:00`, `21:00` — morning, night |
| `1-1-1` and `TDS` | the same clock: `08:00`, `14:00`, `21:00` |
| `every 8 hours` | `08:00`, `16:00`, `00:00` (spaced by eight hours, `00:00` labelled night) |
| `SOS`, `PRN`, `as needed` | `scheduled: false`, `reason: as_needed` |
| `nonsense`, `0-0-0`, `every 6 hours` | `scheduled: false`, `reason: unsupported` |
| `5-0-0` | `scheduled: false`, `reason: too_many` |
| `Dolo 650` × `3-3-3` | `5850 mg` > `4000 mg` → `paracetamol_limit` |
| `Dolo 650` × `2-2-2` | scheduled (`3900 mg`) |
| `POST /reminders` (ml) | `200`, `[('08:00','morning',1), ('21:00','night',1)]`, Malayalam script with the caveat sentence, `processed_in_memory: true`, `Cache-Control: no-store` |
| Malformed body | `422` for empty `medicines`, missing `pattern`, 41-char pattern, extra keys, `<script>`, and `language: "zz"` |
| Temp dir after building plans | empty |

### 16.4 Verification

```
$ ./.venv/bin/pytest -o addopts="" -q
332 passed, 1 warning in 5.01s
$ cd tests/js
state 18/18 · retry 4/4 · exif-scrub 15/15 · audio-pack 10/10 · audiopack 17/17
presets 9/9 · recall 13/13 · groundtruth 12/12 · reminders 16/16   (114 frontend checks)
```

The 265 checks from Pass 30 pass unmodified. The reminder suite runs the real
`index.html` + `app.js` in jsdom against captured API payloads, and the clock
tests are the same functions the browser executes.

### 16.5 Scorecard against the Pass 31 checklist

| Criterion | Verdict |
|---|---|
| Feature innovation | **Pass** — dose timing is the next question after safety, and it is answered in the patient's script with real clock times |
| Zero disk persistence | **Pass** — plan computed from the request, returned once, dropped; browser keeps it in a variable; empty temp dir asserted |
| Zero regressions | **Pass** — 332 backend + 114 frontend, 0 failures, 0 skipped |
| Multilingual audio | **Pass** — slot labels, dose sentence, confirmation, caveat and all four refusals carry en/ml/hi; the speech payload is spoken by the device voice, and the countdown is rendered in the selected language |
| Hackathon excellence | **9/10** |

### Honest limits of this pass

* Reminders only fire **while the tab is open**. A closed tab cannot be woken
  without a service-worker push subscription and a server key, which this
  zero-persistence build deliberately does not have. The banner says so.
* The spoken reminder uses the device voice. There are still **no shipped audio
  clips** for reminder sentences (`static/audio/manifest.json` clips are `{}`),
  and this headless browser has no `ml-IN` voice, so audibility was not heard —
  only the string handed to `Speech.speak` was asserted.
* `Notification` was not exercised visually: jsdom has no `Notification` API, so
  the tests prove the *no-notification* path stays silent and crash-free. The
  granted path is guarded by `permission === "granted"` but was not observed.
* The panel and banner were verified in a DOM (visibility, copy, order, cancel,
  language switch), **not visually reviewed in a browser** this pass.

---

**Overall: 9/10.** Points withheld for the things this environment cannot
certify: a live Groq extraction (no key exists here), audible playback of real
clips, the recall feed and knowledge base being curated pilot data rather than
licensed feeds, and CI having run on GitHub (the workflow is syntax-checked and
every command is run locally, but no push was authorised).
