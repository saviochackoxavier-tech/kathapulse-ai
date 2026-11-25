# KathaPulse AI — Clinical, Translation & Offline Validation Report

**Build audited:** `v1.6.1` @ `5aeb05f`
**Date:** 25 November 2026
**Environment:** Python 3.12, `.venv` from `requirements.txt`; Node 26 + jsdom 24;
server at `0.0.0.0:3004`; vision key **not configured** (`vision_keys: 0`).

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
| Prompt injection via label text | Addressed | charset validation, phrase blocklist, no tool calls, fixed compiler-like rules (`tests/test_api.py`) |

**Bottom line:** the deterministic safety paths are test-backed and reproducible;
the AI-reading path, the licensed-data claim, and the human translation review
are not. Nothing in this report should be read as clinical validation.
