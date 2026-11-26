# NeuraViz AI Challenge 2026–27 — Stage 4 (Final Stage) Checklist

**Project:** KathaPulse AI · **Build:** `v1.6.1` (code at `5aeb05f`) · **Docs:** Pass 36
**Prepared:** 25 November 2026
**Challenge stage:** **Stage 4 — Final Stage** (selected finalist)
**Final-stage deadline:** **10 December 2026**

> **Understand Your Medicine. Protect Your Health.**

---

## 1. Verified challenge facts (and what is uncertain)

| Fact | Source |
|---|---|
| Organiser: NeuraViz Technologies Pvt. Ltd. | `neuraviz.com/aichallenge2026` |
| Free to enter, open worldwide, individual participation, no coding required | organiser page + Unstop listing |
| ₹1,50,000 prize pool, eight winners | `neuraviz.com/aichallenge2026` |
| Four stages: register → idea → proof of concept → **final submission** | `neuraviz.com/aichallenge2026/learn/chapter-6` |
| **Stage 4 asks for the working proof of concept, results and lessons learned** | `neuraviz.com/aichallenge2026/learn/chapter-6`, Step 6 |
| Final-stage submission is made from the participant portal | `neuraviz.com/aichallenge2026/login` |

**Uncertainties, stated rather than hidden:**

- The **10 December 2026** date is the one in the finalist instructions. The
  public challenge page still advertises an extended general registration date
  for the earlier stages. **The portal governs.** Re-check the date and the
  permitted upload formats on `neuraviz.com/aichallenge2026/login` on submission
  day; do not rely on this document for either.
- Eligibility (18+, one original idea per participant, individual only) comes
  from the Unstop listing. **Check the official rules on the portal** — this
  document does not replace them.
- The final package is uploaded **manually by the participant** (Step 5). Nothing
  in this repository can submit on their behalf.

Source URLs:
`https://neuraviz.com/aichallenge2026` ·
`https://neuraviz.com/aichallenge2026/learn/chapter-6` ·
`https://neuraviz.com/aichallenge2026/login` ·
`https://unstop.com/competitions/neuraviz-ai-challenge-2026-submit-an-ai-idea-no-coding-needed-neuraviz-technologies-pvt-ltd-1810876`

---

## 2. Final summary of the solution (paste-ready, ~100 words)

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

**Why AI, honestly:** the AI handles the hard perception problem — reading a
creased, glared, low-resolution foil — not the safety decision. Rules over a
fixed catalogue produce the warning, so the same input always produces the same
verdict, and an unclear input produces a refusal instead of a guess. See
`docs/SUBMISSION_OVERVIEW.md` §4 for how this differs from existing scanners.

---

## 3. Final-stage narrative mapped to the official guidance

The organiser's final step asks for the working proof of concept, its results and
what was learned. Use the table verbatim or adapt it.

| Final-stage prompt | KathaPulse answer |
|---|---|
| **Problem** | Overlapping paracetamol brands, look-alike strips (Telma/Telma-H), English-only labels, recalled or expired batches, and sensitive photos uploaded to unknown clouds. |
| **Who is affected** | Elderly patients and their families in Kerala, small pharmacy counters, and anyone self-medicating in Malayalam or Hindi. Low-end Android phones, intermittent connectivity. |
| **The working POC** | FastAPI service + installable PWA; 48 molecules, 48 curated brands, 256 indexed names, 4 pilot recall notices; vision/OCR/manual extraction tiers; deterministic clinical rules; evidence card; confidence gate; batch audit; tri-lingual speech and local dose reminders. |
| **Results (measured, not claimed)** | 348 backend checks and 119 frontend checks green; 44/44 duplicate-salt corpus; 320 px `305/305` and 360 px `345/345` with zero overflow; 81 strings present in all three languages. |
| **Why AI** | Reading a photographed foil across glare, folds and mixed fonts is the part fixed rules cannot do. A vision model reads; deterministic clinical rules decide; confidence gating decides when to refuse. |
| **What is different** | Field-level evidence a judge can audit, a real batch audit with a pharmacovigilance caveat, ml/hi/en parity, zero server-side image storage, reminders in the patient's language. |
| **Risks and mitigations** | Misread label → confidence gate, refuse/retake, manual entry; invented drug → catalogue-only resolution; privacy → RAM-only, no logs; clinical wording → disclaimers, not a diagnosis; incomplete recall data → caveated in the UI. |
| **Lessons learned** | Perception confidence must be a first-class state, not a score; a rule engine is easier to audit than a model answer; the 320 px layout broke only when measured in a real browser; documentation claims must be tied to a named test. |

### Do not claim

- "100% uptime", "zero hallucination", "10/10 security", "FDA/CE approved",
  "clinically validated", "the first/only multilingual scanner".
- That the recall list is a government feed. It is a four-entry pilot list.
- That Groq-to-Gemini failover exists. Two **keys** for one OpenAI-compatible
  endpoint are supported; Gemini is untested configuration
  (`docs/VALIDATION_REPORT.md` §5).
- That the live vision model has been demonstrated here. It has not; see §5.

---

## 4. Stage 4 deliverables (uploaded manually, later)

The final-stage package is **the participant's manual upload**. Keep each file
small, text-searchable where possible, and free of secrets.

| # | Deliverable | File to upload | Status |
|---|---|---|---|
| 1 | Final summary of the solution | `artifacts/stage4_submission/KathaPulse-AI-Stage4-Summary.pdf` | **Built** (§10.1) |
| 2 | Final documents (report, presentation; up to 3 files) | `…-Report.pdf` (overview + validation report + evidence appendix) and `…-Pitch.pdf` (10 slides) | **Built** (§10.1) |
| 3 | Optional demo link | Unlisted video from §9, or the live preview URL | **Manual recording** |
| — | Source archive (supporting, only if the portal accepts extra files) | `artifacts/stage4_submission/kathapulse-ai-<tag>.zip` from §10 | Generated by script |

Presentation outline (one slide each): problem → who is affected → the workflow →
the refusal-first safety engine → evidence card → batch audit → tri-lingual
voice/reminders → measured results → limitations → next steps.

---

## 5. Live vision credential — verified status

Command run on 25 November 2026 from the repository root:

```bash
./.venv/bin/python scripts/check_vision.py
```

Result: **`status: manual_required`**, exit code `1`, `vision_keys: 0`. The
server has no `KATHA_VISION_API_KEY`, so a photographed strip can only fall
through to OCR (if installed) or open the manual-entry panel. This is a
**configuration gap, not a code failure** — the vision tier is covered by 21
stubbed tests (endpoint, auth header, data-URL shape, fence tolerance, brand and
strength mapping, 401/500/nonsense degradation, no-key → no network call).

**Re-verified in Pass 36 (25 November 2026): unchanged** — `status:
manual_required`, `vision_keys: 0`. The four captures therefore use deterministic
presets, and the two confidence-gate captures carry a visible **"simulated
confidence response"** label.

### To enable live OCR before recording

1. Open the Freebuff project → **Settings → Project settings → Secrets**.
2. Add `KATHA_VISION_API_KEY` (and, only if the endpoint is not the default,
   `KATHA_VISION_BASE_URL`, `KATHA_VISION_MODEL`). Never paste a key into chat,
   a tracked file, an `.env.example`, or a screenshot.
3. Restart the preview server (see §6) so the new environment is read.
4. Re-run:

   ```bash
   ./.venv/bin/python scripts/check_vision.py   # expect status: ok, vision_keys: 1
   curl -s localhost:3004/health | python -m json.tool   # counts only, never key material
   ```

5. If it still reports `manual_required`, stop: the demo must use the preset and
   stubbed paths below, **labelled as simulated**.

### Deterministic demo path (no key needed)

The five one-click presets and the manual-entry textarea run entirely through the
clinical engine, batch audit and local knowledge base. They are the honest demo
when no key is configured. A **stubbed** `/verify-medicines` response may be used
to show the confidence gate, but every screenshot or video segment that relies on
it must carry the visible label **"simulated confidence response"**.

---

## 6. Preview stability and recovery

The preview runs the supervised wrapper, which restarts uvicorn within a second
of a crash:

```bash
nohup setsid ./scripts/serve.sh >/tmp/kathapulse-supervisor.log 2>&1 </dev/null &
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3004/   # expect 200
ss -ltnp | grep 3004                                                # expect 0.0.0.0:3004
```

**If the preview stops while the chat is idle**, the checkpoint has usually
removed `.venv` (environment folders are not archived). Recovery:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
nohup setsid ./scripts/serve.sh >/tmp/kathapulse-supervisor.log 2>&1 </dev/null &
```

Then confirm `GET /` → 200, `/static/js/app.js` → 200 and `/sw.js` → 200, and
re-open the Browser panel. A `*.style.dev` 403 without the owner's session is the
preview auth gate, not a dead server. Never use `pkill -f`; kill the recorded
uvicorn PID or let the supervisor restart it.

| Check | Expected |
|---|---|
| `GET /` | 200, `<title>KathaPulse AI</title>` |
| `GET /static/css/styles.css`, four JS assets, `/sw.js` | 200 |
| `GET /health` | 200, `Cache-Control: no-store`, no key material |
| Kill the uvicorn worker | supervisor restarts it; next request 200 |
| Chat idle → server gone | recreate `.venv`, restart as above |

---

## 7. Physical mobile phone verification (manual, required)

Headless Chromium has no `ml-IN`/`hi-IN` voice, cannot show real touch comfort,
and has not run an installed-PWA cycle. These checks need a real Android phone
(Chrome) or iPhone (Safari), on the deployed preview or a LAN address.

### 7.1 Audible Malayalam and Hindi TTS + dose banner

- [ ] Android: **Settings → System → Languages & input → Text-to-speech output**
      → install the **Malayalam** and **Hindi** voices; set speech rate normal.
- [ ] Open the app, choose **മലയാളം**, run **Glycomet GP · ground truth**, tap
      **കേൾക്കുക / Listen**. Confirm audible Malayalam, then **STOP** silences it.
- [ ] Switch to **हिन्दी**, run the same preset, tap **सुनें / Listen**. Confirm the
      voice is Hindi, not Malayalam read with a Hindi accent or English fallback.
- [ ] Schedule `1-0-1`, tap **ഓർമ്മിപ്പിക്കുക / Set**: confirm the green countdown
      banner and the spoken dose announcement at the slot (or temporarily set a
      slot one minute ahead). Confirm the banner is readable in both languages.
- [ ] Install **no** Malayalam voice and repeat once: the app must show its
      explicit fallback notice and readable script, never silence with no text.
- [ ] Record: `evidence/phone-ml-voice.mp4`, `evidence/phone-hi-voice.mp4`,
      `evidence/phone-reminder-banner.jpg`.

### 7.2 Narrow-screen spacing and touch targets

- [ ] In Chrome DevTools device mode (or on the phone itself), check **320 px**
      and **360 px** widths on the recalled-batch result.
- [ ] `document.documentElement.scrollWidth === clientWidth` at both widths
      (Pass 33 measured `305/305` and `345/345`).
- [ ] No sideways scrolling, no clipped Malayalam molecule names, no button
      under ~44 px, and the verdict/banner visible without pinch-zoom.
- [ ] Tap every control one-handed: language selector, LISTEN, demo preset,
      schedule select, Set, Cancel, manual-entry submit.
- [ ] Record: `evidence/phone-320.jpg`, `evidence/phone-360.jpg`.

### 7.3 Service worker (`kathapulse-v10`) offline cycle

- [ ] Load the app once online; DevTools → Application → Service Workers shows
      **activated**, cache `kathapulse-v10` populated.
- [ ] Turn on **airplane mode**, reload: the shell and cached taxonomy/knowledge
      feed render; no browser error page.
- [ ] Attempt a scan offline: a localised, retryable error card appears — never a
      blank screen and never English-only.
- [ ] Turn the network back on, tap Retry: the scan succeeds without a reload.
- [ ] Record: `evidence/phone-offline-shell.jpg`, `evidence/phone-offline-error.jpg`.
- [ ] State honestly: this cycle is **not** covered by the automated suite.

---

## 8. Visual evidence pack — four required screenshots

Capture at **320 px** width unless stated, full page, no personal data, no keys.
Save under `evidence/` (git-ignored) with the exact names below. Use the cloud
browser panel or Chrome DevTools; each shot must show the whole card, not a crop
that hides the caveat.

### Captured in Pass 36 — what exists now

All four required scenes were captured from the live server with the cloud
Chromium on 25 November 2026. Re-measured widths are **320/320** and **360/360**
(`scrollWidth === clientWidth`, no horizontal overflow). The Pass 33 numbers
(305/305) were a classic scrollbar, not overflow.

| File | Scene | Real or simulated |
|---|---|---|
| `evidence/01-evidence-card-320.png` | (a) evidence card, English, 320 px | **real** — deterministic preset, live API |
| `evidence/01-evidence-card-360.png` | (a) same at 360 px | **real** |
| `evidence/01-evidence-card-320-full.png` | (a) whole page at 320 px, for context | **real** |
| `evidence/02-recapture-simulated.png` | (b) medium → amber retake card, fields *Unverified* | **simulated** (visibly labelled) |
| `evidence/02-low-rejected-simulated.png` | (b) low → rejection wording **+ manual-entry card** | **simulated** (visibly labelled) |
| `evidence/03-recall-banner-320.png` | (c) recall + expiry banner, caveat in English | **real** — live preset |
| `evidence/03-recall-banner-ml.png` | (c) same, Malayalam | **real** |
| `evidence/03-recall-banner-hi.png` | (c) same, Hindi | **real** |
| `evidence/04-voice-reminder-ml.png` | (d) LISTEN, no-voice fallback notice, script, live `1-0-1` countdown | **real** |
| `evidence/04-voice-reminder-hi.png` | (d) same controls, Hindi countdown | **real** |
| `evidence/01-evidence-card.json`, `03-recall-banner.json` | API proofs (`ground_truth` / `2026-11-25`; `recall_warning: true`) | **real** |

Two findings recorded during capture, both disclosed rather than cropped:
control labels (`LISTEN`/`STOP`/`SET`/`CANCEL`) stay bilingual **Malayalam +
English** and do not follow the selector; the batch caveat renders in the
**selected language only** (the API carries all three, hence the three captures).
Fixing either means editing `static/index.html`, which the Stage 4 freeze
forbids.

What a headless browser **cannot** show, and what still needs the phone (§7):
audible `ml-IN`/`hi-IN` playback (the capture honestly shows the fallback notice
instead), real touch comfort, and the installed-PWA offline cycle.

### (a) Successful scan with the Explainable Evidence card

- [ ] Open the app, choose **മലയാളം** (or **English** for legibility), tap
      **Glycomet GP · ground truth**.
- [ ] Confirm the result shows the verdict, **Identification evidence** with
      *Medicine name detected*, *Strength detected*, and *Active ingredient:
      database verified*, plus the provenance line naming the local taxonomy or
      ground-truth database and `2026-11-25`.
- [ ] Capture `evidence/01-evidence-card-320.png`. Also save the JSON:

  ```bash
  curl -s -X POST localhost:3004/verify-medicines \
    -H 'Content-Type: application/json' \
    -d '{"medicines":[{"name":"Glycomet GP"}],"language":"ml"}' \
    | python -m json.tool > evidence/01-evidence-card.json
  ```

- [ ] Repeat at 360 px → `evidence/01-evidence-card-360.png`.

### (b) Blurry / low-confidence scan → explicit rejection or retake

Choose one route and label it:

- **Route A (with a key):** photograph a deliberately blurred or glared foil;
  confirm the amber **Retake a clearer photo** card, verdict held at **Could not
  verify**, evidence fields **Unverified**. Capture `evidence/02-recapture.png`.
- **Route B (no key):** intercept `/verify-medicines` (DevTools → Network →
  Override, or a local stub proxy) and return `recapture_required: true` for
  medium and `low_confidence_rejected: true` for low. The UI path is real; the
  response is simulated, so the image must be annotated **"simulated confidence
  response"**. Capture `evidence/02-recapture-simulated.png` and
  `evidence/02-low-rejected-simulated.png`.
- [ ] Confirm `low` shows the rejection wording **and** the manual-entry card.
- [ ] API proof: `./.venv/bin/pytest -q tests/test_confidence_evidence.py` → 16 passed.

### (c) Recalled or expired batch — warning + tri-lingual disclaimer

- [ ] Tap **Glycomet 500 · batch audit** (`GM2407A`, `09/2026`).
- [ ] Confirm the crimson banner **above** the verdict shows `RECALLED_BATCH`
      and `EXPIRED_STOCK`, and directly below it the pharmacovigilance caveat in
      Malayalam, Hindi and English: *"A batch with no warning is not guaranteed
      to be safe, genuine, or free from quality defects…"*.
- [ ] Capture `evidence/03-recall-banner-320.png`, then switch to **हिन्दी** and
      capture `evidence/03-recall-banner-hi.png`.
- [ ] API proof:

  ```bash
  curl -s -X POST localhost:3004/verify-medicines \
    -H 'Content-Type: application/json' \
    -d '{"medicines":[{"name":"Glycomet 500","batch_no":"GM2407A","expiry":"09/2026"}],"language":"en"}' \
    | tee evidence/03-recall-banner.json | python -m json.tool
  # expect recall_warning: true and batch_disclaimer.en present
  ```

### (d) Malayalam and Hindi speech controls + active dose reminder

- [ ] Choose **മലയാളം**, run a preset, and show the **കേൾക്കുക / Listen** control
      and the always-visible script text.
- [ ] Schedule `1-0-1` and tap **Set**; keep the green countdown banner on screen.
- [ ] Switch to **हिन्दी** so the same controls and banner re-render in Hindi
      from the same in-memory plan.
- [ ] Capture `evidence/04-voice-reminder-ml.png` and
      `evidence/04-voice-reminder-hi.png`.
- [ ] Note in the caption that audible playback is verified only on a real phone
      (§7.1); in this sandbox the visible fallback is what a voiceless browser shows.

---

## 9. Optional Stage 4 voiceless demo walkthrough (manual recording)

Record **60–90 seconds**, no microphone narration, English captions burned in or
in the video description. A silent screen recording is acceptable; speak nothing
rather than inventing results.

1. **0:00–0:10 — Title card:** "KathaPulse AI — a refusal-first medicine-safety
   companion. Working proof of concept, `v1.6.1`."
2. **0:10–0:30 — Evidence (a):** open the app, tap **Glycomet GP · ground truth**,
   pause on the evidence fields, then the verdict.
3. **0:30–0:45 — Rejection (b):** run the blurred/low-confidence route; hold on
   the retake or rejection card and the manual-entry option.
4. **0:45–1:05 — Batch audit (c):** tap **Glycomet 500 · batch audit**, hold on
   the crimson banner and the tri-lingual caveat.
5. **1:05–1:20 — Language and reminders (d):** switch ml → hi, tap Listen (show
   the fallback notice if no voice), set `1-0-1`, show the countdown banner.
6. **1:20–1:30 — Close:** test counts on screen (348 backend / 119 frontend) and
   one honest limitation line: "Live vision model not enabled in this recording;
   all scan results shown are deterministic presets."

Rules: use a clean device with no notifications, hide bookmarks and personal
tabs, never show `.env`, `/health` key material or the browser's password UI. If
any segment uses a stubbed response, put **"simulated confidence response"** on
screen for that segment and say so in the description. Upload unlisted (YouTube
or Drive) and paste the link into the portal. This recording is **optional**; the
four screenshots are the required evidence.

---

## 10. Regression evidence and clean archive

```bash
./.venv/bin/pytest --color=no -o addopts="" -q          # expect 348 passed
cd tests/js && npm ci
for s in state retry exif-scrub audio-pack audiopack presets recall groundtruth reminders; do
  node "$s.test.mjs" || exit 1
done                                                    # expect all exit 0, 119 checks
```

The preset suite needs `./scripts/serve.sh` running on port 3004. Capture the
terminal output as `evidence/07-tests.png`.

```bash
./scripts/make_submission_archive.sh
```

It archives **tracked files at HEAD** and refuses to leave a ZIP that contains
`.env`, `*secret*`/`*.key`, `.venv/`, `__pycache__/`, `node_modules/`, `.git/`,
`artifacts/`, or a real credential shape. `.env.example` placeholders remain and
are not treated as secrets.

### 10.1 Build the submission pack

```bash
./.venv/bin/python scripts/audit_knowledge_base.py     # 256/256, exit 0
./scripts/make_submission_archive.sh                  # clean ZIP + sha256
./.venv/bin/python scripts/build_stage4_pack.py       # HTML/MD + copies + SHA256SUMS
```

The builder writes `artifacts/stage4_submission/`:

| File | Purpose |
|---|---|
| `KathaPulse_AI_Stage4_Technical_Report.pdf` | Final report, 21 pages: overview + validation report + evidence appendix (36 capture slices) |
| `KathaPulse_AI_Stage4_Technical_Report.docx` | The same report as an editable DOCX for the portal (22 tables, 36 pictures) |
| `KathaPulse-AI-Stage4-Pitch.pdf` | 10 landscape slides built from §3 and the captures |
| `KathaPulse-AI-Stage4-Summary.pdf` | The one-page summary (§2), paste-ready |
| `KathaPulse-AI-Stage4-*.md` / `-Pitch.html` | Text sources for editing without a PDF tool |
| `UPLOAD-CHECKLIST.md` | The manual steps (`docs/STAGE4_UPLOAD_CHECKLIST.md`) |
| `evidence/` | Copies of the captures and the two API proofs |
| `kathapulse-ai-*.zip` | The clean source archive |
| `SHA256SUMS.txt` | SHA-256 of every file in the pack |

The HTML is self-contained (images are embedded). The PDFs are built with ReportLab
(A4 portrait for the report and summary, A4 landscape for the pitch) and the report's
DOCX twin with python-docx, so a browser "Print → Save as PDF" is a convenience,
never the shipped file.

### Archive checklist

- [ ] Script exits `0`.
- [ ] ZIP lists the three docs, `scripts/make_submission_archive.sh`, `tests/`,
      `.github/workflows/ci.yml`.
- [ ] No `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `artifacts/`.
- [ ] Secret scan returns nothing; SHA-256 recorded in the submission notes.
- [ ] ZIP < 2 MB (source only).

---

## 11. Package contents

| File | Purpose | Status |
|---|---|---|
| `docs/SUBMISSION_OVERVIEW.md` | Problem, solution, honest competitor matrix, privacy, limitations | Complete |
| `docs/VALIDATION_REPORT.md` | Test-backed clinical, translation, offline audit | Complete |
| `docs/NEURAVIZ_STAGE4_CHECKLIST.md` | This document | Complete |
| `README.md` | Architecture, API, differentiation matrix, legal/security sections, evidence gallery, test commands | Complete |
| `CONTRIBUTING.md`, `LICENSE` | Contribution rules, test gates, MIT + medical-disclaimer boundary | Complete |
| `evidence/` captures | Four required screenshots (+ optional video) | **Captured** — 10 PNGs + 2 JSON proofs (§8) |
| Source archive | Clean, secret-free ZIP | Generated (§10) |

---

## 12. Final pre-submission gate (tick every line)

- [ ] Final-stage deadline and upload format re-checked on the portal on submission day.
- [ ] Summary (§2), report and presentation uploaded (≤ 3 files), no inflated claims.
- [x] Four screenshots (a–d) captured, legible at 320 px, no personal data or keys.
- [x] Any stubbed response visibly labelled "simulated confidence response".
- [ ] Physical phone checks done: audible ml/hi, 320–360 px spacing, offline SW cycle.
- [ ] `./scripts/check_vision.py` run and its status stated honestly in the report.
- [x] 348 backend + 119 frontend checks green on the documented commit.
- [x] ZIP verified clean; SHA-256 recorded.
- [ ] Optional voiceless demo link added, or a plain statement that no video is included.
- [ ] Repository URL and commit hash included.
- [ ] Native-speaker/clinical review of ml/hi warning copy requested (not yet done).

**Known blockers at the time of writing:** no `KATHA_VISION_API_KEY` in this
environment (`manual_required`); no real-device audio or offline cycle captured;
clinical translation review outstanding. Each is disclosed rather than hidden,
and none prevents submitting the working POC with deterministic preset evidence.
