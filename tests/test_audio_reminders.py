"""Dose reminders: schedule parsing, localisation, and the paracetamol ceiling.

What is pinned here:

  * every way an Indian prescription writes a schedule ("1-0-1", "twice daily",
    "every 8 hours") maps to real clock times, and the times match the spacing;
  * ``SOS`` / garbage is refused with a reason instead of a guessed schedule;
  * a schedule that would push paracetamol past 4000 mg/day is refused before
    it can be set — the reminder engine reuses the clinical strengths;
  * the plan is fully translated and speakable in en/ml/hi;
  * nothing is stored: no id, no table, no file, and the response is `no-store`.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import audio_reminders as ar, main
from app.schemas import ManualMedicine, Language

MALAYALAM = re.compile(r"[\u0d00-\u0d7f]")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def request(pattern: str, *names: str, language: Language = Language.malayalam):
    return ar.ReminderRequest(
        medicines=[ManualMedicine(name=name) for name in names],
        pattern=pattern,
        language=language,
    )


def times(pattern: str) -> list[str]:
    schedule, reason = ar.parse_schedule(pattern)
    assert schedule is not None, f"{pattern!r} was refused: {reason}"
    return [time for time, _ in schedule.times]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("1-0-1", ["08:00", "21:00"]),
        ("1 - 0 - 1", ["08:00", "21:00"]),
        ("1/0/1", ["08:00", "21:00"]),
        ("1.0.1", ["08:00", "21:00"]),
        ("0-0-1", ["21:00"]),
        ("1-0-0", ["08:00"]),
        ("0-1-0", ["14:00"]),
        ("1-1-1", ["08:00", "14:00", "21:00"]),
        ("2-0-2", ["08:00", "21:00"]),
        ("every 8 hours", ["08:00", "16:00", "00:00"]),
        ("every 12 hours", ["08:00", "20:00"]),
        ("twice daily", ["09:00", "21:00"]),
        ("BD", ["09:00", "21:00"]),
        ("bid", ["09:00", "21:00"]),
        ("once daily", ["09:00"]),
        ("OD", ["09:00"]),
        ("thrice daily", ["08:00", "14:00", "21:00"]),
        ("TDS", ["08:00", "14:00", "21:00"]),
        ("four times daily", ["08:00", "12:00", "16:00", "20:00"]),
        ("QID", ["08:00", "12:00", "16:00", "20:00"]),
        ("1", ["09:00"]),
    ],
)
def test_every_prescription_shape_maps_to_clock_times(pattern, expected):
    assert times(pattern) == expected


def test_dose_counts_are_per_slot():
    schedule, _ = ar.parse_schedule("2-0-2")

    assert [(time, tablets) for time, tablets in schedule.times] == [
        ("08:00", 2),
        ("21:00", 2),
    ]
    assert schedule.doses_per_day == 4


@pytest.mark.parametrize(
    "pattern,reason",
    [
        ("SOS", "as_needed"),
        ("s.o.s", "as_needed"),
        ("PRN", "as_needed"),
        ("as needed", "as_needed"),
        ("if needed", "as_needed"),
        ("5-0-0", "too_many"),
        ("0-0-9", "too_many"),
        ("0-0-0", "unsupported"),
        ("", "unsupported"),
        ("nonsense", "unsupported"),
        ("every 6 hours", "unsupported"),
        ("take with food", "unsupported"),
        ("-1", "unsupported"),
    ],
)
def test_a_schedule_is_never_guessed(pattern, reason):
    schedule, parsed_reason = ar.parse_schedule(pattern)

    assert schedule is None
    assert parsed_reason == reason


@pytest.mark.parametrize(
    "time,slot",
    [
        ("08:00", "morning"),
        ("11:59", "morning"),
        ("12:00", "afternoon"),
        ("16:59", "afternoon"),
        ("20:00", "evening"),
        ("21:00", "night"),
        ("00:00", "night"),
    ],
)
def test_the_part_of_day_follows_the_clock(time, slot):
    assert ar.slot_for_time(time) == slot


# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------


def test_slots_and_speech_are_fully_localised():
    plan = ar.build_plan(request("2-0-2", "Dolo 650"))

    assert plan.scheduled is True
    assert plan.doses_per_day == 4
    assert [slot.time for slot in plan.slots] == ["08:00", "21:00"]
    for slot in plan.slots:
        assert MALAYALAM.search(slot.label.ml)
        assert DEVANAGARI.search(slot.label.hi)
        assert slot.label.en in {"Morning", "Night"}
        assert "Dolo 650" in slot.speech.en
        assert "08:00" in slot.speech.en or "21:00" in slot.speech.en
        assert MALAYALAM.search(slot.speech.ml)
        assert DEVANAGARI.search(slot.speech.hi)


def test_a_two_tablet_dose_says_two_tablets_in_every_language():
    plan = ar.build_plan(request("2-0-2", "Dolo 650"))

    assert "2 tablets" in plan.slots[0].speech.en
    assert "2 ഗുളിക" in plan.slots[0].speech.ml
    assert "2 गोली" in plan.slots[0].speech.hi


def test_a_single_tablet_uses_the_singular():
    plan = ar.build_plan(request("1-0-1", "Amaryl 1"))

    assert "1 tablet" in plan.slots[0].speech.en
    assert "tablets" not in plan.slots[0].speech.en


def test_the_full_script_has_intro_and_caveat_in_all_three_languages():
    plan = ar.build_plan(request("1-1-1", "Amaryl 1"))

    assert plan.speech is not None
    assert "Dose reminder." in plan.speech.en
    assert "not a prescription" in plan.speech.en.lower()
    assert "ഡോസ് ഓർമ്മപ്പെടുത്തൽ" in plan.speech.ml
    assert "കുറിപ്പടിയല്ല" in plan.speech.ml
    assert "खुराक" in plan.speech.hi
    assert "पर्चा नहीं" in plan.speech.hi
    assert plan.safety_note is not None
    assert MALAYALAM.search(plan.safety_note.ml)
    assert DEVANAGARI.search(plan.safety_note.hi)


def test_the_confirmation_names_the_times():
    plan = ar.build_plan(request("1-0-1", "Amaryl 1"))

    assert "08:00" in plan.message.en and "21:00" in plan.message.en
    assert MALAYALAM.search(plan.message.ml)


@pytest.mark.parametrize(
    "pattern,reason",
    [("SOS", "as_needed"), ("nonsense", "unsupported"), ("9-0-0", "too_many")],
)
def test_a_refusal_is_localised_and_explains_itself(pattern, reason):
    plan = ar.build_plan(request(pattern, "Amaryl 1"))

    assert plan.scheduled is False
    assert plan.reason == reason
    assert plan.slots == []
    assert plan.message is not None
    for lang in ("en", "ml", "hi"):
        assert getattr(plan.message, lang).strip()
    assert MALAYALAM.search(plan.message.ml)
    assert DEVANAGARI.search(plan.message.hi)


def test_the_sos_copy_says_when_to_take_it():
    plan = ar.build_plan(request("SOS", "Dolo 650"))

    assert "doctor" in plan.message.en.lower()
    assert "ഡോക്ടർ" in plan.message.ml


# ---------------------------------------------------------------------------
# Safety: the paracetamol ceiling applies to schedules too
# ---------------------------------------------------------------------------


def test_a_schedule_above_the_paracetamol_ceiling_is_refused():
    # 3 tablets three times a day = 9 x 650 mg = 5850 mg.
    plan = ar.build_plan(request("3-3-3", "Dolo 650"))

    assert plan.scheduled is False
    assert plan.reason == "paracetamol_limit"
    assert "5850" in plan.message.en
    assert "4000" in plan.message.en
    assert MALAYALAM.search(plan.message.ml)


def test_a_schedule_at_the_ceiling_is_allowed():
    # 2 x 650 three times a day = 3900 mg, which is legal.
    plan = ar.build_plan(request("2-2-2", "Dolo 650"))

    assert plan.scheduled is True
    assert plan.doses_per_day == 6


def test_the_ceiling_sums_every_paracetamol_brand_in_the_scan():
    # Two 650 mg paracetamol brands, four times a day = 5200 mg.
    plan = ar.build_plan(request("four times daily", "Dolo 650", "Crocin Cold & Flu"))

    assert plan.scheduled is False, "1300 mg x 4 doses was allowed"
    assert plan.reason == "paracetamol_limit"


def test_a_non_paracetamol_schedule_is_not_touched_by_the_ceiling():
    plan = ar.build_plan(request("1-1-1", "Amaryl 1"))

    assert plan.scheduled is True


def test_an_unknown_medicine_does_not_block_its_own_reminder():
    """No verified strength means no dose arithmetic to do, not a refusal."""
    plan = ar.build_plan(request("1-0-1", "SMUDGED FOIL"))

    assert plan.scheduled is True
    assert "SMUDGED FOIL" in plan.slots[0].speech.en


# ---------------------------------------------------------------------------
# No storage, no identifiers
# ---------------------------------------------------------------------------


def test_the_plan_carries_no_patient_identifier():
    body = ar.build_plan(request("1-0-1", "Amaryl 1")).model_dump()

    serialised = json.dumps(body)
    assert "scan_id" not in serialised
    assert "patient" not in serialised.lower()
    assert body["processed_in_memory"] is True


def test_the_plan_is_deterministic():
    first = ar.build_plan(request("1-0-1", "Amaryl 1")).model_dump()
    second = ar.build_plan(request("1-0-1", "Amaryl 1")).model_dump()

    assert first == second


def test_building_a_plan_writes_nothing_to_disk(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    ar.build_plan(request("1-1-1", "Dolo 650"))
    ar.build_plan(request("SOS", "Dolo 650"))

    assert list(Path(scratch).iterdir()) == []


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def post(payload: dict):
    return TestClient(main.app).post("/reminders", json=payload)


def test_the_endpoint_returns_a_schedulable_plan():
    response = post(
        {
            "medicines": [{"name": "Amaryl 1"}],
            "pattern": "1-0-1",
            "language": "ml",
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scheduled"] is True
    assert body["doses_per_day"] == 2
    assert [slot["time"] for slot in body["slots"]] == ["08:00", "21:00"]
    assert MALAYALAM.search(body["speech"]["ml"])
    assert body["processed_in_memory"] is True
    # Reminders are health data: never cached by any intermediary.
    assert "no-store" in response.headers["cache-control"]


def test_the_endpoint_refuses_sos_with_a_reason():
    body = post(
        {"medicines": [{"name": "Dolo 650"}], "pattern": "SOS", "language": "en"}
    ).json()

    assert body["scheduled"] is False
    assert body["reason"] == "as_needed"
    assert body["slots"] == []
    assert "doctor" in body["message"]["en"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"medicines": [], "pattern": "1-0-1"},
        {"medicines": [{"name": "Dolo 650"}]},
        {"medicines": [{"name": "Dolo 650"}], "pattern": "1-0-1", "extra": 1},
        {"medicines": [{"name": "Dolo 650"}], "pattern": "x" * 41},
        {"medicines": [{"name": "<script>"}], "pattern": "1-0-1"},
    ],
)
def test_the_endpoint_rejects_an_invalid_request(payload):
    assert post(payload).status_code == 422


def test_the_endpoint_rejects_an_unknown_language():
    response = post(
        {"medicines": [{"name": "Dolo 650"}], "pattern": "1-0-1", "language": "zz"}
    )
    assert response.status_code == 422
