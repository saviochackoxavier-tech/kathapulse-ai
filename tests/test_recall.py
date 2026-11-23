"""Batch, recall and expiry audit: the box-level guardrail.

The clinical rules ask "is this combination dangerous?".  These tests are about
the other question -- "is this *box* still fit to hand over?" -- and pin:

  * every expiry shape an Indian foil actually prints, and the shapes it must
    refuse (an unreadable date is never silently "fine");
  * the recall match: right molecule or brand family, right batch prefix, and
    nothing matched without the printed batch;
  * cold-chain products, which a photo can never clear;
  * localised copy in English, Malayalam and Hindi, and a speech script that
    carries the recall warning;
  * the API contract (`batch_no` / `expiry` in, findings + flags out) and its
    input validation;
  * the audit itself: deterministic, date-injectable, and writing nothing.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clinical, extraction, main, recall
from app.schemas import Language, ScannedMedicine, Severity, Verdict

TODAY = date(2026, 11, 23)
MALAYALAM = re.compile(r"[\u0d00-\u0d7f]")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")

RECALL_CODES = {"RECALLED_BATCH"}
EXPIRY_CODES = {"EXPIRED_STOCK", "EXPIRY_SOON", "EXPIRY_UNREADABLE"}


def medicine(label: str, batch: str = "", expiry: str = "") -> ScannedMedicine:
    return extraction.resolve_medicine(label, [label], 0, batch_no=batch, expiry=expiry)


def codes(medicines, as_of: date = TODAY) -> list[str]:
    return [f.code for f in recall.audit(medicines, as_of)]


# ---------------------------------------------------------------------------
# Expiry parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "printed",
    [
        "04/2026",
        "4/2026",
        "04-2026",
        "04.2026",
        "2026-04",
        "04/26",
        "APR 2026",
        "APR26",
        "APRIL 26",
        "EXP 04/2026",
        "EXP: 04/2026",
        "EXP. 04/26",
        "USE BEFORE 04/2026",
        "expiry apr 2026",
        "  04 / 2026  ",
    ],
)
def test_every_printed_expiry_shape_is_understood(printed):
    assert recall.parse_expiry(printed) == (2026, 4)


@pytest.mark.parametrize(
    "printed",
    ["", "   ", "see box", "not visible", "13/2026", "00/26", "04/1999", "2026/13", "APR"],
)
def test_an_unreadable_expiry_is_refused_not_assumed(printed):
    assert recall.parse_expiry(printed) is None


def test_display_expiry_prints_the_way_the_foil_does():
    assert recall.display_expiry((2026, 4)) == "04/2026"
    assert recall.display_expiry((2027, 12)) == "12/2027"


def test_months_until_counts_calendar_months():
    assert recall.months_until((2026, 11), TODAY) == 0
    assert recall.months_until((2026, 12), TODAY) == 1
    assert recall.months_until((2026, 10), TODAY) == -1
    assert recall.months_until((2027, 11), TODAY) == 12


# ---------------------------------------------------------------------------
# Expiry findings
# ---------------------------------------------------------------------------


def test_expired_stock_is_critical():
    findings = recall.audit([medicine("Dolo 650", expiry="09/2026")], TODAY)

    assert [f.code for f in findings] == ["EXPIRED_STOCK"]
    assert findings[0].severity == Severity.critical
    assert "09/2026" in findings[0].message.en
    assert "Dolo 650" in findings[0].message.en


@pytest.mark.parametrize("expiry", ["11/2026", "12/2026", "NOV 2026", "11/26"])
def test_expiry_this_month_or_next_month_is_a_warning(expiry):
    findings = recall.audit([medicine("Dolo 650", expiry=expiry)], TODAY)

    assert [f.code for f in findings] == ["EXPIRY_SOON"]
    assert findings[0].severity == Severity.warning


def test_a_batch_with_time_left_is_silent():
    assert recall.audit([medicine("Dolo 650", expiry="04/2028")], TODAY) == []


def test_an_unreadable_expiry_is_surfaced_not_dropped():
    findings = recall.audit([medicine("Dolo 650", expiry="not visible")], TODAY)

    assert [f.code for f in findings] == ["EXPIRY_UNREADABLE"]
    assert findings[0].severity == Severity.warning
    assert "Dolo 650" in findings[0].message.en


def test_no_printed_expiry_means_no_expiry_claim():
    assert recall.audit([medicine("Dolo 650")], TODAY) == []


# ---------------------------------------------------------------------------
# Recall matching
# ---------------------------------------------------------------------------


def test_a_recalled_batch_matches_on_molecule_and_prefix():
    findings = recall.audit([medicine("Glycomet 500", batch="GM2407A")], TODAY)

    assert [f.code for f in findings] == ["RECALLED_BATCH"]
    assert findings[0].severity == Severity.critical
    message = findings[0].message.en
    assert "GM2407A" in message
    assert "NDMA" in message
    assert findings[0].anchors == ["metformin"]


def test_batch_matching_ignores_case_and_separators():
    for printed in ("gm2407a", "GM 2407 A", "gm-2407/A"):
        assert codes([medicine("Glycomet 500", batch=printed)]) == ["RECALLED_BATCH"]


def test_a_clean_batch_of_a_recalled_product_is_not_flagged():
    assert codes([medicine("Glycomet 500", batch="GM2501B")]) == []


def test_a_recalled_product_without_a_batch_is_not_flagged():
    """No batch read means no claim: the audit never guesses a lot number."""
    assert codes([medicine("Glycomet 500")]) == []


def test_a_recall_on_another_product_does_not_follow_the_batch():
    # GM24 is a metformin prefix; a Dolo strip carrying it is not recalled.
    assert codes([medicine("Dolo 650", batch="GM2407A")]) == []


def test_the_paracetamol_notice_matches_its_own_brand_family():
    assert codes([medicine("Crocin Cold & Flu", batch="CP2409")]) == ["RECALLED_BATCH"]


def test_a_recalled_batch_makes_the_verdict_critical():
    report = clinical.analyse(
        [medicine("Glycomet 500", batch="GM2407A")],
        Language.malayalam,
        as_of=TODAY,
    )

    assert report.verdict == Verdict.critical
    assert "RECALLED_BATCH" in {f.code for f in report.findings}


def test_the_audit_is_independent_of_the_combination_rules():
    """A single, otherwise safe strip is still stopped by its batch."""
    report = clinical.analyse(
        [medicine("Dolo 650", expiry="01/2026")], Language.english, as_of=TODAY
    )
    found = {f.code for f in report.findings}
    assert found == {"EXPIRED_STOCK"}, "an expired box must not also read as safe"
    assert report.verdict == Verdict.critical


# ---------------------------------------------------------------------------
# Cold chain
# ---------------------------------------------------------------------------


def test_a_cold_chain_product_is_flagged_even_without_a_batch():
    findings = recall.audit([medicine("Human Insulin 100 IU")], TODAY)

    assert [f.code for f in findings] == ["COLD_CHAIN_RISK"]
    assert findings[0].severity == Severity.warning
    assert "2 °C" in findings[0].message.en


def test_an_ordinary_tablet_is_not_a_cold_chain_product():
    assert codes([medicine("Dolo 650")]) == []


# ---------------------------------------------------------------------------
# Copy, speech, duplicates
# ---------------------------------------------------------------------------


def test_every_audit_finding_is_written_in_all_three_languages():
    findings = recall.audit(
        [
            medicine("Glycomet 500", batch="GM2407A", expiry="09/2026"),
            medicine("Human Insulin 100 IU"),
        ],
        TODAY,
    )

    assert {f.code for f in findings} >= {"RECALLED_BATCH", "EXPIRED_STOCK", "COLD_CHAIN_RISK"}
    for finding in findings:
        assert MALAYALAM.search(finding.message.ml), finding.code
        assert DEVANAGARI.search(finding.message.hi), finding.code
        assert MALAYALAM.search(finding.title.ml), finding.code
        assert DEVANAGARI.search(finding.title.hi), finding.code
        assert finding.action.en and finding.action.ml and finding.action.hi


def test_the_speech_script_carries_the_recall_warning_in_both_languages():
    report = clinical.analyse(
        [medicine("Glycomet 500", batch="GM2407A", expiry="09/2026")],
        Language.malayalam,
        as_of=TODAY,
    )
    ml = clinical.build_speech(report.findings, Language.malayalam).text
    hi = clinical.build_speech(report.findings, Language.hindi).text

    assert MALAYALAM.search(ml)
    assert DEVANAGARI.search(hi)
    assert "GM2407A" in ml
    assert "GM2407A" in hi
    # Both findings are critical and keep their order: the recall is spoken
    # before the expiry it was scanned with.
    assert ml.index("GM2407A") < ml.index("09/2026")


def test_the_same_box_scanned_twice_does_not_double_the_banner():
    box = medicine("Glycomet 500", batch="GM2407A", expiry="09/2026")

    findings = recall.audit([box, box], TODAY)

    assert [f.code for f in findings] == ["RECALLED_BATCH", "EXPIRED_STOCK"]


def test_the_audit_is_deterministic_and_date_injectable():
    box = [medicine("Dolo 650", expiry="01/2027")]

    first = [f.model_dump() for f in recall.audit(box, date(2026, 11, 23))]
    second = [f.model_dump() for f in recall.audit(box, date(2026, 11, 23))]
    later = recall.audit(box, date(2027, 2, 1))

    assert first == second, "the audit is not deterministic"
    assert first == [], "a 01/2027 expiry is fine in November 2026"
    assert [f.code for f in later] == ["EXPIRED_STOCK"]


def test_the_audit_writes_nothing_to_disk(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    recall.audit(
        [medicine("Glycomet 500", batch="GM2407A", expiry="09/2026")], TODAY
    )

    assert list(Path(scratch).iterdir()) == []


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def post(payload: dict):
    return TestClient(main.app).post("/verify-medicines", json=payload)


def test_api_returns_the_recall_and_expiry_flags():
    response = post(
        {
            "medicines": [
                {"name": "Glycomet 500", "batch_no": "GM2407A", "expiry": "09/2026"}
            ],
            "language": "ml",
        }
    )

    assert response.status_code == 200
    body = response.json()
    found = {f["code"] for f in body["safety"]["findings"]}
    assert {"RECALLED_BATCH", "EXPIRED_STOCK"} <= found
    assert body["recall_warning"] is True
    assert body["expiry_warning"] is True
    assert body["processed_in_memory"] is True
    assert body["medicines"][0]["batch_no"] == "GM2407A"
    assert body["medicines"][0]["expiry"] == "09/2026"
    assert MALAYALAM.search(body["safety_message_ml"])
    assert DEVANAGARI.search(body["safety_message_hi"])


def test_api_without_batch_or_expiry_is_unchanged():
    response = post({"medicines": [{"name": "Dolo 650"}], "language": "en"})

    body = response.json()
    found = {f["code"] for f in body["safety"]["findings"]}
    assert not found & (RECALL_CODES | EXPIRY_CODES | {"COLD_CHAIN_RISK"})
    assert body["recall_warning"] is False
    assert body["expiry_warning"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("batch_no", "<script>alert(1)</script>"),
        ("expiry", "04/2026; DROP TABLE"),
        ("batch_no", "A" * 40),
        ("expiry", "1" * 30),
    ],
)
def test_api_rejects_junk_batch_and_expiry(field, value):
    response = post({"medicines": [{"name": "Dolo 650", field: value}], "language": "en"})

    assert response.status_code == 422


def test_health_reports_the_pilot_recall_feed_size():
    body = TestClient(main.app).get("/health").json()

    assert body["recall_notices"] == len(recall.RECALLS) > 0
    assert "PILOT-RCL" not in json.dumps(body), "the feed body leaked into /health"
