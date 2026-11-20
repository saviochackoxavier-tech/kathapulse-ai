"""Measured accuracy of duplicate-salt detection on a labelled corpus.

The Inspector asks for >95% duplicate-salt accuracy.  A claim is not evidence,
so this file scores the engine against 44 labelled cases -- positives that a
real Kerala household could present (two paracetamol brands, a combination
product plus its single molecule, a hidden HCTZ inside Telma-H) and negatives
that must stay quiet (a legitimate co-prescription of different molecules).

Reported metrics: precision, recall and accuracy of the boolean
"is there a duplicate salt?" decision.
"""

from __future__ import annotations

from app import clinical
from app.extraction import resolve_medicine
from app.schemas import Language

# (labels, is_duplicate, salt_expected_among_anchors)
CASES: list[tuple[tuple[str, ...], bool, str | None]] = [
    # -- positives: same molecule on two strips ---------------------------
    (("Dolo 650", "Crocin 650"), True, "paracetamol"),
    (("Dolo 650", "Calpol 500"), True, "paracetamol"),
    (("Pacimol 650", "Dolo 650"), True, "paracetamol"),
    (("Metacin 500", "Crocin 500"), True, "paracetamol"),
    (("DOLO 650", "dolo650"), True, "paracetamol"),           # casing/format noise
    (("Dolo-650", "Paracetamol 650"), True, "paracetamol"),    # brand vs molecule
    # -- positives: combination product + its single molecule -------------
    (("Combiflam", "Dolo 650"), True, "paracetamol"),
    (("Zerodol-SP", "Crocin 650"), True, "paracetamol"),
    (("Ultracet", "Pacimol 650"), True, "paracetamol"),
    (("Telma-H 40/12.5", "HCTZ 12.5"), True, "hydrochlorothiazide"),
    (("Telma-H", "Telma 40"), True, "telmisartan"),
    (("Montair-LC", "Levocet 5"), True, "levocetirizine"),
    (("Augmentin 625", "Mox 500"), True, "amoxicillin"),
    (("Clavam 625", "Novamox 500"), True, "amoxicillin"),
    (("Glycomet-GP", "Glimy 1"), True, "glimepiride"),
    (("Glimestar-M", "Glycomet 500"), True, "metformin"),
    (("Pan-D", "Pan 40"), True, "pantoprazole"),
    (("Combiflam", "Brufen 400"), True, "ibuprofen"),
    # -- positives with OCR-style slips ----------------------------------
    (("Dolo 650", "Crocin 6S0"), True, "paracetamol"),
    # -- negatives: different molecules, legitimate together --------------
    (("Telma 40", "Pan 40"), False, None),
    (("Dolo 650", "Brufen 400"), False, None),
    (("Telma 40", "HCTZ 12.5"), False, None),          # = Telma-H regimen
    (("Thyronorm 50", "Metformin 500"), False, None),
    (("Azee 500", "Pan 40"), False, None),
    (("Montair 10", "Cetzine 10"), False, None),
    (("Ecosprin 75", "Atorva 10"), False, None),
    (("Amlopres 5", "Telma 40"), False, None),
    (("Cardace 5", "Metformin 500"), False, None),
    (("Omez 20", "Domstal 10"), False, None),
    (("Zerodol 100", "Pan 40"), False, None),
    (("Flagyl 400", "Dolo 650"), False, None),
    (("Glycomet 500", "Telma 40"), False, None),
    (("Clopilet 75", "Atorva 10"), False, None),
    (("Lasix 40", "Aldactone 25"), False, None),
    (("Metolar 50", "Amlopres 5"), False, None),
    (("Rosuvas 10", "Ecosprin 75"), False, None),
    (("Doxy 100", "Pan 40"), False, None),
    (("Wysolone 10", "Pan 40"), False, None),
    (("Asthalin 2", "Montair 10"), False, None),
    (("Januvia 100", "Metformin 500"), False, None),
    (("Imdur 30", "Atorva 10"), False, None),
    # -- negatives that contain a shared *class* but not a shared salt ----
    (("Brufen 400", "Zerodol 100"), False, None),
    (("Telma 40", "Losar 50"), False, None),
    (("Amaryl 2", "Diamicron 80"), False, None),
]


def _duplicate_anchors(labels: tuple[str, ...]) -> tuple[bool, set[str]]:
    medicines = [
        resolve_medicine(label, [label], index) for index, label in enumerate(labels)
    ]
    report = clinical.analyse(medicines, Language.english)
    duplicate_findings = [f for f in report.findings if f.code == "DUPLICATE_SALT"]
    anchors: set[str] = set()
    for finding in duplicate_findings:
        anchors.update(finding.anchors)
    return bool(duplicate_findings), anchors


def test_duplicate_salt_accuracy_above_95_percent():
    true_positive = false_positive = true_negative = false_negative = 0
    salt_hits = salt_total = 0
    misses: list[str] = []

    for labels, expected, salt in CASES:
        detected, anchors = _duplicate_anchors(labels)

        if expected and detected:
            true_positive += 1
            if salt:
                salt_total += 1
                if salt in anchors:
                    salt_hits += 1
                else:
                    misses.append(f"{labels}: duplicate found but wrong salt {anchors}")
        elif expected and not detected:
            false_negative += 1
            misses.append(f"{labels}: MISSED duplicate")
        elif not expected and detected:
            false_positive += 1
            misses.append(f"{labels}: FALSE ALARM")
        else:
            true_negative += 1

    total = len(CASES)
    correct = true_positive + true_negative
    accuracy = correct / total
    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0
    salt_accuracy = salt_hits / salt_total if salt_total else 1.0

    print(
        f"\nDuplicate-salt corpus: {total} cases | "
        f"accuracy {accuracy:.1%} | precision {precision:.1%} | recall {recall:.1%} | "
        f"correct-salt {salt_accuracy:.1%}"
    )
    if misses:
        print("  " + "\n  ".join(misses))

    assert accuracy >= 0.95, f"accuracy {accuracy:.1%} below 95%: {misses}"
    assert precision >= 0.95, f"precision {precision:.1%} below 95%: {misses}"
    assert recall >= 0.95, f"recall {recall:.1%} below 95%: {misses}"
    assert salt_accuracy >= 0.95, f"wrong salt identified in {misses}"
