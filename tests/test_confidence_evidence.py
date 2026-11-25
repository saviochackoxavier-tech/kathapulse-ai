"""Pass 33 — confidence gating, explainable identification and disclaimers.

Three behaviours are pinned here, each of which could silently degrade into a
confident-sounding guess:

* a **low**-confidence read is refused before matching, never mapped;
* a **medium** read resolves but is marked for a retake, and the evidence card
  reports it as unverified;
* the evidence card only says "matched" for facts that were actually read
  (name, printed/combo strength), and names the database + review date behind
  "verified".

The pharmacovigilance caveat is checked on both the single-scan and the batch
contract, because the batch endpoint is the one a pharmacist reads.
"""

from __future__ import annotations

import asyncio
import io

from fastapi.testclient import TestClient

from app import extraction, knowledge_base, main


client = TestClient(main.app)


def jpeg_bytes(size: int = 512) -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


def _read(label: str, names: list[str], confidence: str) -> extraction._Read:
    return extraction._Read(label, names, "", "", confidence)


# ---------------------------------------------------------------------------
# Resolution-level confidence
# ---------------------------------------------------------------------------


def test_low_confidence_read_is_refused_before_any_matching():
    medicine = extraction.resolve_medicine(
        "Dolo 650", ["Dolo 650"], 0, confidence="low"
    )
    assert medicine.matched is False
    assert medicine.ingredients == []
    assert medicine.rejection == "low_confidence"
    assert medicine.confidence == "low"
    assert medicine.verified_by == ""


def test_medium_confidence_keeps_the_candidate_but_asks_for_a_retake():
    medicine = extraction.resolve_medicine(
        "Dolo 650", ["Dolo 650"], 0, confidence="medium"
    )
    assert medicine.matched is True  # the text really is on the foil
    assert medicine.recapture is True
    assert medicine.confidence == "medium"
    assert medicine.rejection == ""


def test_unreported_confidence_neither_boosts_nor_rejects():
    medicine = extraction.resolve_medicine("Dolo 650", ["Dolo 650"], 0)
    assert medicine.matched is True
    assert medicine.recapture is False
    assert medicine.confidence == ""
    assert medicine.rejection == ""


def test_wording_that_is_not_a_level_is_treated_as_unreported():
    medicine = extraction.resolve_medicine(
        "Dolo 650", ["Dolo 650"], 0, confidence="pretty sure"
    )
    assert medicine.confidence == ""
    assert medicine.matched is True
    assert medicine.recapture is False


# ---------------------------------------------------------------------------
# Strength provenance
# ---------------------------------------------------------------------------


def test_printed_strength_counts_as_matched_and_default_does_not():
    printed = extraction.resolve_medicine("Dolo 650", ["Dolo 650"], 0)
    assert printed.strength_source == "printed"
    row = main._evidence([printed])[0]
    assert row.name_status == "matched"
    assert row.strength_status == "matched"

    # A bare molecule has no printed strength; only the catalogue default.
    defaulted = extraction.resolve_medicine("Paracetamol", ["Paracetamol"], 0)
    assert defaulted.matched is True
    assert defaulted.strength_source == "default"
    row = main._evidence([defaulted])[0]
    assert row.name_status == "matched"
    assert row.strength_status == "unverified"  # never presented as camera-read


def test_combination_brand_strengths_come_from_the_brand_record():
    medicine = extraction.resolve_medicine("Telma-H 40/12.5", ["Telma-H"], 0)
    assert medicine.strength_source == "combo"
    assert main._evidence([medicine])[0].strength_status == "matched"


# ---------------------------------------------------------------------------
# The evidence card itself
# ---------------------------------------------------------------------------


def test_evidence_names_the_database_and_the_review_date():
    medicine = extraction.resolve_medicine("Glycomet GP", ["Glycomet GP"], 0)
    row = main._evidence([medicine])[0]
    assert row.ingredient_status == "verified"
    assert row.source == "ground_truth"
    assert row.verified_on == knowledge_base.CATALOGUE_VERIFIED_ON
    assert knowledge_base.CATALOGUE_VERIFIED_ON[:2] == "20"


def test_evidence_never_verifies_an_unrecognised_label():
    medicine = extraction.resolve_medicine("SMUDGED FOIL", ["SMUDGED FOIL"], 0)
    row = main._evidence([medicine])[0]
    assert (row.name_status, row.strength_status, row.ingredient_status) == (
        "unverified",
        "unverified",
        "unverified",
    )
    assert (row.source, row.verified_on) == ("", "")


def test_evidence_reports_a_medium_read_as_unverified():
    medicine = extraction.resolve_medicine(
        "Dolo 650", ["Dolo 650"], 0, confidence="medium"
    )
    row = main._evidence([medicine])[0]
    assert row.name_status == "unverified"
    assert row.strength_status == "unverified"
    assert row.ingredient_status == "unverified"
    assert row.source == ""


# ---------------------------------------------------------------------------
# Tier wiring
# ---------------------------------------------------------------------------


def test_vision_prompt_asks_for_confidence_and_rejects_low(monkeypatch):
    assert "confidence" in extraction._VISION_PROMPT

    async def fake_vision(image_bytes: bytes, content_type: str):
        return [_read("Dolo 650", ["Dolo 650"], "low")]

    monkeypatch.setattr(extraction, "_vision_extract", fake_vision)
    result = asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert result.status == "manual_required"
    assert result.medicines[0].rejection == "low_confidence"


def test_vision_medium_read_is_ok_but_flagged_for_recapture(monkeypatch):
    async def fake_vision(image_bytes: bytes, content_type: str):
        return [_read("Dolo 650", ["Dolo 650"], "medium")]

    monkeypatch.setattr(extraction, "_vision_extract", fake_vision)
    result = asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert result.status == "ok"
    assert result.medicines[0].recapture is True


def test_ocr_confidence_is_high_only_for_an_exact_catalogue_hit():
    assert extraction._ocr_confidence("DOLO 650") == "high"
    # Not in the catalogue: never promoted, so the UI asks for a retake.
    assert extraction._ocr_confidence("Zzqx 10") == "medium"


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------


def test_verify_medicines_returns_evidence_and_disclaimer():
    response = client.post(
        "/verify-medicines",
        json={"medicines": [{"name": "Dolo 650"}], "language": "ml"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["recapture_required"] is False
    assert body["low_confidence_rejected"] is False
    row = body["evidence"][0]
    assert row["label"] == "Dolo 650"
    assert row["name_status"] == "matched"
    assert row["strength_status"] == "matched"
    assert row["ingredient_status"] == "verified"
    assert row["source"] == "taxonomy"
    assert row["verified_on"] == knowledge_base.CATALOGUE_VERIFIED_ON

    caveat = body["batch_disclaimer"]
    assert set(caveat) == {"en", "ml", "hi"}
    assert "not guaranteed" in caveat["en"]
    assert "quality defects" in caveat["en"]
    assert caveat["ml"] and caveat["hi"]


def test_low_confidence_strip_is_rejected_with_a_retake_signal(monkeypatch):
    async def fake_extract(image_bytes: bytes, content_type: str):
        return extraction.Extraction(
            medicines=[extraction.resolve_medicine(
                "Dolo 650", ["Dolo 650"], 0, confidence="low"
            )],
            source=extraction.ExtractionSource.vision,
            status="manual_required",
        )

    monkeypatch.setattr(main.extraction, "extract", fake_extract)
    response = client.post(
        "/verify-strip",
        files={"image": ("strip.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")},
        data={"language": "hi"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["extraction_status"] == "manual_required"
    assert body["low_confidence_rejected"] is True
    assert body["recapture_required"] is True
    assert body["evidence"][0]["ingredient_status"] == "unverified"
    assert body["medicines"][0]["matched"] is False


def test_medium_confidence_strip_prompts_recapture(monkeypatch):
    async def fake_extract(image_bytes: bytes, content_type: str):
        return extraction.Extraction(
            medicines=[extraction.resolve_medicine(
                "Dolo 650", ["Dolo 650"], 0, confidence="medium"
            )],
            source=extraction.ExtractionSource.vision,
            status="ok",
        )

    monkeypatch.setattr(main.extraction, "extract", fake_extract)
    response = client.post(
        "/verify-strip",
        files={"image": ("strip.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")},
        data={"language": "en"},
    )
    body = response.json()
    assert body["recapture_required"] is True
    assert body["low_confidence_rejected"] is False
    assert body["evidence"][0]["name_status"] == "unverified"


def test_batch_output_carries_the_pharmacovigilance_caveat():
    response = client.post(
        "/verify-strips/batch",
        files=[
            ("strips", ("a.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")),
            ("strips", ("b.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")),
        ],
        data={"language": "ml"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["strip_count"] == 2
    assert set(body["batch_disclaimer"]) == {"en", "ml", "hi"}
    assert "not guaranteed" in body["batch_disclaimer"]["en"]
