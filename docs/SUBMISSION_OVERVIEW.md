# KathaPulse AI — Submission Overview

**Build:** `v1.6.1` — application code at `5aeb05f`, unchanged since
**docs/tooling:** Pass 37 (26 November 2026) · **branch:** `main`
**Document date:** 25 November 2026
**Challenge:** NeuraViz AI Challenge 2026–27, **Stage 4 — Final Stage**
**Final-stage deadline:** **10 December 2026** (confirm on the participant portal)

> **Understand Your Medicine. Protect Your Health.**

---

## 1. What KathaPulse AI is

KathaPulse AI is a mobile-web medicine-safety companion for Indian households and
small pharmacies. A patient photographs a medicine strip, or types the printed
names; the app returns a **deterministic, tri-lingual verdict** about what is
actually in the box, what must not be taken together, whether the batch has been
flagged, and when the next dose is due.

It is one integrated workflow, not a pill-identifier:

```
photograph strip → read the printed text → resolve molecules against a curated
catalogue → run clinical rules → audit the batch/expiry → explain the evidence
→ speak the warning in ml/hi/en → schedule the dose locally
```

Three things make it different in practice:

1. **The safety decision is not made by a language model.** The LLM only reads
   the foil. Every warning comes from explicit rules over a fixed taxonomy
   (`app/clinical.py`, `app/recall.py`, `app/audio_reminders.py`). When the text
   is unclear, the app refuses or asks for a retake rather than guessing.
2. **The result is explainable.** Each scan returns field-level evidence —
   medicine name, strength, active ingredient — with the database that verified
   it and the date that database was last reviewed. A strength that came from a
   molecule default is shown as *Unverified*, not as something the camera read.
3. **Nothing is stored.** The image is processed in RAM only (`io.BytesIO`),
   never written to disk, never kept after the response. The dose plan lives in
   the browser tab and dies with it.

### Core message, used consistently

*"Understand Your Medicine. Protect Your Health."* — the product explains what
the medicine is (identification evidence), then protects the patient from the
specific ways a box can hurt them (duplicate salt, paracetamol ceiling, known
interactions, look-alike brands, recalled/expired batches).

---

## 2. The problem it addresses

- **Self-medication with overlapping salts.** Two brands of the same molecule, or
  a combination brand plus a plain tablet, are a common and invisible overdose.
  Dolo 650 taken three times a day across two strips already reaches 5,850 mg of
  paracetamol against a 4,000 mg adult ceiling.
- **Look-alike shelf neighbours.** Telma vs Telma-H, Pan 40 vs Pan-D, Amaryl vs
  Amlopres: one letter changes the molecule.
- **Language.** The people most at risk read Malayalam or Hindi, while the package
  insert and most scanning apps are English-first.
- **Batch quality.** A box can be genuine, in date, and still be under a CDSCO
  quality alert.
- **Privacy.** Photographing medicine in a small town is sensitive; uploading it
  to an unknown cloud service is not an acceptable default.

KathaPulse addresses all five in one flow, on a low-end Android phone, with
44–58 px touch targets and a high-contrast dark interface.

---

## 3. What the build actually contains (verified file tree)

Only files that exist in this build are listed. Counts are from this build; the
application code is unchanged since `5aeb05f` — Pass 34–36 added documentation,
audit scripts and the submission pack only.

| Area | Files | Reality |
|---|---|---|
| API & contracts | `app/main.py` (513 lines), `app/schemas.py`, `app/config.py` | 6 endpoints + 1 WebSocket relay; strict Pydantic contracts; no OpenAPI exposed unless `KATHA_DOCS_ENABLED=1` |
| Extraction | `app/extraction.py` | Three tiers: vision LLM (optional key) → local Tesseract OCR (optional binary) → manual entry. Per-strip confidence gate. |
| Clinical rules | `app/clinical.py`, `app/taxonomy.py` | Duplicate-salt, paracetamol ceiling, documented pairs, same-class duplication, LASA, age bands. 48 molecules. |
| Ground truth | `app/knowledge_base.py` | 48 curated Kerala brands, 256 indexed names, provenance date `2026-11-25` |
| Batch audit | `app/recall.py` | 4 **curated pilot** recall notices, expiry parsing, cold-chain flag |
| Reminders | `app/audio_reminders.py` | Schedule parser (`1-0-1`, BD, TDS, every 8 h), refusals at the paracetamol ceiling; server stores nothing |
| PWA shell | `static/index.html`, `static/css/styles.css` (737 lines), `static/sw.js` (cache `kathapulse-v10`) | Offline shell, installable, no scan result cached |
| Client logic | `static/js/app.js`, `state.js`, `capture.js`, `speech.js`, `audio-pack.js`, `reminders.js` | State machine, EXIF scrub, tri-lingual speech, local audio pack, dose clock |
| Tests | 14 backend files (348 checks), 9 Node suites (119 checks) | See `docs/VALIDATION_REPORT.md` |
| CI | `.github/workflows/ci.yml` | Backend + frontend jobs; locally executed, not yet run on GitHub |
| Audit & packaging | `scripts/audit_knowledge_base.py`, `scripts/build_stage4_pack.py`, `scripts/make_submission_archive.sh` | 256-entry structural audit (`exit 0`), pack builder, secret-free source ZIP |

---

## 4. Honest positioning against six products

This is a comparison of **publicly stated** capabilities, not a benchmark. Every
row is based on the product's own website or store listing as read on
25 November 2026; "not stated publicly" means exactly that, not that the feature
is absent. No competitor was tested, and no claim is made that KathaPulse
invents AI medicine scanning — it does not.

| | **KathaPulse AI** (this project) | **Pill IQ** (`pilliq.in`, also `pilliq.io`) | **PharmaScan AI** (`com.pharmascan.app`) | **MedLingual** (`medlingual.app`) | **MedScan** (`org.evergreenlabs.medscan`) | **MedicineWatch India** (`medicinewatch.vercel.app`) | **DoseBell** |
|---|---|---|---|---|---|---|---|
| **Public description** | Integrated strip-safety workflow for Indian households/pharmacies | AI packaging scanner: uses, dosage, side effects, storage; 1,200+ medicines. (The separate `pilliq.io` is clinician-facing FDA-label RAG.) | AI medicine scanner and pill identifier; prescriptions; interactions per store listing | OTC medication label scanner with translated explanations; OpenFDA + Google Translate | Label scanner that reads the medication's purpose aloud, senior-friendly; Canadian DIN focus | Checks whether a medicine batch is flagged in India's official CDSCO quality alerts | **No public product under this name was found.** Closest verified name is *MedBell* (family reminders/caregiver alerts) |
| **Interaction / duplicate-salt checking** | **Yes, deterministic rules**: duplicate salt, paracetamol ceiling, documented pairs, same-class duplication, LASA | Interaction reports mentioned as a Premium feature; methodology not public | Interactions mentioned in the store listing | Not stated publicly | Not stated publicly | No — batch alerts, explicitly "not a substitute for a doctor or pharmacist" | Not verifiable |
| **Recall / batch / expiry audit** | **Yes** — 4 curated pilot notices, expiry parse, cold-chain flag, with a caveat that an unflagged batch is not a safe batch | Not stated publicly | Not stated publicly | Not stated publicly | Not stated publicly | **Yes — the core feature**, sourced from CDSCO | Not verifiable |
| **Languages** | **ml / hi / en**, all 81 UI and safety strings present in all three | English interface (site and store listing); Malayalam not stated | Not stated in the listing excerpt | 6 languages: en, es, zh, tl, vi, hi (App Store listing); Malayalam not listed | Many, **including Malayalam**, per listing | Not stated publicly | Not verifiable |
| **Explainability of a scan** | **Yes** — per-field evidence + database + review date; confidence gate refuses/retakes | Plain-language summary; sourcing not public | Plain-language info | Translation of OpenFDA content | Reads out the label's purpose | Links to the official alert | Not verifiable |
| **Privacy posture** | Image in RAM only; no disk, no cache, no accounts; dose plan in tab memory | "Photos used only to identify"; scan history saved in the app; premium ₹100/month | Not stated in the listing | Not stated publicly | Not stated publicly | Privacy page exists; server-side app | Not verifiable |
| **Dose reminders** | **Yes** — local countdown, spoken in ml/hi/en, explicit "page must stay open" | Not stated publicly | Not stated publicly | Reminders listed as a feature | Not stated publicly | No | Not verifiable |
| **Offline behaviour** | Installable PWA, cached shell + taxonomy, warnings readable with no voice pack | Not stated publicly | Not stated publicly | Not stated publicly | Not stated publicly | Not stated publicly | Not verifiable |
| **Platform** | Any modern mobile browser; installable PWA | Android 8.0+ (iOS "on the way") | Android | iOS App Store | Android | Web | Not verifiable |
| **Price** | Free prototype; no paid tier | Free 3 scans/day; ₹100/month Premium | Free with in-app purchases | Not stated | Free | Free | Not verifiable |

### What this table does **not** claim

- It does not claim KathaPulse is more accurate than any of these products;
  none was tested.
- It does not claim Pill IQ, PharmaScan AI, MedLingual or MedScan lack a feature
  merely because the feature is not on their public page.
- It does not claim "the only" or "the first" multilingual medicine scanner.
  Multilingual label scanning already exists (MedScan reads labels aloud in
  Malayalam; MedLingual translates OTC labels into Hindi).
- **DoseBell could not be verified.** A table row is included for completeness,
  but nothing is asserted about it. Two similarly named products exist (MedBell,
  DoseBee) and were not treated as the same product.

### The honest differentiator

Not "AI scans medicine". That is common. The defensible claim is the
**combination**:

> a refusal-first safety engine (rules, not model output) + evidence a judge can
> audit field by field + a real batch audit + Malayalam/Hindi parity + zero
> server-side image persistence, in one workflow built for a 320 px phone.

---

## 5. Privacy and data handling (as implemented)

| Question | Answer in this build | Where it is enforced |
|---|---|---|
| Is the photo stored? | No. Read into `bytes`, processed, released with the request. | `app/main.py::_read_upload`, no `tempfile` anywhere in `app/` |
| Is it sent to a third party? | Only if `KATHA_VISION_API_KEY` is configured, and then as a base64 image to the configured OpenAI-compatible endpoint. Without a key, no image leaves the server. | `app/config.py`, `app/extraction.py` |
| Are scans logged? | No request bodies, no images, no per-user identifiers are logged. Provider failures log a status code, never a key or body. | `app/main.py`, `app/extraction.py` |
| Are results cached? | `Cache-Control: no-store` on every response, including the HTML shell. The service worker never caches a POST. | `app/main.py`, `static/sw.js` |
| Is the dose schedule stored? | No. The server derives a plan and returns it; the browser holds it in a variable and loses it on reload. | `app/audio_reminders.py`, `static/js/app.js` |
| Where is the API key kept? | Environment/`.env` only, git-ignored. Never in the repo, the archive, a log, or a response. | `.gitignore`, `scripts/make_submission_archive.sh` |

**DPDP Act 2023 alignment is a design posture, not a certification.** No consent
manager, data-fiduciary registration or audit has been performed.

### 5.1 Indian legal and regulatory boundaries (summary)

The full, code-referenced position is `docs/VALIDATION_REPORT.md` §10. In short:

- **DPDP Act 2023** — purpose limitation by construction (processing only on an
explicit capture or typed name), data minimisation (1600 px, 6 MiB, ≤10
medicines, ≤5 strips), storage limitation (RAM only, `no-store`, no
`localStorage`), and **zero data egress while no vision key is configured**. Not
done: consent notice/record, grievance officer, DPIA, and — if a vision key is
ever enabled — a transfer notice for the image that would then go to that
provider.
- **Drugs and Cosmetics Act 1940 / Rules 1945, CDSCO** — not a drug, not a
medical device, not CDSCO-certified, no diagnostic claim; the recall list is a
four-entry **pilot**, never described as a government feed; the app never tells a
patient to start, stop or change a dose. **Gap:** Schedule H/H1
(prescription-only) status is not checked — required before any pharmacy use.
- **IT Act 2000 / SPDI baseline** — no server-side store of sensitive health
data, HTTPS at the proxy, no interception or analytics, standard security headers
and input allowlists. Not claimed: ISO 27001, CERT-In audit, incident-response
runbook, HSTS header (owned by the edge).

---

## 6. Limitations a reviewer should know before judging

| Limitation | Consequence |
|---|---|
| No live vision key in this environment | `/health` reports `vision_keys: 0`; scans return `manual_required`. The AI-reading path is implemented and unit-tested with stubbed provider responses, not demonstrated live. |
| Recall list is a 4-entry curated pilot, not a CDSCO feed | The app says "recall list", never "government recall". MedicineWatch India is genuinely ahead here. |
| Catalogue is 48 molecules / 48 brands | A miss asks the user to type the name; it never invents a drug. |
| Translations have not been reviewed by a clinical translator | All 81 keys exist in ml/hi/en and script assertions pass, but native-speaker sign-off is outstanding. |
| Not a medical device | Screening aid only; every result carries a disclaimer. |
| CI has not run on GitHub | The workflow runs locally; no push was authorised. |
| Audio not heard on a real device | The selection/fallback logic is tested; headless Chromium has no ml-IN/hi-IN voice. |
| Static control labels stay bilingual Malayalam + English | Cosmetic: `LISTEN`/`STOP`/`SET`/`CANCEL` markup labels do not follow the selector, though every warning and script does. Fix queued after the freeze. |
| Batch caveat renders in the selected language only | The API returns `en`/`ml`/`hi`; the UI shows the active one. Captured in all three for the pack. |
| Schedule H/H1 status is not checked | The app flags duplication and interactions but does not say "prescription only". Required before pharmacy deployment. |

---

## 7. Where to read next

- `docs/VALIDATION_REPORT.md` — the test-backed clinical, translation and
  offline-error audit.
- `docs/NEURAVIZ_STAGE4_CHECKLIST.md` — Stage 4 finalist alignment, live-vision
  status, physical-phone protocol, four-screenshot capture runbook, voiceless
demo script, archive command.
- `docs/STAGE4_UPLOAD_CHECKLIST.md` — the manual steps: phone checks, optional
  video, key setup, the three files to upload and the statements to include.
- `README.md` — architecture, API, test commands, pass-by-pass history.
- `CONTRIBUTING.md` — setup, test gates, drug-data rules, security disclosure.
- `LICENSE` — MIT, with the medical-device / CDSCO boundary stated in the file.
- `AUDIT_REPORT.md` — independent audit notes and per-pass scorecards.
- Repository: <https://github.com/saviochackoxavier-tech/kathapulse-ai> (branch `main`).
