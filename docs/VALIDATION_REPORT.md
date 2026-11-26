# KathaPulse AI — Clinical, Translation & Offline Validation Report

**Build audited:** `v1.6.1` @ `5aeb05f`
**Date:** 25 November 2026
**Environment:** Python 3.12, `.venv` from `requirements.txt`; Node 26 + jsdom 24;
server at `0.0.0.0:3004`; vision key **not configured** (`vision_keys: 0`).

**Pass 36 addendum (25 November 2026):** §9 (security controls), §10 (Indian
legal and regulatory boundaries), §11 (knowledge-base integrity) and §12
(Stage 4 evidence captures) were added, and §7 gained the new browser
measurements. **No application code changed**: `app/` and `static/` are untouched
since `5aeb05f` (`git diff --stat 5aeb05f -- app static` is empty).

This report records **what the test suite actually proves**, what was checked in
a browser, and what remains unverified. It is deliberately not a marketing
document: every claim below cites a test file, a command, or a measurement. Where
a check could not run, it says so.

---

## 1. Method and scope

| Item | Value |
|---|---|
| Backend suite | **348 tests, 14 files, 0 failures, 0 skipped** (`pytest -o addopts="" -q`) |
| Frontend suite | **119 checks, 9 Node suites, 0 failures** |
| Translation inventory | **81 keys × 3 languages, 0 missing** |
| Clinical catalogue | 48 molecules, 48 curated Kerala brands, 256 indexed names |
| Batch audit data | 4 curated pilot recall notices |
| Browser measurements | Chromium at 320 px and 360 px (Pass 33; see §7) |
| Live provider calls | **None** — no API key in this environment |

Per-file backend counts in this build:

| Test file | Checks | Covers |
|---|---:|---|
| `test_accuracy.py` | 1 | 44-case duplicate-salt corpus, scored |
| `test_api.py` | 25 | contracts, upload validation, prompt-injection blocks, headers |
| `test_audio_pack.py` | 5 | shipped clip manifest integrity |
| `test_audio_reminders.py` | 67 | schedule parsing, refusals, translations, ceiling |
| `test_clinical.py` | 38 | duplicate salt, interactions, class duplication, LASA, age |
| `test_confidence_evidence.py` | 16 | confidence gate, evidence provenance, disclaimer |
| `test_e2e.py` | 4 | full ml and hi round trips through the API |
| `test_failover.py` | 16 | key rotation, status handling, secret hygiene |
| `test_hardening.py` | 16 | i18n coverage, container posture, registry |
| `test_knowledge_base.py` | 59 | catalogue integrity, resolution, age bands, fallback |
| `test_nextgen.py` | 14 | `/sw.js`, feeds, batch endpoint, relay handshake |
| `test_ratelimit.py` | 10 | optional sliding-window limiter |
| `test_recall.py` | 56 | expiry parsing, recall matching, tri-lingual copy |
| `test_vision.py` | 21 | model-output contract, sanitisation, tiers |

---

## 2. Clinical interaction and paracetamol-ceiling audit

### 2.1 Documented drug–drug interactions

`tests/test_clinical.py::test_documented_interactions_fire` is parametrised over
four clinically documented pairs, and asserts both the `INTERACTION` finding and
the *reason* in the English message:

| Pair | Expected risk text |
|---|---|
| Warf 5 + Ecosprin 75 | bleeding |
| Aldactone 25 + Telma 40 | potassium |
| Imdur 30 + Penegra 50 | blood pressure |
| Tramal 50 + Daxid 50 | serotonin |

Additional interaction tests in the same file:

- `test_dual_blockade_acei_plus_arb` — Cardace 5 + Telma 40 must be `critical`.
- `test_nitrate_pde5_is_critical` — Imdur 30 + Manforce 50 must be `critical`.
- `test_two_nsaids_flagged_as_class_duplicate` — Brufen 400 + Zerodol 100 is a
  same-class duplicate (`caution`).
- `test_acei_arb_pair_not_double_reported` — one interaction, not two banners for
  the same pharmacological event.

### 2.2 Duplicate salt and the paracetamol ceiling

| Test | What it pins |
|---|---|
| `test_dual_paracetamol_is_critical` | Dolo + Crocin → `DUPLICATE_SALT`, critical |
| `test_same_strip_listed_twice_is_not_a_duplicate` | the same box twice is not two exposures |
| `test_telmisartan_hctz_combo_plus_separate_hctz_is_a_duplicate` | combination + plain tablet overlap |
| `test_telmisartan_plus_plain_hctz_is_not_a_duplicate` | the same molecule at the same strength is not doubled by construction |
| `test_paracetamol_daily_ceiling_across_strips` | cumulative daily total across strips |
| `test_paracetamol_near_ceiling_warns` | 3,000–4,000 mg band warns without blocking |

The same limit is enforced on typed schedules
(`tests/test_audio_reminders.py`):

| Test | Arithmetic | Expected |
|---|---|---|
| `test_a_schedule_above_the_paracetamol_ceiling_is_refused` | Dolo 650 `3-3-3` = **5,850 mg/day** | refused, `reason == "paracetamol_limit"`, message names 5850 and 4000 |
| `test_a_schedule_at_the_ceiling_is_allowed` | Dolo 650 `2-2-2` = **3,900 mg/day** | scheduled, 6 doses |
| `test_the_ceiling_sums_every_paracetamol_brand_in_the_scan` | Dolo + Crocin, four times daily = **5,200 mg/day** | refused |
| `test_a_non_paracetamol_schedule_is_not_touched_by_the_ceiling` | Amaryl `1-1-1` | scheduled |
| `test_an_unknown_medicine_does_not_block_its_own_reminder` | unverified label | scheduled, no dose arithmetic invented |

The ceiling constant exists in exactly one place
(`app/clinical.PARACETAMOL_DAILY_MAX_MG = 4000.0`) and `app/audio_reminders.py`
imports it; this was consolidated in Pass 32 and is covered by the unchanged
suites.

### 2.3 Look-alike / sound-alike (LASA)

`tests/test_clinical.py` contains 11 LASA checks, including:
`test_lasa_same_brand_family_with_extra_molecule` (Telma vs Telma-H),
`test_lasa_pan_family`, `test_lasa_zerodol_family_is_both_lasa_and_duplicate`,
`test_lasa_sound_alike_across_families` (Amaryl/Amlopres),
`test_lasa_loprin_family_requests_verification` (a brand we recognise but refuse
to resolve to a molecule), and `test_lasa_not_raised_for_identical_contents`.
A single strip of Amaryl correctly raises an advisory about its twin, and the
verdict becomes `caution`.

### 2.4 Batch, expiry and recall

`tests/test_recall.py` (56 checks) covers:

- 15 printed expiry shapes (`04/2026`, `4/26`, `2026-04`, `APR 26`, `USE BEFORE …`)
  and 9 unreadable values that are reported, not assumed safe.
- Recall matching by molecule, brand token and batch prefix; no claim without a
  batch number.
- Expired → critical, expiring this/next month → warning, unreadable → warning.
- Cold-chain products (insulin, vaccines, oxytocin …) flagged for fridge-log
  verification.
- Tri-lingual copy and speech script; deterministic `as_of` injection so the
  result is auditable.
- Deduplication: the same box scanned twice does not double the banner.

**Honest limit:** the recall list is four curated pilot entries, not a live
CDSCO feed. The wording says "recall list", never "government recall". The API
returns a pharmacovigilance caveat stating that an unflagged batch is not
guaranteed safe, genuine, or free from quality defects.

### 2.5 Confidence-based rejection (Pass 33)

`tests/test_confidence_evidence.py` (16 checks) proves:

- a `low`-confidence read is refused **before** any taxonomy match
  (`matched: false`, `rejection: "low_confidence"`);
- a `medium` read resolves but sets `recapture_required`, and the HTTP response
  reflects it;
- an absent/unrecognised confidence changes nothing;
- OCR is `high` only for an exact catalogue hit;
- evidence never marks a molecule-default strength as read, and names the
  database (`taxonomy` / `ground_truth`) with review date `2026-11-25`.

### 2.6 What this does **not** establish

- No external clinical database (Stockley, Micromedex, BNF) was used to validate
  the rule set. The interactions are a small curated table; "100% accuracy" is
  claimed only for the **44-case duplicate-salt corpus** in `test_accuracy.py`,
  not for clinical practice.
- No clinician reviewed the warning text.
- Not a medical device; screening aid only.

---

## 3. Translation completeness and clarity

### 3.1 Inventory (measured, not estimated)

```
$ ./.venv/bin/python - <<'PY'
from app import i18n
print(len(i18n.TEXTS))
for lang in ("en","ml","hi"):
    c = i18n.coverage(lang)
    print(lang, c["translated"], "/", c["keys"], "missing:", len(c["missing"]))
PY
81
en 81 / 81 missing: 0
ml 81 / 81 missing: 0
hi 81 / 81 missing: 0
```

`tests/test_hardening.py::test_enabled_languages_are_fully_translated` asserts
`missing == []` and `percent == 100.0` for every enabled language.
`test_planned_languages_fall_back_to_english_instead_of_crashing` proves a
planned language (Tamil) degrades to English rather than raising.

### 3.2 Script correctness, not just key presence

Checks assert the actual Unicode blocks, so a transliterated English string
cannot pass as a translation:

| File | Evidence |
|---|---|
| `tests/test_clinical.py` | Malayalam script in findings and speech; Hindi speech names the drug and carries the instruction |
| `tests/test_recall.py` | Malayalam in every recall title/message, and in `safety_message_ml` |
| `tests/test_knowledge_base.py` | Malayalam in every localised caution, and in the age-warning script |
| `tests/test_audio_reminders.py` | Malayalam in slot labels, dose sentences, refusal messages and the endpoint's `speech.ml` |
| `tests/test_e2e.py` | Full ml and hi round trips through the real API |
| `tests/js/recall.test.mjs`, `groundtruth.test.mjs` | ml and hi copy rendered in a real DOM |

The nine frontend suites also assert the client-side copy, which is separate
from `i18n.TEXTS`: 10 error codes (`timeout, offline, network, too_large,
bad_type, bad_request, server, image_failed, camera_denied, unknown`), each with
en/ml/hi strings (`static/js/state.js`), and retry copy in all three.

### 3.3 Disclaimer clarity

| Disclaimer | Where it appears | Languages |
|---|---|---|
| Screening-aid disclaimer | `disclaimer` key on every `VerifyResponse` and `BatchVerifyResponse`; rendered at the foot of the result | en/ml/hi |
| Pharmacovigilance caveat (Pass 33) | `pharmacovigilance` → `batch_disclaimer`; rendered inside the batch/recall banner | en/ml/hi |
| Reminder scope | "the reminder runs while this page stays open" in the panel copy | en/ml/hi |
| Offline read-aloud | script always visible with an explicit "speech unavailable — read below" notice | en/ml/hi |

**Honest limit:** all three translations were written by the project author, not
a clinical translator. Coverage and script are machine-checked; **medical
accuracy of the Malayalam and Hindi wording has not been signed off by a native
clinical reviewer**. This is the largest outstanding validation gap.

---

## 4. Offline, low-confidence and error handling

### 4.1 Client error surface

`static/js/state.js` classifies every failure into one of 10 codes and carries
localised copy for each; `tests/js/state.test.mjs` (18 checks) asserts:

- timeout is distinguished from network failure;
- **offline wins over an HTTP status** — the phone knows better than a 500;
- `413` → too large, `415` → wrong type, `400/422` → bad request, `5xx` → server;
- camera denial is its own code with its own advice;
- unknown failures still produce readable copy in the selected language.

`tests/js/retry.test.mjs` (4 checks) drives the real DOM and proves a failed
upload leaves a readable, retryable card, and that retry re-enters the flow
instead of calling the request directly.

### 4.2 Low-confidence rejection UX

Verified in Chromium at 320 px (Pass 33):

- medium confidence → amber "Retake a clearer photo" card, verdict held at
  **Could not verify**, provenance badge withheld, retake text spoken, evidence
  fields marked *Unverified*;
- low confidence → the same card with the rejection wording plus the manual-entry
  card, and `manual_required` from the API.

Screenshots: `artifacts/viewport-320-recapture.png`,
`artifacts/viewport-320-batch.png` (generated artifacts, git-ignored).

### 4.3 Offline PWA

| Check | Result |
|---|---|
| `/sw.js` served from root with `Service-Worker-Allowed: /` | **Verified** (`HTTP/1.1 200`, header present) |
| Cache version | **`kathapulse-v10`** |
| Precache list includes shell, CSS, all six scripts, taxonomy, knowledge, audio manifest | **Verified in source** |
| POST requests never cached or replayed | **Verified in source and by design** |
| Offline navigation falls back to the cached shell | **Implemented; not exercised in an installed PWA here** |
| Offline manifest fetch degrades to the device voice | **Tested** — `tests/js/audiopack.test.mjs::offline manifest fetch degrades to the device voice` |
| Warning readable without a voice pack | **Tested** — read-aloud panel always visible; `retry.test.mjs` forces `isSupported: false` |

**Honest limit:** the service worker has not been exercised through a real
install → offline → reload cycle in this environment. That is a manual device
check (see the Stage 4 checklist §7.3), not a test result.

---

## 5. Dual-key failover — corrected description

The brief calls this "dual-provider Groq-to-Gemini failover". **That is not what
the code does**, and the documentation must not claim it:

- `app/config.py` supports a **second key** (`KATHA_VISION_API_KEY_FALLBACK`) for
  the same OpenAI-compatible endpoint configured by `KATHA_VISION_BASE_URL`
  (Groq by default in `.env.example`, OpenAI possible).
- A `401/403/429` on the primary rotates to the fallback
  (`app/extraction.py::_read_with_key`); a lone key gets one quiet retry on 429.
- There is **no Gemini adapter** and no cross-provider translation of the
  response shape. Pointing `KATHA_VISION_BASE_URL` at a Gemini
  OpenAI-compatible endpoint would be untested configuration, not a feature.
- `/health` exposes only telemetry: `vision_keys` (count), `vision_fallback`
  (bool), `vision_model`, `vision_base_url` host. Never a key.

Evidence: `tests/test_failover.py` (16 checks) covers rotation, the
no-fallback retry policy, provider 5xx abandonment, malformed envelopes, and
secret hygiene. Observed live telemetry in this environment:

```json
{"vision_model": null, "vision_base_url": null, "vision_keys": 0, "vision_fallback": false}
```

`scripts/check_vision.py` exits `1` with `RESULT: FAIL — manual_required`, which
is the correct, honest state when no key exists.

---

## 6. Reproduce this audit

```bash
# Backend (348)
./.venv/bin/pytest -o addopts="" -q

# Frontend (119) — install once from the committed lockfile
cd tests/js && npm ci
for s in state retry exif-scrub audio-pack audiopack presets recall groundtruth reminders; do
  node "$s.test.mjs"
done

# Translation inventory
./.venv/bin/python -c "from app import i18n; [print(l, i18n.coverage(l)) for l in ('en','ml','hi')]"

# Vision status (expected to fail without a key)
./.venv/bin/python scripts/check_vision.py

# Clean archive (no secrets, no dependencies)
./scripts/make_submission_archive.sh
```

---

## 7. Browser evidence (and a correction to the brief)

The Pass 34 brief states that a headless sandbox cannot render Chromium
screenshots. **In this environment that is not true**: Pass 33 used the cloud
browser to render the real app and measure layout. Recorded results:

| Viewport | `scrollWidth / clientWidth` | Horizontal overflow | Notes |
|---|---|---|---|
| 320 px | **305 / 305** | none | recall banner, caveat, evidence card, recapture card all render; smallest tap target 58 px |
| 360 px | **345 / 345** | none | Hindi evidence card and provenance line render without overflow |

The screenshots (`artifacts/viewport-320-batch.png`,
`artifacts/viewport-320-recapture.png`, `artifacts/viewport-360-hindi.png`) are
**git-ignored build artifacts**, so they are not in the archive. They can be
regenerated with the procedure in `docs/NEURAVIZ_STAGE4_CHECKLIST.md` §8, and a
human should still confirm the spacing on a physical phone.

### 7.1 Pass 36 captures (Stage 4 evidence pack)

Re-measured on 25 November 2026 with the same cloud Chromium, at the viewport
widths the Stage 4 runbook asks for. The Pass 33 figure of `305/305` was a
classic scrollbar narrowing the viewport; this browser uses overlay scrollbars,
so the numbers are 320/320 and 360/360. **In both cases
`scrollWidth === clientWidth`: no horizontal overflow.**

| Capture | Viewport | `scrollWidth / clientWidth` | What it shows |
|---|---|---|---|
| `evidence/01-evidence-card-320.png` | 320 px | **320 / 320** | verdict → identification evidence (name / strength / active ingredient) → provenance `Kerala ground-truth catalogue · verified 2026-11-25` → disclaimer → RAM-only line |
| `evidence/01-evidence-card-360.png` | 360 px | **360 / 360** | the same card at 360 px |
| `evidence/02-recapture-simulated.png` | 320 px | 320 / 320 | medium confidence → amber retake card, verdict held at *Could not verify*, all three evidence fields *Unverified* |
| `evidence/02-low-rejected-simulated.png` | 320 px | 320 / 320 | low confidence → rejection wording **and** the manual-entry card (batch / expiry / age fields) |
| `evidence/03-recall-banner-320.png` | 320 px | 320 / 320 | recall + expiry banner **above** the verdict, pharmacovigilance caveat below it (English) |
| `evidence/03-recall-banner-ml.png` | 320 px | 320 / 320 | the same banner and caveat in Malayalam |
| `evidence/03-recall-banner-hi.png` | 320 px | 320 / 320 | the same banner and caveat in Hindi |
| `evidence/04-voice-reminder-ml.png` | 320 px | 320 / 320 | LISTEN control, the **real** no-Malayalam-voice fallback notice, full read-aloud script, active `1-0-1` reminder banner |
| `evidence/04-voice-reminder-hi.png` | 320 px | 320 / 320 | the same controls and a live Hindi countdown |

API proofs saved beside them: `evidence/01-evidence-card.json`
(`verdict: safe`, `evidence[0] = (matched, matched, verified, ground_truth,
2026-11-25)`) and `evidence/03-recall-banner.json` (`verdict: critical`,
`recall_warning: true`, `expiry_warning: true`, `batch_disclaimer` present in
`en`, `ml`, `hi`).

**Labelling.** Captures (b) carry a visible banner: *"SIMULATED CONFIDENCE
RESPONSE — injected test fixture, no live vision key."* The route was fulfilled
in the browser from a **real** API response whose confidence fields were
rewritten to `medium` / `low`; the rendering path is the production client code,
the confidence value is not. Captures (a), (c) and (d) are deterministic presets
or live API responses and are not simulated.

**Two honest UI findings recorded during the capture:**

1. The **persistent control labels stay bilingual Malayalam + English**
   (`കേൾക്കുക / LISTEN`, `നിർത്തുക / STOP`, `ഓർമ്മിപ്പിക്കുക / SET`,
   `ഓർമ്മപ്പെടുത്തൽ നിർത്തുക / CANCEL`) and do **not** follow the language
   selector, while every dynamic string does. It is legible in all three
   modes, but a Hindi-only reader sees Malayalam on the buttons.
2. The **batch caveat renders in the selected language only** (the API returns
   all three). A judge switching language sees one language at a time, so the
   pack proves the tri-lingual copy by capturing all three.

Both are cosmetic rather than safety defects, and both are outside the Stage 4
freeze: fixing them means editing `static/index.html`, which this pass is not
allowed to touch. They are listed here rather than quietly cropped out.

---

## 8. Residual risks and unverified claims

| Risk | Status | Mitigation in place |
|---|---|---|
| Vision model misreads a foil | High without a key; unmeasured live | confidence gate, refuse/retake, evidence card shows what was read |
| Curated catalogue misses a brand | Medium | manual entry; never invents a drug |
| Recall list incomplete | High | wording says "pilot recall list"; pharmacovigilance caveat |
| Malayalam/Hindi clinical wording | Unreviewed by a clinician | flagged here; native-speaker review required before public use |
| Service worker offline cycle | Untested end-to-end | manual device check listed |
| Audio on real devices | Untested audibly | selection logic tested; visible text fallback |
| CI on GitHub | Never run | workflow runs locally; push not authorised |
| Static control labels do not follow the language selector | Cosmetic; see §7.1 | All dynamic copy is localised; markup labels are bilingual ml+en. Fix queued after the Stage 4 freeze (`static/index.html`). |
| Batch caveat shows one language at a time | Cosmetic; see §7.1 | API carries all three (`batch_disclaimer.en/ml/hi`); UI renders the active one. Captured in all three. |
| Vision key would send a scrubbed image to a third party | Disclosed, not active | No key is configured here, so there is zero egress. Enabling it needs a transfer/consent notice first — §10.1. |
| No HSTS header, rate limiter off by default | Deployment gap | TLS is terminated by the hosting proxy; the limiter is opt-in (`KATHA_RATE_LIMIT_PER_MIN`), intended for the edge — §9.3. |
| Prompt injection via label text | Addressed | charset validation, phrase blocklist, no tool calls, fixed compiler-like rules (`tests/test_api.py`) |

**Bottom line:** the deterministic safety paths are test-backed and reproducible;
the AI-reading path, the licensed-data claim, and the human translation review
are not. Nothing in this report should be read as clinical validation.

---

## 9. Security controls — code-verified

Each row names the file that enforces the control, so a reviewer can check the
claim instead of trusting it. Numbers are line references at `5aeb05f`.

| # | Control | Implementation | How it was verified |
|---|---|---|---|
| 9.1 | **No image ever reaches disk** | `app/extraction.py:526` — `Image.open(io.BytesIO(image_bytes))`. The upload is read into `bytes` in `app/main.py::_read_upload` and released with the request. | `grep -rn "tempfile\|\.save(\|open(.*['\"]wb" app/` returns only docstring sentences, never a call site. |
| 9.2 | **Upload type and size gate** | `app/main.py:360-380`: `Content-Type` allowlist (JPEG/PNG/WebP) → magic-byte signature check against `ALLOWED_IMAGE_TYPES` → read `MAX_IMAGE_BYTES + 1` and reject if longer (6 MiB). | `tests/test_api.py` upload validation cases; live `POST` with a text/plain body returns `415`. |
| 9.3 | **EXIF/GPS stripped on the phone** | `static/js/capture.js`: every frame is drawn to `<canvas>` and re-encoded with `canvas.toBlob()`; a canvas has nowhere to store EXIF/XMP/IPTC. The original `File`/`Blob` is dropped and object URLs are revoked; `createImageBitmap(..., {imageOrientation:"from-image"})` bakes orientation into pixels. Long edge clamped to 1600 px, quality 0.85. | `tests/js/exif-scrub.test.mjs` (15 checks). |
| 9.4 | **Strict request contracts** | `app/schemas.py:145,162` — `ConfigDict(extra="forbid")`; medicine names restricted to Latin + Malayalam + Devanagari + digits + a small punctuation set (`_ALLOWED_CHARS`), length-capped; batch/expiry have their own allowlists; a 10-pattern instruction-phrase blocklist (`_INJECTION_PATTERNS`). Unrecognised text is never executed, interpolated into a prompt, or used to build a tool call. | `tests/test_api.py` (25 checks) incl. prompt-injection blocks; extra keys rejected with `422`. |
| 9.5 | **No sessions, cookies or identifiers** | `app/main.py:10` — "No cookies, no sessions, no per-user identifiers, no request-body logging"; no analytics or third-party script in `static/index.html`. | `grep -rn "localStorage\|sessionStorage\|indexedDB" static/js/` → a single **comment** in `reminders.js:11` explaining why none is used. |
| 9.6 | **Security headers** | `app/main.py:80-86`: `Cache-Control: no-store, max-age=0`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(self), microphone=(), geolocation=()`, and a CSP. | `curl -sI localhost:3004/` shows every header; `/health` is also `no-store` and contains **counts only**. |
| 9.7 | **Secret isolation** | Keys live in `.env` (git-ignored) or the host environment; `/health` exposes `vision_keys` (count), `vision_fallback` (bool) and the base-URL **host** — never key material. `scripts/make_submission_archive.sh` refuses to leave a ZIP containing a credential-shaped string or `.env`/`*.key`/`*secret*`. | Archive run: exit `0`, 79 files, secret scan clean, SHA-256 recorded (§12). |
| 9.8 | **Logging discipline** | No request bodies are logged. `app/extraction.py` logs exception **type names** and status transitions; `app/relay.py:16` — "No logging. Payloads are never written to the log; only connection counts." | Source review; the application never calls a body-logging helper. |
| 9.9 | **Rate limiting** | `app/ratelimit.py`: sliding window, `KATHA_RATE_LIMIT_PER_MIN`, **off by default** (`=0`) because the edge is expected to own abuse control. | `tests/test_ratelimit.py` (10 checks). **Not enabled in this preview** — stated rather than implied. |
| 9.10 | **Offline cache safety** | `static/sw.js` cache `kathapulse-v10`: the shell, CSS, scripts, taxonomy and knowledge feed are precached; **POST requests are never cached or replayed**, and no scan result is stored. | `tests/test_nextgen.py` asserts the SW contract; source review of the fetch handler. |
| 9.11 | **Response hygiene** | Every response is `no-store`; the API returns no stack traces (generic 5xx message); OpenAPI is only exposed when `KATHA_DOCS_ENABLED=1`. | `tests/test_api.py`; live `curl`. |
| 9.12 | **Reproducible clean archive** | `scripts/make_submission_archive.sh` archives **tracked files at HEAD** with `git archive`, then rejects forbidden paths and credential shapes. | Run on this commit: clean, 79 files, < 1 MB. |

### 9.3 What is **not** in place (disclosed, not implied)

- **No HSTS header.** TLS is terminated by the hosting proxy (the preview origin
  is HTTPS); HSTS belongs at that edge, not in this app.
- **No CSRF tokens** — there are no cookies or sessions, so there is no ambient
  authority to forge; every state-changing call is a explicit JSON `POST`.
- **No authentication, by design** — there are no accounts and no per-user data.
  A deployment that adds them must add authn/authz and scoping first.
- **Rate limiting disabled by default** (9.9), **no WAF**, **no dependency CVE
  scan** in CI, **no penetration test**, and **CI has not run on GitHub**.
- **The vision provider path is a third-party transfer.** With
  `KATHA_VISION_API_KEY` set, the scrubbed JPEG is sent as base64 to the
  configured OpenAI-compatible endpoint. No key is configured here, so there is
  **zero egress**; enabling it in production requires the notice described in
  §10.1.

---

## 10. Indian legal and regulatory boundaries

This section states what the build does and, more importantly, **what it does not
claim**. Nothing here is a certification, and no lawyer has reviewed it.

### 10.1 Digital Personal Data Protection Act, 2023 (DPDP)

A photographed medicine strip, and a typed medicine name, are personal data; the
combination with an optional age is health-related. The build's posture:

| DPDP principle | What this build does | What is **not** done |
|---|---|---|
| **Purpose limitation** | Processing happens only on an explicit user action (capture, choose photo, or typed names). The always-visible privacy strip states that metadata is removed on the phone and the image is not saved. Nothing is processed in the background, and no scan is reused for another purpose. | No written consent notice, no consent artefact or record, no consent manager, no published grievance officer. |
| **Data minimisation** | Long edge clamped to 1600 px at quality 0.85; 6 MiB hard cap; at most 10 medicines per scan and 5 strips per batch; only the printed name, strength, batch, expiry and optional age are used. | No formal DPIA. |
| **Storage limitation** | Server: RAM only (`io.BytesIO`), released with the request, `no-store` on every response. Client: the dose plan lives in tab memory; `static/js/reminders.js:11` documents why there is **no localStorage**. The service worker never caches a `POST`. | No retention schedule document (there is nothing to retain). |
| **Security safeguards** | §9 in full: allowlists, magic bytes, strict schemas, headers, secret isolation, no body logging. | No ISO 27001 / SOC 2 certification, no independent audit. |
| **Third-party transfer** | **None while no vision key is configured** — `/health` reports `vision_keys: 0`, so no image leaves the server. | If a key is added, the scrubbed image goes to that provider. That transfer has **no notice and no consent step** yet, so it must not be enabled for real patients without one. |
| **Data-principal rights** | Structurally satisfied by not storing anything: there is no record to access, correct or erase. | No published contact channel for rights requests. |
| **Children's data** | Age is optional and only ever triggers a catalogue age-band warning (e.g. paediatric syrup). | No verifiable parental-consent flow; the tool is not directed at children. |

### 10.2 Drugs and Cosmetics Act, 1940 / Rules, 1945 — CDSCO scope

| Boundary | Position taken |
|---|---|
| **Not a drug, not a medical device** | The app makes no diagnostic or therapeutic claim, is not registered with CDSCO, and is not a CDSCO-certified device. The footer says "Screening aid only"; every response carries a screening-aid disclaimer in all three languages. |
| **Not a substitute for a licensed pharmacist or doctor** | Every warning ends by directing the user to a pharmacist or doctor; the app never tells a patient to start, stop or change a dose. |
| **Recall data is not a CDSCO feed** | Four **curated pilot** notices, labelled "recall list", never "government recall". The API attaches the pharmacovigilance caveat: a batch with no warning is not guaranteed safe, genuine, or free from quality defects. |
| **Schedule H / H1 prescription status is not checked** | **Genuine gap.** The app flags duplication and interactions but does not tell the user that a molecule is prescription-only. This must be added before any pharmacy deployment. |
| **Adverse-event reporting (PvPI) is not performed** | The app advises returning a recalled batch to the pharmacy; it does not file a pharmacovigilance report and does not claim to. |
| **Advertising claims** | No efficacy, cure, comparative-accuracy or approval claim. The competitor matrix in `docs/SUBMISSION_OVERVIEW.md` §4 compares **publicly stated** capabilities and says so explicitly. |

### 10.3 Information Technology Act, 2000 (and the SPDI Rules baseline)

| Requirement | Position |
|---|---|
| **Sensitive personal data not stored** | No server-side store of health imagery, no database, no cache of results. The only persistence anywhere is the offline **shell** in the service worker, which holds no patient data. |
| **Secure transport** | The app is served over HTTPS by the hosting proxy (the preview origin is HTTPS); the camera path additionally requires a secure context. The app itself sets no HSTS — see §9.3. |
| **No interception or monitoring** | No analytics, no third-party scripts, no beacons, no request-body logging; `Referrer-Policy: no-referrer` keeps URLs out of outbound requests. |
| **Reasonable security practices** | Input validation and allowlists, strict schemas, security headers, secret isolation, dependency pinning (`requirements.txt`), reproducible clean packaging. |
| **Not claimed** | No ISO 27001 certification, no CERT-In empanelled audit, no incident-response runbook, no formal DPIA. The DPDP Act 2023 is the governing framework; the SPDI Rules are treated as the historical baseline for sensitive personal data. This document asserts the posture against both and certifies neither. |

---

## 11. Knowledge-base integrity audit (256 entries)

`scripts/audit_knowledge_base.py` checks **every** entry, not a sample, and exits
non-zero on the first broken invariant. Result on this build:

```
$ ./.venv/bin/python scripts/audit_knowledge_base.py
  indexed names            : 256
  curated Kerala brands    : 48
  taxonomy molecules       : 48
  catalogue entries        : 96
  unique catalogue brands  : 96
  catalogue verified on    : 2026-11-25
  entries with curator note: 8
  structural failures      : 0
RESULT: PASS          (exit 0)
```

What is asserted for all **256** indexed names:

| Invariant | Result |
|---|---|
| Compact key is stable and non-empty | 256 / 256 |
| Resolves to a product present in `PRODUCTS_BY_BRAND` | 256 / 256 |
| That product has a non-empty brand and dosage form | 256 / 256 |
| At least one active ingredient, each present in `app.taxonomy` | 256 / 256 |
| At least one positive printed pack strength, attached to a listed molecule | 256 / 256 |
| Generic name present in **en, ml, hi** and in the right script (Malayalam / Devanagari blocks) | 256 / 256 |
| Drug class present | 256 / 256 |
| Resolution method is `ground_truth` or `molecule` (never a silent guess) | 256 / 256 |

And for the 96 public catalogue entries (`GET /knowledge.json`): unique brand keys
(96 unique / 96 entries), non-empty molecules, positive strengths, localised
cautions in all three languages, and `CATALOGUE_VERIFIED_ON = 2026-11-25`.

**Provenance honesty:** the reference source is documented at **module level**
(`app/taxonomy.py` — verified Indian molecule + brand aliases; the curated Kerala
shelf list and Indian pack strengths in `app/knowledge_base.py`), with one review
date — it is *not* a per-entry citation, and 8 products additionally carry a
curator note. This is a curated pilot dataset, not a licensed formulary; a
deployment swaps `PRODUCTS` for a licensed feed without changing the matcher.

---

## 12. Stage 4 submission state

| Item | State |
|---|---|
| Live preview | `0.0.0.0:3004` → `GET /` **200**, `/static/js/app.js` **200**, `/sw.js` **200**, `/health` **200** (`no-store`, counts only) |
| Four required captures (a–d) | **Captured** in `evidence/` — see §7.1; simulated responses visibly labelled |
| Physical-phone checks | **Not performed** — audible ml/hi TTS, touch comfort and the installed-PWA offline cycle need a real device (`docs/NEURAVIZ_STAGE4_CHECKLIST.md` §7, `docs/STAGE4_UPLOAD_CHECKLIST.md` §1) |
| Live vision | **Not enabled** — `vision_keys: 0`, `scripts/check_vision.py` → `manual_required`, exit `1` |
| Regression | 348 backend / 119 frontend checks green on this commit (§1, §6) |
| Repository | <https://github.com/saviochackoxavier-tech/kathapulse-ai>, branch `main`; `LICENSE` (MIT) and `CONTRIBUTING.md` present since Pass 37 |
| Clean archive | Built by `scripts/make_submission_archive.sh`; forbidden-path and credential scans clean (§9.7) |
| Pack | `scripts/build_stage4_pack.py` → `artifacts/stage4_submission/` (report, pitch, summary, evidence copies, ZIP, `SHA256SUMS.txt`) |
