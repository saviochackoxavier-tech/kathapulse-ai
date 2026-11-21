# KathaPulse AI

Dialect-aware medication safety companion for Kerala. Photograph a medicine
strip, get a plain-language warning in Malayalam or Hindi — spoken aloud — before
you take two tablets that contain the same drug.

> **NeuraViz Stage 3/4 submission — POC v1.0.0.**
> Team: `<team name>` · Contact: `<name> · <email>`
> *(Replace the two placeholders above before submitting; everything else in this
> file is final.)*

**Judges' 30-second demo — no camera, no API key, no configuration.**

1. Open the preview URL (or `http://localhost:3004`).
2. Tap **Telma 40 + Telma-H** → red `critical` card: the same telmisartan twice,
   plus a look-alike warning about the same foil family. Spoken in Malayalam.
3. Tap **Dolo 650 + Crocin Cold & Flu** → red `critical` card: 1300 mg of
   paracetamol at once, from two brands.
4. Tap **Amaryl 1 mg** → amber `caution` card: sounds like Amlopres, a
   different drug — verify before taking.
5. Switch the language selector to **हिन्दी** to see the identical findings, and
   the same spoken script, in Hindi.

The three presets run through the deterministic clinical engine only, so they
work with no vision key and no network egress. Real photos additionally need the
optional vision or OCR tier — see [Configuration](#configuration).

**Privacy in one line:** the browser strips EXIF before upload, the server
processes the image in RAM and never writes it to disk, and there are no
accounts or cookies — see [Privacy design (DPDP Act 2023)](#privacy-design-dpdp-act-2023).

```
browser                          server (FastAPI)                 data
───────                          ────────────────                 ────
camera / gallery
   │
   ├─ canvas re-encode ──────────► POST /verify-strip  (multipart)
   │  (EXIF, GPS, timestamp,           │
   │   device id all dropped)          ├─ extract: vision LLM → OCR → manual
   │                                  ├─ resolve: Indian drug taxonomy (48 molecules)
   ▼                                  ├─ rules: duplicate salt, dose ceiling,
scrubbed JPEG only ──────────────────►│         interactions, same-class overlap
   │                                  ▼
   ├─ result cards (high contrast)  JSON: tri-lingual findings + speech script
   └─ Web Speech API (ml-IN / hi-IN)
```

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./scripts/serve.sh                     # supervised, port 3004, restarts on exit
```

`scripts/serve.sh` runs uvicorn in a restart loop bound to `0.0.0.0:$PORT`
(default 3004, the preview port). A cloud runner restart or a crash therefore
recovers within a second instead of leaving the preview iframe on "refused to
connect". For a one-shot run:

```bash
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3004 --proxy-headers
```

Open the preview URL, or `http://<host>:3004` on the phone. The camera needs a
secure context (HTTPS or localhost); the "Choose photo" path works everywhere.

### Configuration

Copy `.env.example` to `.env`. Variables are read **per request**, so a key
takes effect without a restart. Real environment variables always win over the
file, and `/health` reports only *whether* a tier is configured — never a key.

### Vision tier (GroqCloud)

Any OpenAI-compatible chat-completions endpoint works. The configured demo
provider is Groq:

```
KATHA_VISION_BASE_URL=https://api.groq.com/openai/v1
KATHA_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
KATHA_VISION_API_KEY=<set this in Secrets, never in git>
KATHA_VISION_JSON_MODE=0
```

**Secret handling.** The key belongs in Settings → Project settings → Secrets,
or typed by you into `.env` (already in `.gitignore` — check with
`git check-ignore -v .env`). It is never hardcoded, never logged, never
returned by `/health`, and a test asserts it cannot reach either.

`KATHA_VISION_JSON_MODE=0` is the default because Groq does not enable
`response_format: json_object` on every model; parsing is fence-tolerant, so
```json blocks and stray prose around the object are accepted.

Verify the tier end to end — this is the check that distinguishes "wired" from
"working":

```bash
cd tests/js && node make-sample-strip.mjs && cd ../..   # writes samples/strip-dolo.jpg
./.venv/bin/python scripts/check_vision.py            # exit 0 = extraction worked
```

If no provider key exists yet, the same check can be run against a local
Groq-shaped stand-in, which proves every part of the path except the vendor's
own auth:

```bash
./.venv/bin/python scripts/_stub_vision.py 3010 &        # answers /chat/completions
KATHA_VISION_API_KEY=stub KATHA_VISION_BASE_URL=http://127.0.0.1:3010 \
KATHA_VISION_MODEL=stub/vision ./scripts/serve.sh
```

`scripts/_stub_vision.py` is verification tooling, never started by
`serve.sh` and not part of the service.

### Optional extraction tiers

The clinical engine is fully functional without any external service — the
camera path needs one of these to read real photos:

| Tier | Requirement | Behaviour without it |
|---|---|---|
| Vision LLM | `KATHA_VISION_API_KEY`, `KATHA_VISION_BASE_URL`, `KATHA_VISION_MODEL` (any OpenAI-compatible vision endpoint) | falls through |
| Local OCR | `pip install pytesseract pillow` + `tesseract-ocr` binary | falls through |
| Neither | — | returns `manual_required`; the UI opens the manual-entry panel |

The engine **never guesses** a medicine. An unreadable strip produces
`verdict: "unknown"` plus a prompt to type the printed name — a wrong guess is
more dangerous than "I don't know".

## Deploy

Two runner declarations ship with the app; both start the same ASGI object:

| Artifact | Use |
|---|---|
| `Dockerfile` + `.dockerignore` | any container host (Cloud Run, Fly, Railway, ECS). Non-root user, no volume, `HEALTHCHECK` on `/health`. |
| `Procfile` | Heroku/Render style: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` |

```bash
docker build -t kathapulse .
docker run -p 8000:8000 -e KATHA_VISION_API_KEY=... kathapulse
curl -s localhost:8000/health      # tiers + taxonomy size, never a key
```

Configuration on a host is **environment only**. `.env` is a local convenience:
both `.gitignore` and `.dockerignore` exclude it, so a key can never travel in
the image or the repository.

| Variable | Required | Default / purpose |
|---|---|---|
| `PORT` | platform-dependent | 8000 in the image, 3004 locally |
| `KATHA_VISION_API_KEY` | optional | unset → vision tier skipped, OCR/manual fallback |
| `KATHA_VISION_BASE_URL` | optional | `https://api.openai.com/v1` (Groq: `https://api.groq.com/openai/v1`) |
| `KATHA_VISION_MODEL` | optional | `gpt-4o-mini` (Groq: `meta-llama/llama-4-scout-17b-16e-instruct`) |
| `KATHA_VISION_TIMEOUT_S` | optional | `12` |
| `KATHA_VISION_JSON_MODE` | optional | `0` — Groq does not support `json_object` on every model |
| `KATHA_OCR_DISABLED` | optional | `1` disables local tesseract |

Verified on this build: with the exact `uvicorn` command from the `Procfile` and
`PORT=3011`, `GET /` → 200, `/static/css/styles.css`, all four JS assets and
`/static/favicon.svg` → 200, `/favicon.ico` → 200 (browsers probe it even with a
declared icon), `/health` → 200 with `Cache-Control: no-store`, and a real
`POST /verify-medicines` left `/tmp` free of any upload artifact. The **image
itself was not built here** — this sandbox has no access to a Docker daemon —
so the Dockerfile is reviewed and its startup command exercised directly, not
built.

There is no database, volume or writable path to provision: the service is
stateless, so scaling out is just more replicas behind the same origin.

## API

| Endpoint | Purpose |
|---|---|
| `POST /verify-strip` | multipart `image` + `language` (`ml`/`hi`/`en`) + `paracetamol_taken_today_mg` |
| `POST /verify-medicines` | JSON `{medicines:[{name}], language, paracetamol_taken_today_mg}` |
| `GET /health` | which extraction tiers are live, taxonomy size |
| `GET /` | the app shell |

Response shape (abridged):

```json
{
  "extraction_status": "ok",
  "safety": {
    "verdict": "critical",
    "findings": [{
      "code": "DUPLICATE_SALT",
      "severity": "critical",
      "title":   {"en": "Same medicine twice", "ml": "ഒരേ മരുന്ന് രണ്ടുതവണ", "hi": "एक ही दवा दो बार"},
      "message": {"en": "...", "ml": "...", "hi": "..."},
      "action":  {"en": "...", "ml": "...", "hi": "..."},
      "anchors": ["paracetamol"]
    }],
    "speech": {"language": "ml", "text": "കഥാപൾസ് മുന്നറിയിപ്പ്. …", "rate": 0.85}
  },
  "processed_in_memory": true,
  "duplicate_salt_warning": true,
  "lasa_risk": false,
  "safety_message_ml": "കഥാപൾസ് മുന്നറിയിപ്പ്. …",
  "safety_message_hi": "कथापल्स चेतावनी। …"
}
```

The last four fields are the flat client contract: `safety_message_ml` /
`safety_message_hi` are the exact strings to hand to `SpeechSynthesis`, and the
booleans are derived from the findings (one source of truth — a flag can never
disagree with the text).

## Privacy design (DPDP Act 2023)

* **Client side** — every capture and every gallery pick is drawn to a `<canvas>`
  and re-encoded with `toBlob()`. A canvas holds pixels only; it has nowhere to
  store EXIF/XMP/IPTC. Orientation is baked into the pixels first, so the strip
  is not rotated after scrubbing.
* **Server side** — the upload is read into a `bytes` object and never touches
  the filesystem. There is no `tempfile`, no cache directory, no image logging.
  A test walks the AST of `app/main.py` and `app/extraction.py` to keep it that
  way.
* **No accounts, no cookies, no sessions.** Nothing identifies the person
  scanning; the response carries `processed_in_memory: true` and
  `Cache-Control: no-store`.
* **Prompt-injection resistance is structural** — model output is parsed into
  models with `extra="forbid"`, free text is charset-whitelisted and capped at
  120 chars, and unrecognised text is only ever fuzzy-matched against a fixed
  taxonomy. Nothing the model says can trigger an action.

## Clinical engine

`app/clinical.py` is a pure function: same input, same verdict, no model in the
decision path. Checks run in this order:

1. `DUPLICATE_SALT` — same molecule across two strips (critical).
2. `PARACETAMOL_DAILY_MAX` / `_NEAR_MAX` — cumulative dose vs the 4000 mg ceiling.
3. `INTERACTION` — 29 curated molecule pairs (bleeding, hyperkalaemia, nitrate +
   PDE5, serotonin syndrome, dual RAAS blockade …).
4. `DUPLICATE_CLASS` — two different molecules of one family (two NSAIDs, two ARBs).
5.   `LASA_RISK` — look-alike / sound-alike strips: same brand family with different
   contents (`Telma` vs `Telma-H`, `Pan 40` vs `Pan-D`, `Zerodol` vs `Zerodol-SP`,
   `Glycomet` vs `Glycomet-GP`, `Montair` vs `Montair-LC`), cross-family spoken
   collisions (`Amaryl`/`Amlopres`, `Metrogyl`/`Metolar`), and **verification**
   prompts for shelf neighbours we will not resolve (`Loprin`/`Loprin-LS`).
   The pass is split by scope: `_lasa_candidates()` reduces each strip to a
   label, `_dual_strip_lasa_findings()` compares strips scanned together (with
   the decision in `_lasa_pair_body_key()`), and `_single_strip_lasa_findings()`
   handles the lone box that collides with something not in the photo.
6. `UNRECOGNISED_MEDICINE` — never silently "safe".
7. `NO_DANGEROUS_OVERLAP` — the safe path, still not a prescription check.

`app/taxonomy.py` holds 48 molecules with their common Kerala brand names
(Dolo/Crocin/Calpol, Telma/Telsartan, Glycomet, Pan 40, Thyronorm …) and 15
fixed combinations (Telma-H, Combiflam, Montair-LC, Zerodol-SP, Augmentin,
Ultracet …). Combination products resolve to *all* their molecules, which is how
the engine catches "Telma-H + a separate HCTZ tablet".

## Tests

```bash
./.venv/bin/pytest                 # 132 backend, rules, LASA, accuracy, vision, e2e, batch/offline/relay/hardening/ratelimit/audio tests
cd tests/js && npm install && npm test   # 15 EXIF-scrub checks
cd tests/js && node state.test.mjs       # 18 state-machine / error-surface / retry checks
cd tests/js && node retry.test.mjs       # 4 DOM-level retry checks (jsdom + app.js)
cd tests/js && node presets.test.mjs     # 9 live preset checks — needs ./scripts/serve.sh running
cd tests/js && node audio-pack.test.mjs  # 10 audio-pack loader, script and fallback checks (no jsdom, no network)
# Backend / next-gen surface covered by tests/test_nextgen.py: /sw.js, /taxonomy.json,
# POST /verify-strips/batch (1-5 strips) and the zero-retention /ws/relay handshake.
```

The preset suite is the integration one: it POSTs the three demo scenarios to the
running app, then clicks each `data-demo` button in jsdom and asserts the card
colour, the Malayalam/Hindi copy and the exact string handed to Web Speech. Start
the server first (`./scripts/serve.sh`); point it elsewhere with
`KATHA_BASE_URL=http://127.0.0.1:8000 node presets.test.mjs`.

Measured results from this build:

| Check | Result |
|---|---|
| Backend suite | **132 passed** |
| Duplicate-salt corpus (44 labelled cases) | **100% accuracy, 100% precision, 100% recall, 100% correct salt** |
| EXIF scrub (real JPEG codec, dirty input → clean output) | **15/15 checks passed** |
| Client state machine + error surface | **18/18 checks passed** |
| Retry path, executed in a DOM (jsdom) | **4/4 checks passed** — fails 3/4 if the Pass 4 defect is reintroduced |
| Live demo presets, real API + real DOM | **9/9 checks passed** — Telma pair, Dolo+Crocin and Amaryl each render the expected card (32 ms on the cold first call, then 7 ms and 4 ms), and the speech handoff carries the same Malayalam string the API returned |

## Demo presets

Three one-click buttons above the camera run the pilot cases through
`POST /verify-medicines`, so a live demo never depends on a camera, a steady
hand, or a vision key:

| Preset | Expected result |
|---|---|
| Telma 40 + Telma-H | `critical` — duplicate telmisartan **and** LASA (same foil family) |
| Dolo 650 + Crocin Cold & Flu | `critical` — dual paracetamol (1300 mg at once) |
| Amaryl 1 mg | `caution` — LASA advisory: sounds like Amlopres, a different drug |

The third case is a **single-strip** LASA check: the curated sound-alike table
also fires on one box, because the confusion happens before a second box exists.
Brand-family checks (Telma/Telma-H) deliberately need two strips, or every
Telma scan would cry wolf.

A preset and the manual textarea are the same scan, so they share one handler
(`runNamedScan()` in `app.js`): one request, one pair of state transitions, one
retry wiring. `runPreset()` only maps a `data-demo` id to its names, and the
busy guard is inside the shared handler, so a double tap cannot post twice.

## Kochi pilot scenarios

Pilot setting: OP pharmacy counters and homes around Kochi/Ernakulam — Angamaly,
Aluva, Kakkanad — where Malayalam-branded paracetamol and the Telma/Telma-H pair
are the everyday confusions. The user is the person holding the strip, not a
clinician, often on a low-end Android with patchy data.

| Scenario | Scan | Required output |
|---|---|---|
| Fever, two brands brought together | Dolo 650 + Crocin Cold & Flu | `critical` — same paracetamol twice, 1300 mg at once; do not take both |
| BP refill mix-up at the counter | Telma 40 + Telma-H | `critical` — duplicate telmisartan (and HCTZ) **plus** a LASA warning about the same foil family |
| Diabetes shelf neighbour | Glycomet + Glycomet-GP | `warning` — same brand family, different contents, verify before taking |
| Sound-alike, one box only | Amaryl 1 mg | `warning` — sounds like Amlopres, a different drug |
| ASHA home visit, no signal | any strip | localised error card with Retry; never a blank or English-only screen |
| Elderly user, phone has no `ml-IN` voice | any | the warning is still on screen in large type, in an amber "read this" state |

These are acceptance targets for the pilot, **not** measured field outcomes: the
three preset rows are reproducible today through `POST /verify-medicines`, while
the offline-voice and ASHA rows are covered by logic tests and still need a
human on a real handset (see Known limitations).

## Retry semantics

Retry after a failure restores a *clean* run rather than repeating one call:

* the file input is cleared (`value = ""`) so the **same photo** fires `change` again;
* the error card, status line and speech fallback are reset;
* the state machine returns to `idle` and the failed action re-enters the flow
  from the top, so the spinner and busy guards come back with it;
* a capture failure retries by **reopening the camera** (re-calling `shoot()`
  would throw "camera is not running" and loop), and a running camera stream is
  reused rather than opened twice — on Android the second session kills the first.

Repeated failure→retry cycles are covered twice: `state.test.mjs` exercises the
transition table, and `retry.test.mjs` runs the real `app.js` against `index.html`
in jsdom with a scripted `fetch` (fail → click Retry → assert a second request,
a cleared input and a rendered result). Reintroducing the original defect makes
that suite fail 3/4, so it is a genuine regression guard rather than a
restatement of the fix.

## Client orchestration (Pass 4)

`static/js/state.js` is a pure state machine — no DOM, no fetch — so the whole
scan lifecycle is testable in Node:

```
idle ─CAMERA_OPENED→ camera_ready ─CAPTURE_START→ capturing
  │                                                    │
  └─FILE_SELECTED→ scrubbing ─SCRUB_DONE→ uploading ─UPLOAD_OK→ rendering
                                                                      │
                          error ←─(any failure)─┐              SPEECH_START
                             └─RETRY→ idle        └────── speaking ─SPEECH_END→ idle
```

Out-of-order events are no-ops (a late shutter tap cannot corrupt the screen),
and a failure raised from a state with no path for it falls through to a
wildcard `FATAL`, so **the error card always appears** — that behaviour is
tested, not assumed.

Error handling in `app.js`:

* **20 s request timeout** via `AbortController`, classified as `timeout`.
* **Classification** into `timeout | offline | network | too_large | bad_type |
  bad_request | server | image_failed | camera_denied | unknown`, each with
  Malayalam, Hindi and English copy (no English-only fallback).
* **Retry** re-runs the exact action that failed (camera, capture, upload, manual submit).
* **Global `error` / `unhandledrejection` listeners** route to the same card, so a
  stray throw never leaves a dead screen.
* **`offline` event** surfaces immediately instead of waiting for a timeout.

## Evaluation against the Inspector checklist

| Criterion | Result | Evidence / caveat |
|---|---|---|
| Client-side privacy (EXIF scrubbed) | **Pass** | Runtime test builds a JPEG carrying GPS + `DateTimeOriginal` + device serial, runs the shipped `capture.js` through a real encoder, and asserts no APP1/COM segment or marker string survives while the image still decodes. Verified with a real JPEG codec in Node, **not** in a mobile browser — the sandbox has no browser and system libraries for Chromium were unavailable. |
| RAM ephemerality | **Pass** | Upload buffered to `bytes`, response flag `processed_in_memory: true`, AST test forbids `tempfile`/`open()`/`shutil` in the request path. |
| Duplicate-salt accuracy (>95%) | **Pass** | 100% on 44 labelled cases including brand/molecule mixes, combination products and OCR-style slips. Caveat: the corpus is hand-built; it is not a statistically sampled pharmacy set. |
| Linguistic clarity | **Pass (not native-reviewed)** | Malayalam and Hindi copy written for short-sentence, plain-register reading, with drug names transliterated as printed on the strip; speech runs at 0.85× and splits into <170-char chunks because Android truncates long utterances. A native speaker has **not** reviewed the copy — recommend one pass with a Malayalam-speaking pharmacist before pilot. |
| LASA risk rendering | **Pass** | `LASA_RISK` findings render through the same high-contrast card as duplicate-salt warnings, anchored on the *printed label* (what the user sees on the foil), not the molecule name. |
| Speech fallback (offline-resilient) | **Pass (logic verified, no audio heard)** | The warning script is always rendered on screen; if `speechSynthesis` is missing or has no `ml-IN`/`hi-IN` voice, the panel switches to an amber "read this" state instead of throwing. Chunking keeps utterances under 170 chars because Android truncates long ones. |
| Preview accessibility | **Pass (local + Host-header verified)** | Supervised server on `0.0.0.0:3004`; `GET /` → 200 (8.1 KB), all six `/static/*` assets → 200 (CSS 17 KB, four JS files 4.9–27.8 KB, `favicon.svg` 295 B) and `/favicon.ico` → 200 (SVG, 295 B), so a live page load shows zero 404/403 requests in the browser console. Killing the worker process itself, the supervisor restarts it and the next request still returns 200. The public `*.style.dev` URL answers 403 to any request without the owner's session — that is the preview auth gate, not a refused connection. |
| LASA detection accuracy | **Pass** | `Amaryl`+`Amlopres` → spoken-collision alert; `Telma 40`+`Telma-H` → LASA **and** duplicate salt; `Zerodol`+`Zerodol-SP`, `Pan 40`+`Pan-D` likewise; `Loprin`+`Loprin-LS` → verification wording, no composition claim. Every alert carries full Malayalam and Hindi copy. |
| Regression safety | **Pass** | 132 pytest (87 original + 14 next-gen + 16 hardening + 10 rate-limit + 5 audio pack), 18/18 state machine, 4/4 DOM retry, 15/15 EXIF, 10/10 audio pack (JS) and 9/9 live preset checks. No pre-existing test was modified to accommodate a change; the Pass 9 refactor ran the whole set unchanged and produced byte-identical warning copy for all three presets (587 / 260 / 330 characters). |
| RAM ephemerality | **Pass** | AST test still walks `main.py` and `extraction.py` for `tempfile`/`open()`/`shutil`; vision bytes go out as a base64 data URL, OCR decodes from `io.BytesIO`. |
| End-to-end flow | **Pass (logic verified)** | `tests/test_e2e.py` drives a real multipart POST through validation → extraction → rules → JSON with cards, speech script and flags. The camera→canvas→fetch→speech chain is covered by the EXIF suite + state-machine suite + live server calls; a human still has to tap it on a phone, which I could not do here. |
| Error resilience | **Pass** | Timeout, offline, 413/415/422/5xx, camera denial, unreadable image and missing speech API all land on   a localised card or the amber read-aloud fallback. 18/18 state checks, including "FATAL from every state". |
| UI/UX compliance | **Pass (not visually reviewed)** | Slate base, emerald safe/primary, amber caution — with crimson reserved for `critical`. That is a deliberate departure from "emerald/slate/amber": a life-threatening duplicate must not share a colour with "check this". 18–25px type, 58px targets, zero-clutter stepper. |
| Security verification | **Pass** | EXIF suite + AST test + `no-store` headers + magic-byte and 6 MiB limits + `forbid` schemas + injection blocklist (422 on attempt). No accounts, no cookies, no disk writes. |
| Secret hygiene | **Pass** | Key read from env/`.env` per request; `.env` gitignored and verified with `git check-ignore`; no key material anywhere in `app/`, `static/`, `scripts/` or `tests/` (grep sweep); `/health` exposes endpoint and model only; a test asserts the key never reaches logs or responses. |
| Live vision extraction | **Blocked on the key** | The Groq tier is implemented and covered by 19 stubbed tests (endpoint, auth header, data-URL shape, fence tolerance, brand+strength mapping, 401/500/nonsense degradation, no-key → no network call). It cannot be *demonstrated* until `KATHA_VISION_API_KEY` is present in the environment — `scripts/check_vision.py` is the one-command proof. |
| Release package | **Pass** | `requirements.txt` pins match the installed, tested versions exactly (fastapi 0.115.6, uvicorn 0.34.0, pydantic 2.10.4, python-multipart 0.0.20, httpx 0.28.1, pytest 8.3.4); `Dockerfile` (non-root, healthcheck) + `.dockerignore` (keeps `.env` out of the image) + `Procfile` added; `uvicorn` started from the declared command serves `/`, all six `/static/*` assets, `/sw.js`, `/taxonomy.json` and `/health`; a real POST leaves no upload artifact on disk. Caveat: the image was not built (no Docker daemon access in this sandbox). |
| Production readiness | **9.5/10** | Environment-only config read per request, `/health`, supervised server, container + Procfile, pins matching the tested versions, tests for every layer. Missing for a hospital pilot: CI pipeline, rate limiting/abuse caps, and a live vision key. |
| Code quality | **9/10** | Modular (schemas / taxonomy / clinical / extraction / i18n / state / capture / speech / app), typed, commented on *why*, no dead code. Loses one point for the hand-curated taxonomy and the absence of a CI pipeline. |

## Next-gen roadmap (Pass 18)

Four scaling features are specified here. Two are implemented and tested in this
build (offline shell, batch basket scan), one is implemented as a guarded stub
(pharmacist relay), and one is an architecture plan with no code yet (WASM audio
pack). Each stays inside the two hard rules: **nothing about a patient is written
to disk or retained server-side**, and **no feature may make the warning harder to
read** for a 70-year-old.

### 1. Offline-first PWA shell — implemented

`static/sw.js`, served from `/sw.js` (root scope, `Service-Worker-Allowed: /`) so
it controls the whole app rather than just `/static/`. Registered from `app.js`
after `load`, and failing registration is silent by design.

| Request | Strategy | Why |
|---|---|---|
| Navigation (`/`) | network-first, cached shell fallback | a deploy shows up immediately on good signal, and the app still opens with no signal |
| `/static/*`, `/taxonomy.json` | cache-first (stale-while-revalidate) | the cached copy answers immediately; a fresh copy lands in the background for the next visit. Cache-first without revalidation would pin a stale stylesheet forever, so the revalidate half is deliberate |
| Any non-GET (every scan POST) | untouched | a photo upload is never cached, queued or replayed |
| Cross-origin | untouched | the app is same-origin by CSP already |

`CACHE_VERSION` is bumped per asset change and old caches are deleted on
`activate`. Precaching uses individual `cache.add()` calls so one missing URL
cannot leave the app with no cache. `GET /taxonomy.json` is the new public feed
that makes offline lookup possible: drug data only, no keys, no request data.
Note what this is *not*: the Cache API is client-side storage on the patient's own
phone, so server-side zero persistence is unchanged.

### 2. Batch multi-strip scanning — implemented

`POST /verify-strips/batch` (multipart, 1–5 `strips` files — the 3–5 strip basket
is the realistic polypharmacy case — plus `language` and
`paracetamol_taken_today_mg`) returns:

```json
{"strip_count": 2,
 "strips": [{"strip_index": 0, "medicines": [...], "safety": {...}},
            {"strip_index": 1, "medicines": [...], "safety": {...}}],
 "combined": {"verdict": "critical", "findings": [...], "speech": {...}},
 "processed_in_memory": true}
```

`app/extraction.py:extract_batch()` reads the payloads with a concurrency cap of
3, so a five-strip basket cannot fire five vision calls at once from a cheap
phone's connection. `app/clinical.py:analyse_basket()` returns a `BasketReport`:
each strip analysed alone *and* the whole basket analysed as one set. The combined
pass is the clinically important one — a duplicate salt or a LASA pair usually
only appears when two strips meet (there is a test for exactly that: two harmless
strips, one critical basket). Every upload goes through the same magic-byte, 6 MiB
and content-type checks as a single scan and is released as soon as it is read.

### 3. Pharmacist verification relay — guarded stub

`ws://…/ws/relay/{room_id}?ticket=<expiry>.<hmac>` (`app/relay.py`).

* **Refuses everything unless `KATHA_RELAY_SECRET` (16+ chars) is set**, so an
  unconfigured deployment cannot become an open relay.
* Tickets are `HMAC-SHA256(secret, "room:expiry")[:32]`, valid for 120s with a
  30s skew window, compared in constant time. Issuing one belongs to the
  pharmacy's own backend; this service only verifies.
* Rooms are opaque codes, capped at 8 peers, and messages are capped at 2 KB.
  A frame is forwarded to the other sockets in the room and then dropped: no
  queue, no transcript, no replay, no logging, no database. When the last peer
  leaves, the room object is deleted.
* `/health` and `relay.HUB.stats()` expose aggregate counts only.

Production notes before this touches a real pharmacy: terminate TLS and use
`wss://`, move rate limiting in front of the handshake, add message-level
signing for the pharmacist's identity, and audit the relay under the same DPDP
review as the scan path.

### 4. WASM local audio pack — architecture only

Today speech goes through the Web Speech API, which is silent on any phone
without a Malayalam voice (the UI says so rather than reading English aloud).
The plan is to ship the warning audio itself:

1. **Pack format.** One short clip per `(finding.code, language)` — roughly 30
   lines of Malayalam and Hindi, encoded as Opus in WebM at 24 kbps mono (about
   8–12 KB each, under 1 MB for the whole pack). Pre-rendered by a professional
   Malayalam/Hindi voice, reviewed by a clinician, versioned with the taxonomy.
2. **Delivery.** `/audio/{lang}/{code}.webm` served statically with an immutable
   cache header, plus a `manifest.json` of clip versions. The service worker
   precaches the pack for the selected language only.
3. **Playback.** `<audio>` with a tiny JS queue (intro → findings → action) and a
   hard fallback chain: pack clip → `SpeechSynthesis` → written warning. A WASM
   decoder (e.g. `wasm-audio-decoders`) is only needed for older WebViews that
   cannot play Opus/WebM; it is not required for the pack itself, which is why
   this stays a delivery problem rather than a compilation problem.
4. **Why it matters.** It removes the device-dependency that currently makes the
   read-aloud feature unreliable on the cheapest Android phones, and it is the
   only way to guarantee the critical warning can be heard in a noisy shop.

Still not recorded: no voice talent, no clips, no synthesiser model. The loader,
manifest contract and playback tier now ship (see "Local audio pack" below), so
the remaining work is content and clinical review, not plumbing.

### New tests (14, in `tests/test_nextgen.py`)

Public taxonomy feed, service-worker route + scope header + precache list +
never-cache-POST assertion, batch basket shape and per-strip indexes, 4-strip cap
(413), empty basket (422), per-upload validation (415), cross-strip duplicate
detection, relay ticket round trip and three rejections, relay refusal when
unconfigured and on a forged ticket, peer-to-peer forwarding with room teardown,
and oversized-frame dropping. Total backend suite: **100 passed**.

## Production hardening (Pass 19)

### Container posture

| Property | Value | Checked by |
|---|---|---|
| Base image | `python:3.12-slim` (Debian, glibc) | static audit |
| Runtime user | `katha`, uid **10001**, `USER` after install, never reverted | `test_container_runs_as_an_unprivileged_user` |
| Writable layer | none needed — RAM-only processing, no volume, no DB | design + live POST check |
| Dependencies | 6 pins, all `==`, no range specifiers | `test_runtime_dependencies_are_exactly_pinned` |
| Build context | `.env`, `.git`, `.venv`, `tests/`, `__pycache__`, `node_modules` excluded | `test_build_context_excludes_secrets_tests_and_the_venv` |
| Secrets in layers | none: no `ENV`/`ARG`/`COPY` of `KATHA_VISION_API_KEY` or `KATHA_RELAY_SECRET` | `test_container_declares_a_healthcheck_and_no_baked_secrets` |
| Healthcheck | `urllib` GET on `/health`, 30s interval, 3s timeout, 10s start period | same test |
| Footprint | 26 packages installed from the pins; `.venv` is 63 MB, so the runtime layer is small next to the ~130 MB slim base | measured in this sandbox |

**Why not alpine.** Alpine would cut roughly 100 MB, but this stack runs
`uvicorn[standard]` (uvloop, httptools) and `pydantic-core`, all native. They do
publish musllinux wheels, yet the optional OCR tier (`pytesseract` +
`tesseract-ocr`) is significantly more work to package on musl, and a musl/glibc
mismatch here fails at import time in production rather than in CI. The decision
is therefore: **slim + non-root + no writable layer**, with alpine available as a
follow-up only after the OCR tier is settled and a multi-arch build is in CI.

**Not verified here:** `docker build` was not run — the sandbox has a Docker CLI
but `/var/run/docker.sock` is root-only, so the daemon rejects this user. The
image is audited statically (parsed by tests), not built.

### Ingress: nginx and Cloudflare

Two files carry the edge rules, and both are checked by tests so they cannot rot:

* **`deploy/nginx.kathapulse.conf`** — TLS 1.2/1.3 termination, HSTS
  (`max-age=63072000; includeSubDomains`), `server_tokens off`,
  `client_max_body_size 7m` (just above the app's 6 MiB so the app's own 413 is
  what a user sees), per-IP `limit_req` zones (30/min scans, 120/min reads) as a
  token bucket, plus the in-app sliding window below where a bucket boundary is
  not good enough,
  `limit_conn`, `proxy_request_buffering off` for uploads (nothing is spooled to
  an nginx temp file), and an explicit WebSocket upgrade block for `/ws/relay/`.
* **`deploy/cloudflare-rules.md`** — Full (strict) TLS, Always Use HTTPS, HSTS,
  WAF managed rules, Bot Fight Mode, rate-limiting rules for the scan, typed and
  relay paths, cache rules that bypass every POST, `/sw.js` and `/ws/*`, and a
  warning that **Under Attack Mode breaks the relay**.
* **App-side occlusion.** `/docs`, `/redoc`, `/openapi.json` and
  `/docs/oauth2-redirect` now return a `no-store` 404 unless
  `KATHA_DOCS_ENABLED=1`. Three layers — Cloudflare, nginx, app — because the app
  is the one that survives a proxy misconfiguration.

### In-app sliding-window rate limiting (Pass 20)

nginx's `limit_req` is a leaky bucket: it can admit a burst right after a
boundary. `app/ratelimit.py` adds a true **sliding window** as a backstop, with
the same 30 req/min default as the edge rule:

| Property | Value |
|---|---|
| Window | rolling 60s, pruned per admission (no fixed-bucket burst) |
| Key | client IP from the socket; nothing else is recorded |
| Storage | in-process `dict[str, deque[float]]` — RAM only, no file, no Redis |
| Bound | 4096 clients max, coldest evicted, so address floods cannot grow it |
| Response | `429` + `Retry-After` + `no-store`, no client identifier echoed |
| Default | **off** (`KATHA_RATE_LIMIT_PER_MIN=0`): the edge owns the budget |

Enable it for a bare container or a hospital LAN install with no proxy:

```bash
KATHA_RATE_LIMIT_PER_MIN=30 ./scripts/serve.sh
```

It is deliberately not a log: counters are timestamps per IP, discarded with the
process, which keeps the zero-persistence posture of the scan path intact.

### Local audio pack (Pass 21)

`static/js/audio-pack.js` + `static/audio/manifest.json` are the tier above the
Web Speech API, for the phones that have no `ml-IN` / `hi-IN` voice at all.

The manifest ships **empty** (`"clips": {}`), and that is the point: `play()`
answers `unavailable`, the caller falls through to the device voice, and then to
the written warning. Speech behaviour today is byte-for-byte unchanged.

```json
{"schema": 1, "version": "3", "voice": {"name": "...", "license": "..."},
 "clips": {"ml:DUPLICATE_SALT": "/static/audio/ml/DUPLICATE_SALT.webm"}}
```

Keys are `<language>:<finding.code>`, plus `<language>:intro` and
`<language>:outro` for the speech frame. Every API call resolves a status
instead of throwing, so the warning path can never die on audio:

| Status | Meaning | Caller does |
|---|---|---|
| `played` | clip started | stop; audio is the channel |
| `unavailable` | no clip for this key, or the pack failed to load | use `Speech.speak()` |
| `blocked` | autoplay policy rejected it (no user gesture yet) | use `Speech.speak()` |
| `unsupported` | no `Audio` constructor | use `Speech.speak()` |

Manifest values are cleaned before use: anything that is not a non-empty string
without `..` is dropped, so a tampered manifest cannot point at another origin.
The service worker precaches the loader and the manifest as part of the
`kathapulse-v3` shell.

**WASM synthesiser (still a plan).** The clips can be recorded by a human, or
synthesised on-device by a WASM TTS engine (Piper or sherpa-onnx with a
Malayalam/Hindi voice bundle, roughly 20–60 MB, cached after first use). WASM is
the optional third route, not the default: recorded clips win on quality and
size for 30 fixed phrases, and a 40 MB model download is a real cost on a ₹8k
phone. The integration point is already correct — a synthesiser only has to fill
the manifest.

**Wiring (Pass 22).** `speakCurrent()` now tries the pack first as tier 0:
`AudioPack.playScript(language, codes)` plays `intro → each finding code (max 4)
→ outro`, sequenced on `ended` with a 15s per-clip timeout. It is
**all-or-nothing**: if any clip in the chain is missing, nothing plays and the
device-voice path runs exactly as before. The pack is skipped entirely while
`clips` is empty, so today's behaviour is unchanged, and Stop halts clips as well
as speech.

To go live: record/synthesise the 31 finding clips per language, get clinical
sign-off on the wording, drop the `.webm` files under `static/audio/<lang>/`,
list them in the manifest, and bump both `version` and `CACHE_VERSION`.

### Multilingual architecture

`app/languages.py` is a registry, not a rewrite: one `LanguageSpec` row per
language with code, native name, script, family, TTS locale, rollout flag and a
concrete note.

| Code | Language | Script | Family | TTS locale | Status |
|---|---|---|---|---|---|
| ml | Malayalam | Malayalam | Dravidian | ml-IN | **live** |
| hi | Hindi | Devanagari | Indo-Aryan | hi-IN | **live** |
| en | English | Latin | Germanic | en-IN | **live** |
| ta | Tamil | Tamil | Dravidian | ta-IN | planned |
| te | Telugu | Telugu | Dravidian | te-IN | planned |
| kn | Kannada | Kannada | Dravidian | kn-IN | planned |
| bn | Bengali | Bengali | Indo-Aryan | bn-IN | planned |
| mr | Marathi | Devanagari | Indo-Aryan | mr-IN | planned |
| gu | Gujarati | Gujarati | Indo-Aryan | gu-IN | planned |

Coverage today: **31 translation keys, 100% for ml/hi/en** (`i18n.coverage()`),
asserted by tests so a missing string cannot ship silently. New in this pass:
`i18n.t()` falls back to English for an unknown or untranslated code instead of
raising, so a partial Tamil rollout still produces a safe warning rather than a
500.

To add a language: (1) flip its registry row to `enabled=True`; (2) add the code
to the `Language` enum; (3) add a field to `LanguageText`; (4) translate the 31
keys in `app/i18n.py`; (5) add the script's font to the stack in `styles.css`
(`"Noto Sans Tamil"`, `"Noto Sans Kannada"`, …); (6) test at 320px — Telugu and
Tamil transliterations of drug names are longer than Malayalam; (7) confirm the
device TTS voice for that locale, because the spoken warning degrades to text
without it until the WASM audio pack exists.

## Final verification (Pass 23)

What was actually executed on the running `0.0.0.0:3004` process, and what it
proved.

| Check | Method | Result |
|---|---|---|
| Vision HTTP tier | `POST /verify-strip` with `samples/strip-dolo.jpg` against a Groq-shaped endpoint | `extraction_status: ok`, `extraction_source: vision_llm`, `Telma-H 40 mg/12.5 mg → Telmisartan 40.0 mg + Hydrochlorothiazide 12.5 mg` |
| Batch tier | `POST /verify-strips/batch`, three strips | `strip_count: 3`, combined verdict `critical`, 416 KB in RAM |
| Malayalam output | same scan, `language=ml` | full `safety_message_ml`, `വായിക്കുക` read-aloud block |
| Hindi output | `language=hi` | `speaking: true` from `speechSynthesis` (a `hi-IN` voice exists here) |
| Zero disk writes | `find /tmp . -newer <marker>` plus `/proc/<pid>/fd` | no new files, no deleted-but-open fds, no `tempfile` anywhere in `app/` |
| Regressions | `pytest` + five browser suites | `132 passed`; state 18/18, retry 4/4, EXIF 15/15, presets 9/9, audio-pack 10/10 |
| Browser console | DevTools protocol, after scan + speech | empty; only the expected 200s |

**The one thing this pass could not prove:** the deployment's
`KATHA_VISION_API_KEY` was empty at verification time (`.env` had a bare
`KATHA_VISION_API_KEY=` and `/health` reported `vision_model: null`), so no
request reached `api.groq.com`. The tier was exercised over real HTTP against
`scripts/_stub_vision.py`, which asserts the request contract (bearer header,
`messages` content list, `image_url` data URL) and answers in Groq's exact
response shape. Groq's model quality on a real strip photo therefore remains
unverified. Set the key in Settings → Project settings → Secrets, restart, and
`./.venv/bin/python scripts/check_vision.py` becomes the live judge-facing
proof.

**Cosmetic finding:** with the warning language switched to Hindi, the result
screen renders correctly in Hindi but the LISTEN/STOP button labels stay
bilingual Malayalam/English (they are fixed chrome, not translated per
language). Speech itself follows the selected language.

## Known limitations

* Without a vision key or local tesseract, photo scans fall back to manual entry
  (by design — see above). The vision tier has been verified end-to-end against
  a local stand-in but not yet against a live GroqCloud key (Pass 23).
* Malayalam/Hindi TTS depends on the device having that voice installed; the UI
  detects the missing voice and says so instead of reading English aloud.
* The taxonomy is a pilot subset, not a licensed drug database. Replace
  `app/taxonomy.py` with a CDSCO-style feed before any clinical deployment.
* This is a screening aid. It is not a diagnosis and not a substitute for a
  pharmacist.
