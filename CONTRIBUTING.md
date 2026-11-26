# Contributing to KathaPulse AI

Thanks for taking the time to look at this project. It is a **medicine-safety aid**, so the bar for
a change is higher than "it works": a change must not make a warning easier to misread, easier to
miss, or easier to get wrong.

## Ground rules

1. **No patient data, ever, on the server.** No database, no writable volume, no cache directory, no
   `tempfile`, no logging of a request body or an image. The scan path is RAM-only and there is a
   test that walks the AST to keep it that way.
2. **The model never decides.** The vision/OCR tier only reads printed text. Every verdict, finding
   and severity comes from deterministic rules over the closed catalogue (`app/clinical.py`,
   `app/recall.py`, `app/audio_reminders.py`).
3. **Never guess a medicine.** Unknown, unreadable or low-confidence input must produce
   `manual_required` / `retake`, not a plausible-looking match.
4. **All three languages or it does not ship.** Malayalam, Hindi and English strings are asserted by
   tests; a new user-facing string needs all three.
5. **No secrets in the repository.** Keys live in the environment or `.env` (git-ignored). Never
   commit a key, a screenshot of one, or a patient's photograph.

## Development setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt      # Windows: .\.venv\Scripts\pip.exe
./scripts/serve.sh                               # 0.0.0.0:3004, supervised
cd tests/js && npm ci                            # Node 20+ for the frontend suites
```

No vision key is needed for development or for any test. Photo scans fall back to OCR and then to the
manual-entry panel; the five demo presets exercise the full deterministic path.

## Required checks before opening a pull request

Run both halves and paste the results in the PR description:

```bash
./.venv/bin/pytest -o addopts="" -q

cd tests/js
for t in state retry exif-scrub audio-pack audiopack presets recall groundtruth reminders; do
  node "$t.test.mjs" || exit 1
done
```

`presets.test.mjs` needs the server running on port 3004 (or set
`KATHA_BASE_URL=http://127.0.0.1:<port>`). Current baseline: **348 backend checks** and
**119 frontend checks**, all passing.

A pull request that changes a warning, a threshold or a catalogue entry must also say **which test
covers the new behaviour**. If nothing covers it, add the test in the same PR — do not weaken an
existing assertion to make a change fit.

## Changing drug data

The catalogue is curated pilot data, not a licensed formulary.

* **Add or edit a molecule** → `app/taxonomy.py`. Every brand in `app/knowledge_base.py` is checked
  against it by a test, so the two cannot drift apart.
* **Add or edit a brand/product** → `app/knowledge_base.py`, including its molecules, pack
  strengths, dosage form, tri-lingual cautions and age band.
* **Add a recall notice** → `app/recall.py`. Refs are local trace labels (`PILOT-RCL-01`), never a
  CDSCO citation unless you actually have the citation. Update the count assertions in
  `tests/test_recall.py`, `/health` and this README together.
* **After any catalogue change**, run:

  ```bash
  ./.venv/bin/python scripts/audit_knowledge_base.py    # must exit 0
  ```

  It verifies every indexed name, molecule, strength, script and the provenance date
  (`CATALOGUE_VERIFIED_ON`). Update that date only when the data was genuinely re-reviewed.

## Adding a language

1. Flip the row to `enabled=True` in `app/languages.py`.
2. Add the code to the `Language` enum and a field to `LanguageText` in `app/schemas.py`.
3. Translate the keys in `app/i18n.py` (English fallback exists, but a fallback is not a translation).
4. Add the script's font to the stack in `static/css/styles.css`.
5. Confirm the device TTS locale, and test at 320 px — transliterated drug names get long.
6. Run the script/coverage assertions and the full suite.

## Code style

* Python 3.12, type hints on public functions, docstrings that explain **why** a rule exists.
* Pydantic models use `extra="forbid"`; add a field rather than loosening a model.
* JavaScript is plain ES modules, no build step, no framework. Keep pure logic (state, EXIF scrub,
  dose clock) separable from DOM code so it stays testable in Node.
* Comments should record a decision or a hazard, not restate the next line.

## Security disclosure

Please do **not** open a public issue for a vulnerability. Report it privately to the maintainer
listed on the repository profile, with reproduction steps and the affected endpoint. Include:

* the request that triggers it (redact any real key),
* the observed behaviour and the expected behaviour,
* whether patient data could be exposed or a warning suppressed.

Relevant classes for this project: an image escaping RAM to disk, a key reaching a log or response,
prompt injection that changes a verdict, an oversized/forged upload bypassing validation, and a
service-worker path that caches a scan.

## Pull request checklist

- [ ] The change keeps the decision path free of model output.
- [ ] No server-side persistence, logging of request bodies, or new writable path.
- [ ] New user-facing strings exist in ml, hi and en.
- [ ] Tests added or updated for the new behaviour; no existing assertion weakened.
- [ ] `pytest` and all nine Node suites pass locally.
- [ ] `scripts/audit_knowledge_base.py` exits 0 if drug data changed.
- [ ] No `.env`, key material, patient photo or generated artifact is staged.
- [ ] Documentation updated (`README.md`, `docs/VALIDATION_REPORT.md` where behaviour changed).

## License

By contributing you agree that your contribution is licensed under the repository's
[MIT License](LICENSE). The medical-device boundary and data-handling position you must not
contradict are in [`DISCLAIMER.md`](DISCLAIMER.md).
