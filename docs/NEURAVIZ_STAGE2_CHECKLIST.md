# NeuraViz AI Challenge 2026–27 — Stage 2 Alignment & Evidence Checklist

**Project:** KathaPulse AI · **Build:** `v1.6.1` @ `5aeb05f`
**Prepared:** 25 November 2026
**Challenge stage:** Stage 2 — Idea Submission
**Deadline recorded by the organiser:** **31 January 2027, 11:59 PM IST** (extended)

> **Understand Your Medicine. Protect Your Health.**

---

## 1. Verified challenge facts (and what is uncertain)

Checked on 25 November 2026 against the organiser's own pages:

| Fact | Source |
|---|---|
| Organiser: NeuraViz Technologies Pvt. Ltd. | `neuraviz.com/aichallenge2026` |
| Free to enter, open worldwide, individual participation, no coding required | organiser page + Unstop listing |
| ₹1,50,000 prize pool, eight winners | `neuraviz.com/aichallenge2026` |
| **Registration and idea submission close 31 January 2027** ("Extended deadline", 11:59 PM IST) | `neuraviz.com/aichallenge2026`, Unstop |
| Four stages: registration → **Stage 2 idea submission** → Stage 3 proof of concept → final demo | `neuraviz.com/aichallenge2026`, learning chapter 6 |
| Stage 3 focuses on data, solution design, success measures and risks; Stage 2 on a clear problem, the people affected, and why AI helps | `neuraviz.com/aichallenge2026/learn/chapter-6` |

**Uncertainties, stated rather than hidden:**

- Some third-party aggregators (e.g. Internshala) still show **10 December
  2026**. Treat 31 January 2027 as the organiser's current date, but confirm on
  the NeuraViz portal before submitting.
- Eligibility (18+, one original idea per participant, individual only) comes
  from the Unstop listing. **Check the official rules on the portal** — this
  document does not replace them.
- This repository is a working proof of concept, while Stage 2 asks only for an
  idea. That is an advantage for the narrative, not a requirement: the evidence
  pack below is optional supporting material.

Source URLs:
`https://neuraviz.com/aichallenge2026` ·
`https://neuraviz.com/aichallenge2026/learn/chapter-6` ·
`https://unstop.com/competitions/neuraviz-ai-challenge-2026-submit-an-ai-idea-no-coding-needed-neuraviz-technologies-pvt-ltd-1810876`

---

## 2. The 100-word Stage 2 summary (paste-ready)

> KathaPulse AI helps Indian families and small pharmacies understand a medicine
> before they take it. A patient photographs the strip in Malayalam, Hindi or
> English; the app reads the printed name and strength, verifies the molecules
> against a curated Kerala catalogue, and returns a deterministic safety verdict:
> duplicate salt, paracetamol overdose, known interactions, look-alike brands, and
> whether the batch is under a recall or past expiry. Every result shows what was
> actually read, and refuses or asks for a clearer photo rather than guessing.
> Images are processed in memory only and never stored. Dose reminders are spoken
> in the patient's language and kept on their own phone.

**One-line pitch:** *A refusal-first, tri-lingual medicine-safety companion that
explains what is in the box and protects the patient from the ways it can hurt
them.*

**Why AI, honestly:** the AI is used for the hard perception problem — reading a
creased, glared, low-resolution foil — not for the safety decision. Rules over a
fixed catalogue produce the warning, so the same input always produces the same
verdict, and an unclear input produces a refusal instead of a guess. See
`docs/SUBMISSION_OVERVIEW.md` §4 for how this differs from existing scanners.

---

## 3. Stage 2 narrative mapped to the official guidance

The organiser's learning material asks Stage 2 submissions to cover a clear
problem, the people affected, and why AI helps. Fill these fields from the
material below; they are written to be used verbatim or adapted.

| Stage 2 prompt | KathaPulse answer |
|---|---|
| **Problem** | Overlapping paracetamol brands, look-alike strips (Telma/Telma-H), English-only labels, recalled or expired batches, and sensitive photos uploaded to unknown clouds. |
| **Who is affected** | Elderly patients and their families in Kerala, small pharmacy counters, and anyone self-medicating in Malayalam or Hindi. Low-end Android phones, intermittent connectivity. |
| **Why AI** | Reading a photographed foil across glare, folds, and mixed fonts is the part fixed rules cannot do. A vision model reads; deterministic clinical rules decide; confidence gating decides when to refuse. |
| **What is different** | Explainable field-level evidence, batch audit with an explicit pharmacovigilance caveat, ml/hi/en parity, zero server-side image storage, reminders in the patient's language. |
| **Risks and mitigations** | Misread label → confidence gate, refuse/retake, manual entry; hallucinated drug → catalogue-only resolution, never generated; privacy → RAM-only, no logs; clinical wording → disclaimers, not a diagnosis; incomplete recall data → caveated in the UI. |
| **Success measures (proposed for Stage 3)** | Duplicate-salt corpus accuracy (currently 44/44), zero invented molecules on adversarial labels, task completion on a 320 px phone by a first-time elderly user, and clinician sign-off of ml/hi warning copy. |

### Do not claim

- "100% uptime", "zero hallucination", "10/10 security", "FDA/CE approved",
  "clinically validated", "the first/only multilingual scanner".
- That the recall list is a government feed. It is a four-entry pilot list.
- That Groq-to-Gemini failover exists. Two **keys** for one OpenAI-compatible
  endpoint are supported; Gemini is untested configuration
  (`docs/VALIDATION_REPORT.md` §5).

---

## 4. Judge evidence checklist

Tick each item only when the artefact exists. Commands assume the repository root
and the server running on port 3004 (`./scripts/serve.sh`).

### 4.1 Successful scan with Explainable Medicine Identification

- [ ] Start the server: `./scripts/serve.sh` (or reuse the running one).
- [ ] Open the app, choose **മലയാളം**, tap the **Glycomet GP · ground truth** demo.
- [ ] Confirm the result shows:
  - [ ] verdict card,
  - [ ] **Identification evidence** with `മരുന്നിന്റെ പേര് / അളവ് / ഘടകം` all *matched/verified*,
  - [ ] provenance line naming the local taxonomy/ground-truth database and `2026-11-25`,
  - [ ] warning list (or the "no dangerous overlap" finding).
- [ ] Capture: full-page screenshot at 320 px and 360 px, plus the JSON:
      `curl -s -X POST localhost:3004/verify-medicines -H 'Content-Type: application/json' -d '{"medicines":[{"name":"Glycomet GP"}],"language":"ml"}'`
- [ ] Save as `evidence/01-evidence-card-320.png`, `evidence/01-evidence-card.json`.

Pass 33 reference captures (git-ignored, regenerate as above):
`artifacts/viewport-320-batch.png`, `artifacts/viewport-360-hindi.png`.

### 4.2 Blurry / low-confidence scan → rejection or retake

The live server cannot produce a medium-confidence reply without a vision key, so
choose one of these honest routes:

- [ ] **Route A (with a key):** configure `KATHA_VISION_API_KEY`, photograph a
      blurred foil, confirm the amber **Retake a clearer photo** card, the verdict
      held at **Could not verify**, and *Unverified* evidence fields.
- [ ] **Route B (no key):** use the stubbed response path documented in Pass 33 —
      intercept `/verify-medicines` and set `recapture_required: true` (medium) or
      `low_confidence_rejected: true` (low). The UI path is real; the response is
      simulated, so label the screenshot **"simulated confidence response"**.
- [ ] Confirm `low` shows the rejection wording **and** the manual-entry card.
- [ ] Capture: `evidence/02-recapture.png`, `evidence/02-low-rejected.png`.
- [ ] API proof: `./.venv/bin/pytest -q tests/test_confidence_evidence.py`
      → 16 passed.

Reference capture: `artifacts/viewport-320-recapture.png`.

### 4.3 Dual-key failover telemetry

- [ ] Run `./.venv/bin/pytest -q tests/test_failover.py` → **16 passed**.
- [ ] Show `/health`: `curl -s localhost:3004/health | python -m json.tool`.
- [ ] Explain accurately: **primary + fallback key** for one OpenAI-compatible
      endpoint, rotation on 401/403/429, one quiet retry for a lone key. No
      Gemini-specific adapter.
- [ ] If two keys are configured, show `vision_keys: 2` and `vision_fallback: true`
      **without showing the keys**. Otherwise show `vision_keys: 0` and state that
      the path is tested, not live.
- [ ] Capture: `evidence/03-failover-tests.png`, `evidence/03-health.json`.

### 4.4 Offline PWA mode

- [ ] Load the app once online so the service worker installs
      (`kathapulse-v10`).
- [ ] DevTools → Application → Service Workers: confirm **activated**, cache
      `kathapulse-v10` populated.
- [ ] Switch Network → **Offline**, reload: the shell and last-known
      taxonomy/knowledge feed render.
- [ ] Attempt a scan offline: a localised, retryable error appears — never a blank
      screen.
- [ ] Capture: `evidence/04-offline-shell.png`, `evidence/04-offline-error.png`.
- [ ] Note honestly: this cycle is **not** covered by the automated suite; it is a
      manual check.

### 4.5 Batch recall + pharmacovigilance disclaimer

- [ ] Tap **Glycomet 500 · batch audit**.
- [ ] Confirm the crimson banner shows `RECALLED_BATCH` and `EXPIRED_STOCK`, and
      below them the tri-lingual caveat: *"A batch with no warning is not
      guaranteed to be safe, genuine, or free from quality defects…"*.
- [ ] Capture: `evidence/05-batch-caveat.png`.
- [ ] API proof: `curl -s -X POST localhost:3004/verify-medicines -H 'Content-Type: application/json' -d '{"medicines":[{"name":"Glycomet 500","batch_no":"GM2407A","expiry":"09/2026"}],"language":"en"}' | python -m json.tool`
      → `recall_warning: true`, `batch_disclaimer.en` present.

### 4.6 Malayalam voice readout and dose reminder

- [ ] On a real Android device with a Malayalam TTS voice installed
      (Settings → Text-to-speech → install Malayalam), run a scan in മലയാളം and
      tap **കേൾക്കുക / Listen**.
- [ ] Confirm audible Malayalam; then STOP works.
- [ ] With a voice missing, confirm the explicit fallback notice and readable
      script (this is the state headless Chromium shows).
- [ ] Choose a schedule (`1-0-1`), tap **ഓർമ്മിപ്പിക്കുക / Set**, confirm the
      countdown banner and the "page must stay open" copy.
- [ ] Capture video: `evidence/06-malayalam-voice.mp4`,
      `evidence/06-reminder-banner.png`.

**Why not already captured:** headless Chromium has no ml-IN/hi-IN voice, so the
audible readout cannot be recorded in this sandbox. The announcement selection
and English fallback are unit-tested (`tests/js/reminders.test.mjs`, 21 checks).

### 4.7 Regression evidence

- [ ] `./.venv/bin/pytest -o addopts="" -q` → **348 passed**.
- [ ] `cd tests/js && npm ci && for s in state retry exif-scrub audio-pack audiopack presets recall groundtruth reminders; do node "$s.test.mjs"; done` → **119 checks passed**.
- [ ] Capture the terminal output: `evidence/07-tests.png`.

---

## 5. Regenerating the browser measurements

The Pass 33 measurements used the cloud browser (320 px: `305/305`; 360 px:
`345/345`, zero overflow). To repeat them:

1. Open the preview in the chat's browser panel.
2. Set the viewport to 320×640, clear the service worker and caches, reload.
3. Click **Glycomet 500 · batch audit**.
4. In the console:
   ```js
   ({ client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth })
   ```
   Both numbers must match.
5. Repeat at 360×740, and with the language set to **हिन्दी**.
6. Capture full-page screenshots.

A human should still check spacing on a physical phone; automated measurement
proves absence of overflow, not comfort.

---

## 6. Clean, secret-free source archive

The script ships in the repository:

```bash
./scripts/make_submission_archive.sh
```

It creates `artifacts/kathapulse-ai-<tag>.zip` from **tracked files at HEAD**
(`git archive`), then refuses to leave the archive in place if it contains:

- `.env` (the real environment file) or any file matching `*secret*`/`*.key`,
- `.venv/`, `__pycache__/`, `node_modules/`, `.git/`,
- any string shaped like a real credential: `gsk_` or `sk-` followed by 20+
  characters, a Google `AIza` key, or a vision/relay key assigned a long value.
  Documentation placeholders such as `gsk_...`, `=stub` and `<set this in
  Secrets>` are not treated as secrets and are expected to remain.

It prints the archive path, file count and SHA-256. `.env.example` (empty
placeholders) is intentionally included; the real `.env` is git-ignored and never
tracked.

Manual equivalent, if the script is unavailable:

```bash
git archive --format=zip --prefix=kathapulse-ai/ -o kathapulse-ai.zip HEAD
unzip -l kathapulse-ai.zip | grep -E '\.env$|\.venv/|__pycache__/' && echo "FAIL"
grep -rIEl 'sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}' . --exclude-dir=.git --exclude-dir=.venv
```

### Archive checklist

- [ ] Script exits `0`.
- [ ] `unzip -l` lists `app/audio_reminders.py`, `static/js/reminders.js`,
      `docs/`, `tests/`, `.github/workflows/ci.yml`.
- [ ] No `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `artifacts/`.
- [ ] Secret scan returns no file names.
- [ ] SHA-256 recorded in the submission notes.
- [ ] ZIP size reasonable (< 2 MB; source only).

---

## 7. Submission package contents

| File | Purpose | Status |
|---|---|---|
| `docs/SUBMISSION_OVERVIEW.md` | Problem, solution, honest competitor matrix, privacy, limitations | Complete |
| `docs/VALIDATION_REPORT.md` | Test-backed clinical, translation, offline audit | Complete |
| `docs/NEURAVIZ_STAGE2_CHECKLIST.md` | This document | Complete |
| `README.md` | Architecture, API, test commands, pass history | Complete |
| `AUDIT_REPORT.md` | Independent audit notes and scorecards | Complete |
| Source archive | Clean, secret-free ZIP | Generated by script |
| `evidence/` captures | Screenshots, JSON, video, terminal output | **Pending manual capture** (§4) |

---

## 8. Final pre-submission gate (tick every line)

- [ ] Official rules and deadline re-checked on `neuraviz.com` on submission day.
- [ ] Summary and narrative pasted; no inflated claims from §3's "do not claim".
- [ ] 348 backend + 119 frontend checks green on the submitted commit.
- [ ] `./scripts/check_vision.py` output included, stating the key status honestly.
- [ ] Archive script run; ZIP verified clean; SHA-256 recorded.
- [ ] At least one real-device Malayalam voice recording captured (§4.6).
- [ ] Screenshots labelled simulated where the response was stubbed (§4.2 Route B).
- [ ] Repository URL and commit hash included.
- [ ] Native-speaker/clinical review of ml/hi warning copy requested (not yet done).

**Known blockers at the time of writing:** no `KATHA_VISION_API_KEY` in this
environment, no real-device audio capture, and clinical translation review
outstanding. None of these prevents a Stage 2 *idea* submission; all of them must
be disclosed if the working demo is shown.
