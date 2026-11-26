# Medical disclaimer and scope

KathaPulse AI is an **educational medicine-safety aid** and a prototype submitted to the NeuraViz AI
Challenge 2026–27. It is **not a medical device** and has not been cleared, approved or certified by
the Central Drugs Standard Control Organisation (CDSCO) or any other regulator.

It does not provide diagnosis, treatment, prescribing advice, or a substitute for a licensed
pharmacist or physician. It never instructs a patient to start, stop or change a dose.

The bundled drug catalogue (`app/taxonomy.py`, `app/knowledge_base.py`) is **curated pilot data** for
demonstration, not a licensed formulary. The recall list (`app/recall.py`) is **four curated pilot
notices**, not an official pharmacovigilance feed, and a batch that produces no warning is not
guaranteed to be safe, genuine or free of quality defects.

Always confirm with a licensed pharmacist or physician before taking, stopping or changing any
medicine.

## Data handling

The service processes uploaded images in RAM only, writes nothing to disk, keeps no accounts and no
cookies, and returns `Cache-Control: no-store`. A batch number and expiry date are treated as the
same class of data as a drug name: no patient identifier, no retention. If a vision provider key is
configured, the image is sent as a base64 data URL to that provider — a third-party transfer that
must be disclosed to users before production use.

DPDP Act 2023 alignment described in the README is a **design posture, not a certification**. No
consent manager, data-fiduciary registration, grievance officer or DPIA exists in this build.

## Limits of the evidence

The AI-reading path is implemented and unit-tested against stubbed provider responses. In the
submitted environment no vision key is configured (`vision_keys: 0`), so photo scans return
`manual_required`; captures that show a confidence value derived from a simulated response are
labelled **"simulated confidence response"**. Translation and clinical review of the Malayalam and
Hindi copy by native speakers is outstanding.

See [`docs/VALIDATION_REPORT.md`](docs/VALIDATION_REPORT.md) §9–§11 for the code-referenced security,
legal and catalogue audit, including the gaps.
