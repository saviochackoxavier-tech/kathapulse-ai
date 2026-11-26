# KathaPulse AI — Stage 4 upload checklist (manual steps)

**Build:** `v1.6.1` · **Stage 4 (Final Stage)** · **deadline 10 December 2026**
This file lists everything **only a human can do**. Everything else is produced
by `scripts/build_stage4_pack.py` into `artifacts/stage4_submission/`.

> The portal governs. Re-check the deadline, field labels and permitted file
> types on `neuraviz.com/aichallenge2026/login` on submission day; this document
> is not the rules.

---

## 0. One-time portal details to fill in

| Placeholder | Where it appears | Replace with |
|---|---|---|
| `<team name>` | `README.md` header | your registered participant/team name |
| `<name> · <email>` | `README.md` header | the name and email on the entry |
| Repository URL + commit | final summary / report cover | the URL you are willing to share, and the 7-character commit |

The commit hash is printed at the end of `scripts/build_stage4_pack.py` and in
`artifacts/stage4_submission/SHA256SUMS.txt`.

---

## 1. Physical Android phone (10 minutes, required for honesty)

Headless Chromium has **no Malayalam or Hindi voice**; the sandbox capture shows
the visible fallback notice instead. On a real phone:

- [ ] Settings → System → Languages & input → Text-to-speech → install
      **Malayalam** and **Hindi** voices.
- [ ] Open the preview URL, choose **മലയാളം**, tap **Glycomet GP · ground truth**,
      tap **കേൾക്കുക / Listen** → audible Malayalam, **Stop** silences it.
- [ ] Switch to **हिन्दी**, repeat → Hindi voice, not Malayalam with a Hindi
      accent and not English.
- [ ] Set `1-0-1`, tap **Set** → green countdown banner; wait for (or move a slot
      to) the next dose and confirm the spoken announcement.
- [ ] Uninstall the Malayalam voice and repeat once → the app must show its
      explicit fallback notice and keep the full script on screen.
- [ ] 320 px and 360 px: `document.documentElement.scrollWidth === clientWidth`,
      no sideways scroll, no clipped Malayalam molecule names, every control
      reachable one-handed.
- [ ] Service worker: load online once (DevTools → Application → Service
      Workers shows `kathapulse-v10` activated), enable airplane mode, reload →
      cached shell renders; a scan shows a localised retryable error, not a blank
      page; re-enable the network and Retry succeeds.

Record with the phone's own screen recorder if you want video evidence
(`phone-ml-voice.mp4`, `phone-hi-voice.mp4`, `phone-offline-shell.jpg`). These
files are **not** in the pack unless you add them.

## 2. Optional 60–90 s voiceless demo video

Script: `docs/NEURAVIZ_STAGE4_CHECKLIST.md` §9. Rules: no narration, English
captions, unlisted upload, and **"simulated confidence response"** on screen for
the segment that uses the injected fixture. Paste the link into the portal's
optional demo field.

## 3. Live vision key (optional — only if you want a real photo demo)

1. Freebuff → **Settings → Project settings → Secrets** → add
   `KATHA_VISION_API_KEY` (never paste it in chat, a file or a screenshot).
2. Restart the server (`./scripts/serve.sh`), then
   `./.venv/bin/python scripts/check_vision.py` → expect `status: ok`.
3. Re-run §8 captures **without** the simulated label if the live model answers.
   Without a key, keep the labelled captures and state the limitation.

## 4. Upload (Step 5, participant only)

Upload at most **three** files plus the paste-ready summary:

| Portal field | File to upload |
|---|---|
| Final summary | `KathaPulse-AI-Stage4-Summary.pdf` |
| Final report | `KathaPulse-AI-Stage4-Report.pdf` |
| Presentation | `KathaPulse-AI-Stage4-Pitch.pdf` |
| Optional demo link | your unlisted video URL, or the live preview URL |
| Repository / supporting | `kathapulse-ai-v1.6.1-*.zip` **only if** the portal accepts a 4th file or a link field |

Paste the summary from `KathaPulse-AI-Stage4-Summary.md` (plain text, ~100
words). Do not upload the `.md` sources if the portal rejects non-PDF files.

- [ ] Every file opens after upload (re-download one to confirm).
- [ ] No `.env`, no key, no personal photo, no phone number in any upload.
- [ ] Screenshot the confirmation page and keep the reference number.

## 5. Final statements to include verbatim

- "Live vision model: **not enabled** in this environment (`vision_keys: 0`);
  all scan results shown in the evidence pack are deterministic presets, and the
  confidence-gate captures are labelled **simulated confidence response**."
- "Recall data: four curated **pilot** notices, not a CDSCO feed."
- "Not a medical device, not a substitute for a licensed pharmacist or doctor,
  and not CDSCO-certified."
- "Malayalam and Hindi clinical wording has **not** been reviewed by a native
  clinical reviewer."
