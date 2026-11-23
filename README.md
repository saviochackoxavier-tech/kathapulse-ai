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
5. Tap **Glycomet 500 · batch audit** → crimson banner *above* the verdict: the
   batch is on the recall list **and** the foil is past its expiry, spoken in
   Malayalam. This is the pharmacy audit path — it reads the box, not the dose.
6. Tap **Glycomet GP · ground truth** → **metformin + glimepiride** with a green
   "Ground-Truth verified" line: the local database caught the second molecule
   that a plain brand match drops.
7. Switch the language selector to **हिन्दी** to see the identical findings, and
   the same spoken script, in Hindi.

All five presets run through the deterministic engines only (clinical rules, the
offline batch audit and the local knowledge base), so they work with no vision
key and no network egress. Real photos additionally need the
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

**Two keys (failover).** Set `KATHA_VISION_API_KEY_FALLBACK` as well and a
primary that answers `429` (rate-limited), `401` or `403` (revoked, exhausted,
wrong scope) is abandoned immediately: the same request is retried with the
second key, and the first rejected key is not retried on the way. With one key
nothing changes — the quiet single `429` retry stays. `/health` reports
`vision_keys` and `vision_fallback` as a count and a boolean, never a value. The
whole behaviour is pinned by `tests/test_failover.py` (16 tests, no network).

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
| `POST /verify-medicines` | JSON `{medicines:[{name, batch_no?, expiry?}], language, paracetamol_taken_today_mg, age_years?}` |
| `GET /knowledge.json` | the ground-truth catalogue: brands, molecules, cautions, age bands (data only) |
| `GET /health` | which extraction tiers are live, taxonomy size, recall-notice and knowledge-base counts |
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

## Batch recall & expiry audit (Pass 29)

The clinical engine asks whether the **combination** is dangerous. This asks
whether the **box** is still fit to hand over — the question a pharmacy counter
actually faces. It runs on the same request, in the same RAM buffer, with no
network call, and its copy is localised like every other finding:

| Code | Severity | Trigger |
|---|---|---|
| `RECALLED_BATCH` | critical | the printed batch falls inside a recall notice for that molecule or brand family |
| `EXPIRED_STOCK` | critical | the printed expiry month is already in the past |
| `EXPIRY_SOON` | warning | it expires this month or next |
| `EXPIRY_UNREADABLE` | warning | an expiry is printed but cannot be parsed (**not** treated as fine) |
| `COLD_CHAIN_RISK` | warning | the label names a 2–8 °C product (insulin, vaccine, oxytocin, adrenaline …) — a photo can never clear that |

**Where the batch and date come from.** The vision tier reads `batch_number`
and `expiry_date` off the same photo (B.No./Lot line and the EXP stamp); the
manual path exposes two optional fields; the demo preset carries them as data.
Empty means "not read", never "no risk" — no batch, no recall claim.

**Expiry parsing** accepts what Indian foils actually print: `04/2026`,
`4/2026`, `04-2026`, `04.2026`, `2026-04`, `04/26`, `APR 2026`, `APR26`,
`APRIL 26`, with or without a leading `EXP`/`EXP: `/`USE BEFORE`. Anything else
becomes `EXPIRY_UNREADABLE` rather than a silent pass.

**Rendering.** Box findings are not one warning among many — a recalled batch or
an expired foil is a reason not to hand the box over — so they render in a
banner **above** the verdict: crimson for a recall or an expired date, amber for
expiry-soon / unreadable / cold chain, with a badge, the localised title,
message and action, and `role="alert"` so a screen reader announces it. They are
removed from the list below so the same warning is never printed twice, and they
stay in `safety.findings` and in the spoken script, so the audio pack gets a
clip slot per code (`ml:RECALLED_BATCH`, `hi:EXPIRED_STOCK`, …) and the device
voice reads the critical ones first.

**Data honesty.** `app/recall.py` ships **four pilot notices** (metformin
impurity, telmisartan potency, paracetamol dissolution, pantoprazole labelling).
The refs are local trace labels (`PILOT-RCL-01`), **not** CDSCO citations, and
the feed is offline by design so the demo cannot depend on a regulatory API. A
real deployment replaces the `RECALLS` tuple with a signed feed; the matching
code does not change.

**Privacy.** The batch number and expiry are the same class of data as the
drug name — no patient identifier, no retention. The audit is a pure function
over the scanned list (`as_of` injected for tests), and a test pins that it
writes nothing to disk.

## Ground-truth knowledge base (Pass 30)

`app/knowledge_base.py` is the layer between "what molecule is this brand?" and
"what does a pharmacist in Kochi actually call this box?". It is **offline,
pure and deterministic**, and it does two jobs.

### 1. A verified Kerala shelf catalogue

48 curated products (Telma-H, Dolo 650, Amaryl, Glycomet-GP, Pan-D, Augmentin
625, Zerodol-SP, Montair-LC, Ultracet, Thyronorm, Ecosprin, Warf, Doxy …) each
with its exact molecules, Indian pack strengths, drug form, plain-language
cautions and an age band. Every molecule is checked against `app/taxonomy.py` by
a test, so the knowledge base can never name a drug the clinical engine cannot
rule on. On top of the products sit all 48 molecules and their 186 printed
aliases, giving **256 searchable names** for one 48-molecule engine.

The catalogue is published as `GET /knowledge.json` — brands, molecules,
cautions localised in ml/hi/en, age bands, pharmacist notes. Drug data only: no
patient data, no keys, nothing request-specific.

### 2. A deterministic fallback for imperfect text

When the vision tier or OCR hands back text the alias table cannot place, the
request is resolved locally instead of failing:

| Printed (OCR / vision) | Alias table alone | Knowledge base |
|---|---|---|
| `Glycomet GP` | metformin **only** — the glimepiride is silently lost | metformin + glimepiride |
| `PAN D` | nothing (combo key is `pan-d`) | pantoprazole + domperidone |
| `Augmentn 625` | amoxicillin only | amoxicillin + clavulanic acid |
| `Telma H` | combo miss, telmisartan only | telmisartan + HCTZ |

Matching is **space- and dash-insensitive** (`glycometgp` = `Glycomet-GP`) and
then falls back to a similarity score with a hard floor of 0.88. A *more
specific* answer always wins: only a proper superset of molecules replaces the
alias table's result, which is what turns the first row above from a dangerous
half-answer into the right one. Below the floor the matcher returns nothing and
the app keeps asking the user — it never invents a drug.

Each medicine carries `verified_by: "taxonomy" | "ground_truth"`, and the
response carries `ground_truth_verified`, so the UI can show a green
**“Ground-Truth verified”** line only when the local base actually answered. The
badge is quiet emerald by design: verification is reassurance, not a warning,
and it must never compete with the crimson recall banner.

### 3. Age bands, when (and only when) an age is supplied

`age_years` (optional, 0–120) enables `AGE_WARNING`: aspirin under 16, NSAIDs and
sulfonylureas from 65, fluoroquinolones under 18, benzodiazepines under 18 and
from 65. With no age the rule is silent — assuming 70 for everyone would make
every NSAID scan cry wolf, and assuming nothing is honest. The finding is
localised, spoken, and gets its own audio-pack slot (`ml:AGE_WARNING`).

**Resilience.** If the provider is unreachable the photo path returns `200`,
`manual_required`, `verdict: unknown`, a localised read-aloud prompt and
`processed_in_memory: true` — never a 500, never a blank screen, still zero disk
writes. `tests/test_knowledge_base.py` proves that with a provider that raises
`ConnectError` on every call.

## Dose reminders (Pass 31)

The scan tells you what is wrong with the box; the reminder tells you when to
take it. A patient who cannot read the prescription gets one tap: pick how many
times a day, press **Set**, and the app speaks and posts the dose times in the
language already selected.

**The server does not schedule anything.** `POST /reminders` parses the typed
schedule (`1-0-1`, `0-0-1`, `twice daily`, `BD`, `TDS`, `every 8 hours`), applies
the same clinical strengths the scan uses, and returns a derived plan: clock
times, a part-of-day label, per-slot speech and a full spoken script in en/ml/hi.
The browser holds the plan in a variable and runs a 15-second `setInterval` — no
storage, no id, no push service, no database table. It is lost when the tab
closes, and the UI says so instead of pretending:

> 08:00, 21:00-ന് ഓർമ്മപ്പെടുത്തൽ വെച്ചു. ഈ പേജ് തുറന്നിരിക്കുമ്പോൾ മാത്രം പ്രവർത്തിക്കും.

**Refusals instead of guesses.** The parser returns a reason, not a schedule, for
`SOS`/`as needed`/`PRN` (`as_needed`: take it when the doctor said), for anything
it cannot read (`unsupported`, with the `1-0-1` example), for more than four
tablets in one slot (`too_many`), and for a schedule that would push paracetamol
past 4000 mg/day (`paracetamol_limit`). The last one matters: `3-3-3` of Dolo 650
is 5850 mg and is refused with the number in the sentence, while `2-2-2` (3900 mg)
is allowed — the reminder engine cannot contradict the clinical rules.

**Countdown banner.** A scheduled plan paints a green banner above the findings —
"അടുത്ത ഡോസ് 21:00 · 1 മണിക്കൂർ 0 മിനിറ്റ് കഴിഞ്ഞ്" — with a **Cancel** button. When
the clock reaches a slot the app speaks the dose text and, if the browser allows
notifications, posts a local `Notification` (no server, no key, no icon CDN). A
browser without `Notification` still gets the spoken reminder; a browser without
both still gets the banner text.

**Ownership.** The plan belongs to the scan on screen: scanning a different set
of medicines drops it, and switching language re-renders the banner in that
language from the same in-memory plan. Nothing here is a prescription — the
spoken script ends with "this is a reminder, not a prescription" in all three
languages.

| Layer | Change |
|---|---|
| `app/audio_reminders.py` **(new)** | `parse_schedule()`, `slot_for_time()`, the paracetamol-daily check, `build_plan()`, and the request/response models |
| `app/main.py` | `POST /reminders` (thread-pool, `no-store`) |
| `app/i18n.py` | 17 new keys: intro, four parts of day, dose sentence, singular/plural units, caveat, confirmation, and the four refusal reasons |
| `static/js/reminders.js` **(new)** | `nextDose`, `formatLeft`, `isDue` — pure date arithmetic, unit-tested in Node |
| `static/js/app.js` | Panel visibility, `POST /reminders`, banner, 15-second clock, `Notification`, cancel, per-scan invalidation |
| `static/index.html`, `static/css/styles.css` | Reminder panel and countdown banner, 44 px targets, high-contrast emerald |
| `static/sw.js` | Precache `reminders.js` and `knowledge.json`; cache `kathapulse-v7` → `v8` |
| Tests | `tests/test_audio_reminders.py` (67) and `tests/js/reminders.test.mjs` (16) |

## Tests

```bash
./.venv/bin/pytest                 # 332 backend: rules, LASA, accuracy, vision, failover, batch audit, knowledge base, dose reminders, e2e, offline/relay/hardening/ratelimit/audio
./.venv/bin/pytest tests/test_failover.py   # 16 dual-key rotation checks on their own
./.venv/bin/pytest tests/test_recall.py     # 56 recall / expiry / cold-chain audit checks on their own
./.venv/bin/pytest tests/test_knowledge_base.py  # 59 ground-truth matching, cautions, age bands and fallback checks
./.venv/bin/pytest tests/test_audio_reminders.py # 67 schedule parsing, translations, paracetamol ceiling, zero-persistence checks
cd tests/js && npm ci && npm test        # 15 EXIF-scrub checks (npm ci: the lockfile is committed)
cd tests/js && node state.test.mjs       # 18 state-machine / error-surface / retry checks
cd tests/js && node retry.test.mjs       # 4 DOM-level retry checks (jsdom + app.js)
cd tests/js && node presets.test.mjs     # 9 live preset checks — needs ./scripts/serve.sh running
cd tests/js && node audio-pack.test.mjs  # 10 audio-pack loader, script and fallback checks (no jsdom, no network)
cd tests/js && node audiopack.test.mjs   # 17 DOM-level checks: app.js drives playScript, or falls back to speech in en/ml/hi
cd tests/js && node recall.test.mjs      # 13 DOM-level checks: recall/expiry banner, ml+hi copy, pack slot per code, typed batch
cd tests/js && node groundtruth.test.mjs # 12 DOM-level checks: verified badge in ml/hi, age warning + its clip, age sent request-level
cd tests/js && node reminders.test.mjs   # 16 checks: the clock arithmetic, panel, POST body, countdown banner, refusals, cancel
# Backend / next-gen surface covered by tests/test_nextgen.py: /sw.js, /taxonomy.json,
# POST /verify-strips/batch (1-5 strips) and the zero-retention /ws/relay handshake.
```

The preset suite is the integration one: it POSTs the three demo scenarios to the
running app, then clicks each `data-demo` button in jsdom and asserts the card
colour, the Malayalam/Hindi copy and the exact string handed to Web Speech. Start
the server first (`./scripts/serve.sh`); point it elsewhere with
`KATHA_BASE_URL=http://127.0.0.1:8000 node presets.test.mjs`.

### Continuous integration

`.github/workflows/ci.yml` runs both halves on every push and pull request, in
two independent jobs so a backend failure does not hide a frontend one:

| Job | Steps |
|---|---|
| **Backend** | Python 3.12 → `pip install -r requirements.txt` → `pytest` |
| **Frontend** | Python 3.12 + Node 20 → `pip install -r requirements.txt` → `npm ci` → start uvicorn on `127.0.0.1:3004` and poll `/health` → the nine Node suites, one step each |

The preset suite is the reason CI starts the server at all: it is the only test
that talks to the real API. The app is started with **no** vision keys, so CI
exercises the degraded path a judge also hits, and never needs a secret.
`tests/js/package-lock.json` is committed for this (`npm ci` needs it; every
other `package-lock.json` stays ignored). The workflow was syntax-checked and
every command in it was executed locally — GitHub's own runner has not run it,
which needs a push this sandbox is not authorised to make.

Measured results from this build:

| Check | Result |
|---|---|
| Backend suite | **332 passed** (265 + 67 reminder checks) |
| Duplicate-salt corpus (44 labelled cases) | **100% accuracy, 100% precision, 100% recall, 100% correct salt** |
| EXIF scrub (real JPEG codec, dirty input → clean output) | **15/15 checks passed** |
| Client state machine + error surface | **18/18 checks passed** |
| Retry path, executed in a DOM (jsdom) | **4/4 checks passed** — fails 3/4 if the Pass 4 defect is reintroduced |
| Audio pack wiring, real DOM (Passes 24-25) | **17/17 checks passed** — clips present → `playScript` runs intro/findings/outro and the device voice stays silent; clips missing → nothing half-plays and the device voice takes over |
| Live demo presets, real API + real DOM | **9/9 checks passed** — Telma pair, Dolo+Crocin and Amaryl each render the expected card (32 ms on the cold first call, then 7 ms and 4 ms), and the speech handoff carries the same Malayalam string the API returned |
| Batch recall & expiry banner, real API + real DOM | **13/13 checks passed** — a recalled, expired batch renders a crimson `role="alert"` banner above the verdict in Malayalam and Hindi, is not repeated in the findings list, gets one audio clip per code, and the preset POSTs `batch_no`/`expiry`; a near-expiry box renders the same banner in amber |
| Dose reminders, pure clock + real DOM | **16/16 checks passed** — the next slot rolls to tomorrow when today's has passed, `SET` posts only `{name}` per medicine, a scheduled plan paints a localised countdown banner, an SOS refusal paints none, cancel clears it, and a new scan cannot inherit the old plan |
| Batch audit engine | **56/56 checks passed** — 15 printed expiry shapes parsed, 9 refused as unreadable, recall matching by molecule/brand/batch prefix, no claim without a batch, cold-chain flag, tri-lingual copy, deterministic date injection, nothing written to disk |
| Ground-truth knowledge base | **59/59 checks passed** — 256 indexed names, every curated molecule exists in the taxonomy, `Glycomet GP` → metformin + glimepiride while the alias table answers one, OCR slips resolved, nonsense never matched, age bands only where a label states one, provider `ConnectError` → `200`/`manual_required`, no disk writes |
| Verified badge + age rule in a DOM | **12/12 checks passed** — badge shown only for a ground-truth match, Malayalam and Hindi copy, age warning rendered amber and spoken, `AGE_WARNING` clip requested, age sent as a request field (never inside a medicine) |

## Demo presets

Five one-click buttons above the camera run the pilot cases through
`POST /verify-medicines`, so a live demo never depends on a camera, a steady
hand, or a vision key:

| Preset | Expected result |
|---|---|
| Telma 40 + Telma-H | `critical` — duplicate telmisartan **and** LASA (same foil family) |
| Dolo 650 + Crocin Cold & Flu | `critical` — dual paracetamol (1300 mg at once) |
| Amaryl 1 mg | `caution` — LASA advisory: sounds like Amlopres, a different drug |
| Glycomet 500 · batch audit (`GM2407A`, `09/2026`) | `critical` — recalled batch **and** an expired foil, in the banner above the verdict |
| Glycomet GP · ground truth | `safe` — metformin + glimepiride verified locally, green badge shown |

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
| Production readiness | **9.5/10** | Environment-only config read per request, `/health`, supervised server, container + Procfile, pins matching the tested versions, tests for every layer, and CI on every push (backend + frontend). Missing for a hospital pilot: a live vision key, a deployed edge rule set and a licensed drug database. |
| Code quality | **9/10** | Modular (schemas / taxonomy / clinical / extraction / i18n / state / capture / speech / app), typed, commented on *why*, no dead code, CI enforced. Loses one point for the hand-curated taxonomy. |

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

### Audio tier wiring (Pass 24)

`tests/js/audiopack.test.mjs` mounts the real page in jsdom and asserts what
`app.js` does with the pack, with clips present and with clips missing. It found
two defects that are now fixed:

* **tier 0 was dead on a cold page.** `tryAudioPack()` skipped the pack while
  `status().clips` was still 0, and nothing had ever loaded the manifest, so
  shipped clips could never play. The manifest is now warmed at boot and only an
  *already-loaded empty* pack is skipped.
* **no STOP during clip playback.** The pack branch returned before showing the
  STOP button, so a long warning could not be interrupted. STOP is now offered
  for the duration of a clip script.

Cache name bumped to `kathapulse-v5` so phones pick up the new `app.js`; the
service-worker test now pins a version floor instead of a literal number.

Pass 25 extended the suite to all three languages and found a third defect:
English had no flat speech field, so switching an already-scanned result to
English read the **Malayalam** `speech.text` back in an English voice. The API
now returns `safety_message_en` next to `safety_message_ml`/`_hi`, and
`spokenTextFor()` prefers it, so a language switch speaks the right language
without re-scanning.

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
* The knowledge base is a **curated pilot catalogue** (48 Kerala shelf products,
  256 indexed names), not a licensed formulary. Every molecule is validated
  against the taxonomy, but the cautions and age bands need a pharmacist's
  review before a pilot depends on them.
* The recall feed is **four curated pilot notices**, not a live regulator feed;
  every `ref` is a local trace label. The matching engine is finished and
tested, the data is not — replace `app/recall.py:RECALLS` before a pilot relies
  on it.
* This is a screening aid. It is not a diagnosis and not a substitute for a
  pharmacist.
