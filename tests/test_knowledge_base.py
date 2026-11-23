"""Ground-truth knowledge base: matching, cautions, age bands and the fallback.

The promise of this module is narrow and testable:

  * it knows real Kerala shelf products and their molecules, and every molecule
    it names exists in the clinical taxonomy (a test enforces it);
  * it resolves text the alias table gets *wrong* as well as text it misses —
    "Glycomet GP" is metformin **and** glimepiride, not plain Glycomet;
  * it never invents a drug: below the similarity floor it returns nothing and
    the app keeps asking the user;
  * when the vision tier dies, the request still succeeds with a localised,
    structured answer and writes nothing.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clinical, extraction, i18n, knowledge_base as kb, main, taxonomy
from app.schemas import Language, Severity, Verdict

ALL_CANONICALS = {drug.canonical for drug in taxonomy.all_drugs()}
MALAYALAM_REGEX = __import__("re").compile(r"[\u0d00-\u0d7f]")
DEVANAGARI_REGEX = __import__("re").compile(r"[\u0900-\u097f]")


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------


def test_the_index_is_big_enough_to_be_useful():
    counts = kb.stats()

    assert counts["indexed_names"] >= 120, counts  # the pilot shelf surface
    assert counts["brands"] >= 40, counts
    assert counts["molecules"] == len(taxonomy.all_drugs())


def test_every_curated_molecule_exists_in_the_clinical_taxonomy():
    """The knowledge base can never introduce a drug the engine cannot rule on."""
    unknown = {
        molecule
        for product in kb.PRODUCTS
        for molecule in product.molecules
        if molecule not in ALL_CANONICALS
    }
    assert unknown == set(), f"molecules not in taxonomy: {sorted(unknown)}"


def test_every_curated_strength_belongs_to_its_own_product():
    for product in kb.PRODUCTS:
        declared = {canonical for canonical, _ in product.strengths}
        assert declared <= set(product.molecules), product.brand


def test_brand_names_are_unique():
    brands = [product.brand for product in kb.PRODUCTS]
    assert len(brands) == len(set(brands))


def test_the_index_keys_are_compact():
    assert all(key == kb._compact(key) for key in kb.INDEX)
    assert all(len(key) >= kb.MIN_KEY_LEN for key in kb.INDEX)


def test_the_kerala_products_from_the_brief_are_present():
    expected = {
        "Telma-H",
        "Dolo 650",
        "Amaryl 1",
        "Glycomet-GP",
        "Pan-D",
        "Augmentin 625",
        "Combiflam",
        "Zerodol-SP",
        "Montair-LC",
        "Glycomet 500",
    }
    assert expected <= {product.brand for product in kb.PRODUCTS}


# ---------------------------------------------------------------------------
# Matching: exact, space/dash-insensitive, fuzzy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "printed,brand,molecules",
    [
        ("Telma-H", "Telma-H", ("telmisartan", "hydrochlorothiazide")),
        ("Telma H", "Telma-H", ("telmisartan", "hydrochlorothiazide")),
        ("TELMAH", "Telma-H", ("telmisartan", "hydrochlorothiazide")),
        ("Telma-AM", "Telma-AM", ("telmisartan", "amlodipine")),
        ("Pan-D", "Pan-D", ("pantoprazole", "domperidone")),
        ("PAN D", "Pan-D", ("pantoprazole", "domperidone")),
        ("Glycomet GP", "Glycomet-GP", ("metformin", "glimepiride")),
        ("glycomet-gp", "Glycomet-GP", ("metformin", "glimepiride")),
        ("GLYCOMETGP", "Glycomet-GP", ("metformin", "glimepiride")),
        ("Augmentin 625", "Augmentin 625", ("amoxicillin", "clavulanic_acid")),
        ("Zerodol-SP", "Zerodol-SP", ("aceclofenac", "paracetamol")),
        ("Montair-LC", "Montair-LC", ("montelukast", "levocetirizine")),
    ],
)
def test_a_printed_brand_resolves_to_its_exact_molecules(printed, brand, molecules):
    resolution = kb.resolve(printed)

    assert resolution is not None, f"{printed!r} did not resolve"
    assert resolution.brand == brand
    assert resolution.molecules == molecules
    assert resolution.method == "ground_truth"


def test_ocr_slips_still_land_on_the_right_box():
    for printed, molecules in (
        ("Augmentn 625", ("amoxicillin", "clavulanic_acid")),
        ("Glyc0met GP", ("metformin", "glimepiride")),
        ("Montair - LC", ("montelukast", "levocetirizine")),
    ):
        resolution = kb.resolve(printed)
        assert resolution is not None, f"{printed!r} did not resolve"
        assert resolution.molecules == molecules, printed


@pytest.mark.parametrize(
    "printed", ["", "   ", "abc", "nonsense text", "tablet", "store below 25 c"]
)
def test_a_guess_is_never_returned(printed):
    assert kb.resolve(printed) is None


def test_every_resolution_only_names_known_molecules():
    for brand in ("Telma-H", "Pan-D", "Augmentin 625", "Ultracet", "Amaryl 1"):
        resolution = kb.resolve(brand)
        assert resolution is not None
        assert set(resolution.molecules) <= ALL_CANONICALS


def test_resolution_is_deterministic():
    first = kb.resolve("Glycomet GP")
    second = kb.resolve("Glycomet GP")

    assert first == second
    assert first.score == 1.0


# ---------------------------------------------------------------------------
# The clinically important case: more specific than the alias table
# ---------------------------------------------------------------------------


def test_the_taxonomy_alone_misses_the_second_molecule():
    """Why the fallback exists: this is the bug it was written for."""
    taxonomy_matches = {drug.canonical for drug in taxonomy.lookup("Glycomet GP")}
    kb_matches = set(kb.resolve("Glycomet GP").molecules)

    assert taxonomy_matches == {"metformin"}, "taxonomy behaviour changed"
    assert kb_matches == {"metformin", "glimepiride"}
    assert kb_matches > taxonomy_matches


def test_a_more_specific_ground_truth_verdict_wins():
    medicine = extraction.resolve_medicine("Glycomet GP", ["Glycomet GP"], 0)

    assert medicine.matched is True
    assert medicine.verified_by == "ground_truth"
    assert {i.canonical for i in medicine.ingredients} == {"metformin", "glimepiride"}
    # The pack strengths come from the product, not from a printed number.
    assert {i.canonical: i.strength_mg for i in medicine.ingredients} == {
        "metformin": 500,
        "glimepiride": 1,
    }


def test_a_taxonomy_exact_match_is_not_relabelled_as_ground_truth():
    medicine = extraction.resolve_medicine("Dolo 650", ["Dolo 650"], 0)

    assert medicine.verified_by == "taxonomy"


def test_the_ground_truth_beats_the_alias_table_on_a_spacing():
    medicine = extraction.resolve_medicine("PAN D", ["PAN D"], 0)

    assert medicine.verified_by == "ground_truth"
    assert {i.canonical for i in medicine.ingredients} == {"pantoprazole", "domperidone"}


def test_unreadable_text_stays_unreadable():
    medicine = extraction.resolve_medicine("SMUDGED FOIL", ["SMUDGED FOIL"], 0)

    assert medicine.matched is False
    assert medicine.ingredients == []
    assert medicine.verified_by == ""


# ---------------------------------------------------------------------------
# Cautions and age bands
# ---------------------------------------------------------------------------


def test_cautions_come_from_the_class_or_the_override():
    assert "bleeding" in kb.cautions_for("warfarin")
    assert "ulcer" in kb.cautions_for("diclofenac")
    assert "low_sugar" in kb.cautions_for("glimepiride")
    assert "pregnancy" in kb.cautions_for("telmisartan")


@pytest.mark.parametrize(
    "canonical,age,expected",
    [
        ("aspirin", 10, "child"),
        ("aspirin", 40, None),
        ("ciprofloxacin", 12, "child"),
        ("doxycycline", 6, "child"),
        ("glimepiride", 70, "elderly"),
        ("diclofenac", 68, "elderly"),
        ("alprazolam", 70, "elderly"),
        ("paracetamol", 3, None),
        ("amlodipine", 80, None),
        ("telmisartan", 300, None),  # out of range is the schema's job, not this
    ],
)
def test_age_bands_only_exist_where_a_label_states_one(canonical, age, expected):
    assert kb.age_conflicts(canonical, age) == expected


def test_an_unknown_molecule_has_no_opinion():
    assert kb.cautions_for("not_a_drug") == ()
    assert kb.age_band("not_a_drug") == (None, None)


# ---------------------------------------------------------------------------
# Catalogue (the public feed)
# ---------------------------------------------------------------------------


def test_the_catalogue_is_patient_free_and_complete():
    entries = kb.catalogue()

    assert len(entries) == len({entry["brand"] for entry in entries})
    assert len(entries) >= 40
    for entry in entries:
        assert entry["brand"]
        assert entry["molecules"], entry["brand"]
        assert set(entry) == {
            "brand",
            "form",
            "molecules",
            "strengths",
            "cautions",
            "age_min",
            "age_max",
            "note",
        }
        for molecule in entry["molecules"]:
            assert molecule["canonical"] in ALL_CANONICALS
        for caution in entry["cautions"]:
            assert MALAYALAM_REGEX.search(caution["text"]["ml"]), caution["key"]
            assert DEVANAGARI_REGEX.search(caution["text"]["hi"]), caution["key"]


def test_every_caution_key_has_three_languages():
    for key in i18n.CAUTIONS:
        for lang in ("en", "ml", "hi"):
            assert i18n.t(f"kb.caution.{key}", lang).strip(), (key, lang)


# ---------------------------------------------------------------------------
# API: /knowledge.json and /health
# ---------------------------------------------------------------------------


def test_knowledge_feed_serves_the_catalogue():
    response = TestClient(main.app).get("/knowledge.json")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["entries"])
    assert body["indexed_names"] >= 120
    assert body["brands"] == len(kb.PRODUCTS)
    assert body["fuzzy_threshold"] == kb.FUZZY_MIN_SCORE

    telma_h = next(e for e in body["entries"] if e["brand"] == "Telma-H")
    assert {m["canonical"] for m in telma_h["molecules"]} == {
        "telmisartan",
        "hydrochlorothiazide",
    }
    # Data only: nothing request-specific, nothing secret.
    assert "scan_id" not in json.dumps(body)
    assert "KATHA_VISION" not in json.dumps(body)


def test_health_reports_the_knowledge_base_size():
    body = TestClient(main.app).get("/health").json()

    assert body["knowledge_base_entries"] >= 120
    assert body["knowledge_base_brands"] == len(kb.PRODUCTS)


# ---------------------------------------------------------------------------
# API: the fallback, and the age rule
# ---------------------------------------------------------------------------


def verify(payload: dict):
    return TestClient(main.app).post("/verify-medicines", json=payload)


def test_api_reports_ground_truth_verification():
    response = verify({"medicines": [{"name": "Glycomet GP"}], "language": "ml"})

    assert response.status_code == 200
    body = response.json()
    medicine = body["medicines"][0]
    assert medicine["verified_by"] == "ground_truth"
    assert {i["canonical"] for i in medicine["ingredients"]} == {
        "metformin",
        "glimepiride",
    }
    assert body["ground_truth_verified"] is True
    assert body["safety"]["verdict"] != Verdict.unknown


def test_api_does_not_claim_ground_truth_for_a_taxonomy_match():
    body = verify({"medicines": [{"name": "Dolo 650"}], "language": "en"}).json()

    assert body["medicines"][0]["verified_by"] == "taxonomy"
    assert body["ground_truth_verified"] is False


def test_api_age_warning_fires_only_when_an_age_is_given():
    with_age = verify(
        {"medicines": [{"name": "Amaryl 1"}], "language": "ml", "age_years": 72}
    ).json()
    without = verify({"medicines": [{"name": "Amaryl 1"}], "language": "ml"}).json()

    assert "AGE_WARNING" in {f["code"] for f in with_age["safety"]["findings"]}
    assert "AGE_WARNING" not in {f["code"] for f in without["safety"]["findings"]}
    assert MALAYALAM_REGEX.search(with_age["safety_message_ml"])
    assert DEVANAGARI_REGEX.search(with_age["safety_message_hi"])


def test_api_flags_a_child_dose_that_the_label_forbids():
    body = verify(
        {
            "medicines": [{"name": "Ecosprin 75"}],
            "language": "en",
            "age_years": 9,
        }
    ).json()
    finding = next(f for f in body["safety"]["findings"] if f["code"] == "AGE_WARNING")

    assert finding["severity"] == Severity.warning.value
    assert "16" in finding["message"]["en"]
    assert finding["anchors"] == ["aspirin"]


@pytest.mark.parametrize("age", [-1, 121, 1000])
def test_api_rejects_an_impossible_age(age):
    assert verify({"medicines": [{"name": "Dolo 650"}], "age_years": age}).status_code == 422


def test_an_age_inside_the_band_adds_nothing():
    body = verify(
        {"medicines": [{"name": "Dolo 650"}], "language": "en", "age_years": 34}
    ).json()

    assert "AGE_WARNING" not in {f["code"] for f in body["safety"]["findings"]}


# ---------------------------------------------------------------------------
# Resilience: the vision tier dies, the request still answers
# ---------------------------------------------------------------------------


class _DeadProvider:
    """Every call raises: a network drop, not an HTTP error."""

    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        _DeadProvider.calls += 1
        raise httpx.ConnectError("network is down")


def test_the_knowledge_base_needs_no_network(monkeypatch):
    """Resolution and the catalogue are pure functions: no httpx, no sockets."""
    _DeadProvider.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _DeadProvider)

    assert kb.resolve("Glycomet GP").molecules == ("metformin", "glimepiride")
    assert len(kb.catalogue()) >= 40
    assert _DeadProvider.calls == 0


def test_a_vision_network_drop_still_returns_a_structured_answer(monkeypatch, tmp_path):
    """100% uptime: the photo path degrades to a localised manual prompt."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    monkeypatch.setenv("KATHA_VISION_API_KEY", "unit-test-key")
    monkeypatch.setenv("KATHA_VISION_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("KATHA_VISION_API_KEY_FALLBACK", raising=False)
    monkeypatch.setenv("KATHA_OCR_DISABLED", "1")
    monkeypatch.setattr(httpx, "AsyncClient", _DeadProvider)

    response = TestClient(main.app).post(
        "/verify-strip",
        files={"image": ("strip.jpg", b"\xff\xd8\xff\xe0strip", "image/jpeg")},
        data={"language": "ml"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction_status"] == "manual_required"
    assert body["extraction_source"] == "none"
    assert body["safety"]["verdict"] == "unknown"
    assert body["processed_in_memory"] is True
    assert _DeadProvider.calls >= 1, "the vision tier was never actually tried"
    assert MALAYALAM_REGEX.search(body["safety_message_ml"])
    assert DEVANAGARI_REGEX.search(body["safety_message_hi"])
    assert list(Path(scratch).iterdir()) == [], "the fallback wrote to disk"


def test_the_fallback_adds_no_disk_writes_of_its_own(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    medicine = extraction.resolve_medicine("Augmentn 625", ["Augmentn 625"], 0)
    clinical.analyse([medicine], Language.malayalam, age_years=70)
    kb.catalogue()

    assert list(Path(scratch).iterdir()) == []
