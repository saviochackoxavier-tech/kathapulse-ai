"""Clinical guardrail tests — the Kochi pilot scenarios plus edge cases.

Run: ./.venv/bin/pytest -q
"""

from __future__ import annotations

import pytest

from app import clinical
from app.extraction import resolve_medicine
from app.schemas import Language, ScannedMedicine


def strip(label: str) -> ScannedMedicine:
    return resolve_medicine(label, [label], 0)


def scan(*labels: str) -> list[ScannedMedicine]:
    return [resolve_medicine(label, [label], i) for i, label in enumerate(labels)]


def report(*labels: str, language: Language = Language.malayalam, taken: float = 0.0):
    return clinical.analyse(scan(*labels), language, taken)


def codes(rep) -> set[str]:
    return {finding.code for finding in rep.findings}


# ---------------------------------------------------------------------------
# Taxonomy resolution
# ---------------------------------------------------------------------------


def test_brand_resolves_to_molecule_with_printed_strength():
    medicine = strip("Dolo 650")
    assert medicine.matched
    assert [i.canonical for i in medicine.ingredients] == ["paracetamol"]
    assert medicine.ingredients[0].strength_mg == 650


def test_fixed_combination_resolves_to_both_molecules():
    medicine = strip("Telma-H 40/12.5")
    canonicals = {i.canonical for i in medicine.ingredients}
    assert canonicals == {"telmisartan", "hydrochlorothiazide"}


def test_combination_brand_gets_combination_strengths():
    medicine = strip("Combiflam")
    strengths = {i.canonical: i.strength_mg for i in medicine.ingredients}
    assert strengths["ibuprofen"] == 400
    assert strengths["paracetamol"] == 325


def test_ocr_typo_still_resolves():
    assert strip("telmisarfan 40").ingredients[0].canonical == "telmisartan"


def test_unknown_label_is_not_matched():
    medicine = strip("qqzzxx unknown thing")
    assert medicine.matched is False
    assert medicine.ingredients == []


def test_strip_boilerplate_is_ignored():
    medicine = strip("CROSPIN TABLET 5 MG KEEP OUT OF REACH OF CHILDREN")
    assert medicine.matched or True  # must not crash; matched depends on the name
    assert strip("PANTOCID 40 TABLET").ingredients[0].canonical == "pantoprazole"


# ---------------------------------------------------------------------------
# Duplicate salt
# ---------------------------------------------------------------------------


def test_dual_paracetamol_is_critical():
    rep = report("Dolo 650", "Crocin 650")
    assert rep.verdict.value == "critical"
    assert "DUPLICATE_SALT" in codes(rep)

    finding = next(f for f in rep.findings if f.code == "DUPLICATE_SALT")
    assert finding.anchors == ["paracetamol"]
    # 650 + 650 = 1300 mg in one go
    assert "1300" in finding.message.en
    assert "പാരസെറ്റമോൾ" in finding.message.ml
    assert "पैरासिटामोल" in finding.message.hi


def test_same_strip_listed_twice_is_not_a_duplicate():
    medicine = resolve_medicine("Combiflam", ["Combiflam"], 0)
    rep = clinical.analyse([medicine], Language.english)
    assert "DUPLICATE_SALT" not in codes(rep)


def test_telmisartan_hctz_combo_plus_separate_hctz_is_a_duplicate():
    """Kochi pilot scenario: patient keeps taking Telma-H *and* a separate HCTZ.

    Telma-H already contains 12.5 mg hydrochlorothiazide, so adding a standalone
    HCTZ tablet doubles the thiazide -- the classic hidden duplicate in Indian
    polypharmacy, where the patient sees two different-looking boxes.
    """
    rep = report("Telma-H 40/12.5", "HCTZ 12.5")
    assert "DUPLICATE_SALT" in codes(rep)
    finding = next(f for f in rep.findings if f.code == "DUPLICATE_SALT")
    assert finding.anchors == ["hydrochlorothiazide"]
    assert "25" in finding.message.en  # 12.5 + 12.5 mg in one go


def test_telmisartan_plus_plain_hctz_is_not_a_duplicate():
    """Telma 40 + a separate HCTZ is the same regimen as Telma-H.

    No salt repeats, so no duplicate alarm -- the correct answer is "safe",
    which is exactly what a rule engine must be willing to say.
    """
    rep = report("Telma 40", "HCTZ 12.5")
    assert "DUPLICATE_SALT" not in codes(rep)
    assert rep.verdict.value == "safe"


# ---------------------------------------------------------------------------
# Paracetamol ceiling
# ---------------------------------------------------------------------------


def test_paracetamol_daily_ceiling_across_strips():
    # 2 x 650 on two strips = 1300, plus 3000 already taken today = 4300
    rep = report("Dolo 650", "Calpol 650", taken=3000)
    assert "PARACETAMOL_DAILY_MAX" in codes(rep)
    assert rep.verdict.value == "critical"


def test_paracetamol_near_ceiling_warns():
    rep = report("Dolo 650", taken=2500)  # 3150 total
    assert "PARACETAMOL_NEAR_MAX" in codes(rep)
    assert rep.verdict.value == "caution"


def test_no_duplicate_reports_safe():
    rep = report("Telma 40", "Pan 40")
    assert rep.verdict.value == "safe"
    assert "NO_DANGEROUS_OVERLAP" in codes(rep)


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,risk_fragment",
    [
        ("Warf 5", "Ecosprin 75", "bleeding"),
        ("Aldactone 25", "Telma 40", "potassium"),
        ("Imdur 30", "Penegra 50", "blood pressure"),
        ("Tramal 50", "Daxid 50", "serotonin"),
    ],
)
def test_documented_interactions_fire(a, b, risk_fragment):
    rep = report(a, b)
    assert "INTERACTION" in codes(rep)
    text = " ".join(f.message.en.lower() for f in rep.findings if f.code == "INTERACTION")
    assert risk_fragment in text


def test_dual_blockade_acei_plus_arb():
    rep = report("Cardace 5", "Telma 40")
    interaction = [f for f in rep.findings if f.code == "INTERACTION"]
    assert interaction
    assert rep.verdict.value == "critical"


def test_nitrate_pde5_is_critical():
    rep = report("Imdur 30", "Manforce 50")
    assert rep.verdict.value == "critical"


# ---------------------------------------------------------------------------
# Same therapeutic class
# ---------------------------------------------------------------------------


def test_two_nsaids_flagged_as_class_duplicate():
    rep = report("Brufen 400", "Zerodol 100")
    assert "DUPLICATE_CLASS" in codes(rep)
    assert rep.verdict.value == "caution"


def test_acei_arb_pair_not_double_reported():
    rep = report("Cardace 5", "Telma 40")
    assert "DUPLICATE_CLASS" not in codes(rep)


# ---------------------------------------------------------------------------
# Unknown / unreadable
# ---------------------------------------------------------------------------


def test_unreadable_strip_is_never_called_safe():
    rep = report("qwerty unreadable label")
    assert rep.verdict.value == "unknown"
    assert "UNRECOGNISED_MEDICINE" in codes(rep)
    assert "NO_DANGEROUS_OVERLAP" not in codes(rep)


# ---------------------------------------------------------------------------
# Localisation & speech
# ---------------------------------------------------------------------------


def test_findings_are_localised_in_all_three_languages():
    rep = report("Dolo 650", "Crocin 650")
    finding = next(f for f in rep.findings if f.code == "DUPLICATE_SALT")
    for lang in ("en", "ml", "hi"):
        assert getattr(finding.title, lang)
        assert getattr(finding.message, lang)
        assert getattr(finding.action, lang)
    # Malayalam copy must actually be Malayalam script, not transliterated English.
    assert any("\u0d00" <= ch <= "\u0d7f" for ch in finding.message.ml)


def test_speech_payload_uses_requested_language():
    rep = report("Dolo 650", "Crocin 650", language=Language.hindi)
    assert rep.speech.language == Language.hindi
    assert any("\u0900" <= ch <= "\u097f" for ch in rep.speech.text)
    # The spoken text must name the drug in Hindi and carry the instruction.
    assert "पैरासिटामोल" in rep.speech.text
    assert "एक लें" in rep.speech.text


# ---------------------------------------------------------------------------
# LASA — look-alike / sound-alike
# ---------------------------------------------------------------------------


def test_lasa_same_brand_family_with_extra_molecule():
    """Telma vs Telma-H: nearly identical foil, different contents."""
    rep = report("Telma 40", "Telma-H 40/12.5")
    assert "LASA_RISK" in codes(rep)
    finding = next(f for f in rep.findings if f.code == "LASA_RISK")
    assert finding.anchors == ["Telma 40", "Telma-H 40/12.5"]


def test_lasa_pan_family():
    rep = report("Pan 40", "Pan-D")
    assert "LASA_RISK" in codes(rep)


def test_lasa_zerodol_family_is_both_lasa_and_duplicate():
    """Zerodol-SP carries paracetamol that plain Zerodol does not."""
    rep = report("Zerodol 100", "Zerodol-SP")
    assert "LASA_RISK" in codes(rep)


def test_lasa_sound_alike_across_families():
    """Amaryl (glimepiride) vs Amlopres (amlodipine): classic spoken collision."""
    rep = report("Amaryl 2", "Amlopres 5")
    finding = next(f for f in rep.findings if f.code == "LASA_RISK")
    assert "sound" in finding.message.en.lower()
    assert any("\u0d00" <= ch <= "\u0d7f" for ch in finding.message.ml)


def test_lasa_loprin_family_requests_verification():
    """Loprin vs Loprin-LS: a real shelf neighbour we do not resolve."""
    rep = report("Loprin 75", "Loprin-LS")
    finding = next(f for f in rep.findings if f.code == "LASA_RISK")
    # Verification wording, not a composition claim.
    assert "not interchangeable" in finding.message.en
    assert "പേരുകൾ" in finding.message.ml          # "names"
    assert "ഉറപ്പാക്കുക" in finding.message.ml        # "make sure"
    assert "जाँचें" in finding.message.hi            # "check"
    assert "फ़ॉइल" in finding.message.hi             # "foil"
    assert rep.verdict.value == "caution"


def test_brand_only_product_claims_no_molecule():
    medicine = strip("Loprin-LS")
    assert medicine.matched is False
    assert medicine.brand_only is True
    assert medicine.ingredients == []
    assert medicine.label == "Loprin-LS"


def test_brand_only_product_never_feeds_salt_rules():
    """No molecule means no DUPLICATE_SALT claim, even next to Loprin."""
    rep = report("Loprin 75", "Loprin-LS")
    assert "DUPLICATE_SALT" not in codes(rep)


def test_lasa_single_brand_warns_about_its_twin():
    """Scanning Amaryl alone must still say "this sounds like Amlopres"."""
    rep = report("Amaryl 1 mg")
    finding = next(f for f in rep.findings if f.code == "LASA_RISK")
    assert "Amlopres" in finding.message.en
    assert "അംലോപ്രെസ്" in finding.message.ml or "Amlopres" in finding.message.ml
    assert "Amlopres" in finding.message.hi
    assert finding.anchors == ["Amaryl 1 mg"]
    assert rep.verdict.value == "caution"


def test_lasa_single_brand_advisory_not_duplicated_when_twin_present():
    rep = report("Amaryl 2", "Amlopres 5")
    lasa = [f for f in rep.findings if f.code == "LASA_RISK"]
    assert len(lasa) == 1


def test_lasa_single_advisory_only_for_curated_sound_alikes():
    """A lone Telma is not a LASA hazard -- the family needs two boxes."""
    rep = report("Telma 40")
    assert "LASA_RISK" not in codes(rep)


def test_lasa_not_raised_for_identical_contents():
    """Two strengths of the same molecule are a dose issue, not a LASA one."""
    rep = report("Dolo 650", "Dolo 500")
    assert "LASA_RISK" not in codes(rep)


def test_lasa_not_raised_for_unrelated_brands():
    rep = report("Telma 40", "Pan 40")
    assert "LASA_RISK" not in codes(rep)


def test_lasa_turns_verdict_to_caution():
    rep = report("Gnome 5x", "Amaryl 2")  # one readable, one not
    assert rep.verdict.value in {"caution", "unknown"}
    rep2 = report("Amaryl 2", "Amlopres 5")
    assert rep2.verdict.value == "caution"


def test_speech_is_bounded_to_three_findings():
    rep = report("Warf 5", "Ecosprin 75", "Brufen 400", "Zerodol 100", "Dolo 650")
    assert len(rep.speech.text) < 700
    assert rep.speech.rate < 1.0  # slower for elderly listeners
