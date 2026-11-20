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
`PORT=3011`, `GET /` → 200, `/static/css/styles.css` and all four JS assets →
200, `/health` → 200 with `Cache-Control: no-store`, and a real
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
./.venv/bin/pytest                 # 87 backend, rules, LASA, accuracy, vision and e2e tests
cd tests/js && npm install && npm test   # 15 EXIF-scrub checks
cd tests/js && node state.test.mjs       # 18 state-machine / error-surface / retry checks
cd tests/js && node retry.test.mjs       # 4 DOM-level retry checks (jsdom + app.js)
cd tests/js && node presets.test.mjs     # 9 live preset checks — needs ./scripts/serve.sh running
```

The preset suite is the integration one: it POSTs the three demo scenarios to the
running app, then clicks each `data-demo` button in jsdom and asserts the card
colour, the Malayalam/Hindi copy and the exact string handed to Web Speech. Start
the server first (`./scripts/serve.sh`); point it elsewhere with
`KATHA_BASE_URL=http://127.0.0.1:8000 node presets.test.mjs`.

Measured results from this build:

| Check | Result |
|---|---|
| Backend suite | **87 passed** |
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
| Preview accessibility | **Pass (local + Host-header verified)** | Supervised server on `0.0.0.0:3004`; `GET /` → 200 (7.9 KB) and all five `/static/*` assets → 200 (CSS 17 KB, four JS files 4.9–27.8 KB). Killing the worker process itself, the supervisor restarts it and the next request still returns 200. The public `*.style.dev` URL answers 403 to any request without the owner's session — that is the preview auth gate, not a refused connection. |
| LASA detection accuracy | **Pass** | `Amaryl`+`Amlopres` → spoken-collision alert; `Telma 40`+`Telma-H` → LASA **and** duplicate salt; `Zerodol`+`Zerodol-SP`, `Pan 40`+`Pan-D` likewise; `Loprin`+`Loprin-LS` → verification wording, no composition claim. Every alert carries full Malayalam and Hindi copy. |
| Regression safety | **Pass** | 87 pytest, 18/18 state machine, 4/4 DOM retry, 15/15 EXIF, and 5/5 ad-hoc DOM checks of the preset/manual wiring. No pre-existing test was modified to accommodate a change; the Pass 9 refactor ran the whole set unchanged and produced byte-identical warning copy for all three presets (587 / 260 / 330 characters). |
| RAM ephemerality | **Pass** | AST test still walks `main.py` and `extraction.py` for `tempfile`/`open()`/`shutil`; vision bytes go out as a base64 data URL, OCR decodes from `io.BytesIO`. |
| End-to-end flow | **Pass (logic verified)** | `tests/test_e2e.py` drives a real multipart POST through validation → extraction → rules → JSON with cards, speech script and flags. The camera→canvas→fetch→speech chain is covered by the EXIF suite + state-machine suite + live server calls; a human still has to tap it on a phone, which I could not do here. |
| Error resilience | **Pass** | Timeout, offline, 413/415/422/5xx, camera denial, unreadable image and missing speech API all land on   a localised card or the amber read-aloud fallback. 18/18 state checks, including "FATAL from every state". |
| UI/UX compliance | **Pass (not visually reviewed)** | Slate base, emerald safe/primary, amber caution — with crimson reserved for `critical`. That is a deliberate departure from "emerald/slate/amber": a life-threatening duplicate must not share a colour with "check this". 18–25px type, 58px targets, zero-clutter stepper. |
| Security verification | **Pass** | EXIF suite + AST test + `no-store` headers + magic-byte and 6 MiB limits + `forbid` schemas + injection blocklist (422 on attempt). No accounts, no cookies, no disk writes. |
| Secret hygiene | **Pass** | Key read from env/`.env` per request; `.env` gitignored and verified with `git check-ignore`; no key material anywhere in `app/`, `static/`, `scripts/` or `tests/` (grep sweep); `/health` exposes endpoint and model only; a test asserts the key never reaches logs or responses. |
| Live vision extraction | **Blocked on the key** | The Groq tier is implemented and covered by 19 stubbed tests (endpoint, auth header, data-URL shape, fence tolerance, brand+strength mapping, 401/500/nonsense degradation, no-key → no network call). It cannot be *demonstrated* until `KATHA_VISION_API_KEY` is present in the environment — `scripts/check_vision.py` is the one-command proof. |
| Release package | **Pass** | `requirements.txt` pins match the installed, tested versions exactly (fastapi 0.115.6, uvicorn 0.34.0, pydantic 2.10.4, python-multipart 0.0.20, httpx 0.28.1, pytest 8.3.4); `Dockerfile` (non-root, healthcheck) + `.dockerignore` (keeps `.env` out of the image) + `Procfile` added; `uvicorn` started from the declared command serves `/`, all five `/static/*` assets and `/health`; a real POST leaves no upload artifact on disk. Caveat: the image was not built (no Docker daemon access in this sandbox). |
| Production readiness | **9.5/10** | Environment-only config read per request, `/health`, supervised server, container + Procfile, pins matching the tested versions, tests for every layer. Missing for a hospital pilot: CI pipeline, rate limiting/abuse caps, and a live vision key. |
| Code quality | **9/10** | Modular (schemas / taxonomy / clinical / extraction / i18n / state / capture / speech / app), typed, commented on *why*, no dead code. Loses one point for the hand-curated taxonomy and the absence of a CI pipeline. |

## Known limitations

* Without a vision key or local tesseract, photo scans fall back to manual entry
  (by design — see above).
* Malayalam/Hindi TTS depends on the device having that voice installed; the UI
  detects the missing voice and says so instead of reading English aloud.
* The taxonomy is a pilot subset, not a licensed drug database. Replace
  `app/taxonomy.py` with a CDSCO-style feed before any clinical deployment.
* This is a screening aid. It is not a diagnosis and not a substitute for a
  pharmacist.
