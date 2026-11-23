"""Dose-schedule parsing and localised reminder plans.

The pharmacist (or the patient) writes the schedule the way Indian prescriptions
do — ``1-0-1``, ``twice daily``, ``every 8 hours``, ``SOS``. This module turns
that into something a phone can act on: a list of clock times, each with a
localised sentence to speak and a dose count.

What this module deliberately does **not** do
---------------------------------------------
* **No storage.** A plan is derived data returned to the client. There is no
  table, no file, no session, no reminder id — the server forgets the plan the
  moment the response is written. The browser holds it in memory for the life of
  the tab.
* **No push service.** Nothing here can wake a closed tab; a web page cannot do
  that honestly. The UI says "keep this page open" instead of pretending.
* **No invented schedule.** ``SOS`` / "as needed" is refused with a reason, and
  garbage is refused with a reason. A reminder for the wrong time is a safety
  bug, not a UX gap.

One safety rule rides along: a schedule that would push paracetamol past the
4000 mg daily ceiling is refused *before* it can be scheduled, using the same
strengths the clinical engine already resolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import clinical, i18n
from .schemas import MAX_MEDICINES_PER_SCAN, Language, LanguageText, ManualMedicine

# The paracetamol ceiling is owned by ``app.clinical`` -- the rules module the
# rest of the app trusts -- so a reminder can never disagree with a finding.

#: Hard cap on tablets in one slot; anything above is almost certainly a typo.
MAX_TABLETS_PER_DOSE = 4

#: Canonical times per number of doses. Indian OPD habits: 1 = morning,
#: 2 = morning + night, 3 = morning/afternoon/night, 4 = four-hourly daylight.
_SLOT_TIMES: dict[int, tuple[str, ...]] = {
    1: ("09:00",),
    2: ("09:00", "21:00"),
    3: ("08:00", "14:00", "21:00"),
    4: ("08:00", "12:00", "16:00", "20:00"),
}

#: A triple pattern is read as morning / afternoon / night, the same clock as a
#: worded "thrice daily" so the two spellings cannot drift apart.
_TRIPLE_TIMES = _SLOT_TIMES[3]

_TRIPLE = re.compile(r"^\s*(\d)\s*[-/., ]\s*(\d)\s*[-/., ]\s*(\d)\s*$")
_EVERY_HOURS = re.compile(r"every\s*(\d{1,2})\s*(?:hours?|hrs?|h)\b", re.IGNORECASE)
_TIMES_WORD = (
    (re.compile(r"\b(four times?|4 times?|qid|qds)\b"), 4),
    (re.compile(r"\b(three times?|3 times?|thrice|tds|tid)\b"), 3),
    (re.compile(r"\b(two times?|2 times?|twice|bd|bid)\b"), 2),
    (re.compile(r"\b(once|one time|1 time|od)\b"), 1),
)
_AS_NEEDED = re.compile(
    r"\b(sos|s\.o\.s|prn|as needed|if needed|when needed|as required)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class ReminderRequest(BaseModel):
    """A schedule request built from an already-verified scan."""

    model_config = ConfigDict(extra="forbid")

    medicines: list[ManualMedicine] = Field(
        min_length=1, max_length=MAX_MEDICINES_PER_SCAN
    )
    #: What the prescription says: ``1-0-1``, ``twice daily``, ``every 8 hours``.
    pattern: str = Field(min_length=1, max_length=40, examples=["1-0-1"])
    language: Language = Language.malayalam


class ReminderSlot(BaseModel):
    """One dose: when, how much, and what to say in each language."""

    time: str = Field(description="24-hour local time, HH:MM")
    slot: Literal["morning", "afternoon", "evening", "night"]
    tablets: int
    label: LanguageText
    speech: LanguageText


class ReminderResponse(BaseModel):
    """A plan the browser can schedule, or the reason it cannot be scheduled."""

    scheduled: bool
    #: "" when scheduled; otherwise as_needed | unsupported | too_many |
    #: paracetamol_limit.
    reason: str = ""
    doses_per_day: int = 0
    slots: list[ReminderSlot] = Field(default_factory=list)
    #: Full localised script for the first reminder (all slots, then the caveat).
    speech: LanguageText | None = None
    safety_note: LanguageText | None = None
    message: LanguageText | None = None
    processed_in_memory: Literal[True] = True


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """Parsed schedule: one ``(hh:mm, tablets)`` pair per dose."""

    times: tuple[tuple[str, int], ...]

    @property
    def doses_per_day(self) -> int:
        return sum(tablets for _, tablets in self.times)


def parse_schedule(pattern: str) -> tuple[Schedule | None, str]:
    """Parse a printed dosing instruction.

    Returns ``(schedule, "")`` on success, or ``(None, reason)`` where reason is
    ``as_needed`` / ``unsupported`` / ``too_many``. The caller turns the reason
    into localised copy; no schedule is ever guessed.
    """
    text = " ".join(str(pattern or "").lower().split())
    if not text:
        return None, "unsupported"

    if _AS_NEEDED.search(text):
        return None, "as_needed"

    triple = _TRIPLE.match(text)
    if triple:
        counts = [int(part) for part in triple.groups()]
        if any(count > MAX_TABLETS_PER_DOSE for count in counts):
            return None, "too_many"
        pairs = tuple(
            (time, count)
            for time, count in zip(_TRIPLE_TIMES, counts)
            if count > 0
        )
        if not pairs:
            return None, "unsupported"  # "0-0-0" is not a schedule
        return Schedule(times=pairs), ""

    every = _EVERY_HOURS.search(text)
    if every:
        hours = int(every.group(1))
        if hours not in (8, 12):
            return None, "unsupported"
        # Space the doses by the number printed, starting from 08:00: "every 8
        # hours" must be 08/16/00, not three times spread over the day.
        count = 24 // hours
        times = tuple(
            f"{(8 + step * hours) % 24:02d}:00" for step in range(count)
        )
        return Schedule(times=tuple((time, 1) for time in times)), ""

    for pattern_re, count in _TIMES_WORD:
        if pattern_re.search(text):
            return Schedule(times=tuple((t, 1) for t in _SLOT_TIMES[count])), ""

    single = re.fullmatch(r"\s*(\d)\s*", text)
    if single:
        count = int(single.group(1))
        if count < 1:
            return None, "unsupported"
        if count > MAX_TABLETS_PER_DOSE:
            return None, "too_many"
        return Schedule(times=(("09:00", count),)), ""

    return None, "unsupported"


def slot_for_time(time: str) -> str:
    hour = int(time.split(":", 1)[0])
    if hour < 5:
        # A midnight or 04:00 dose from "every 8 hours" is still the night dose.
        return "night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


# ---------------------------------------------------------------------------
# Localisation helpers
# ---------------------------------------------------------------------------


def _amount(tablets: int, lang: str) -> str:
    key = "reminder.units.one" if tablets == 1 else "reminder.units.many"
    return i18n.t(key, lang, count=tablets)


def _medicine_names(medicines: list[ManualMedicine]) -> str:
    """Printed names, joined for speech: what the patient will recognise."""
    names = [m.name.strip() for m in medicines if m.name.strip()]
    return " + ".join(names[:4])


def _daily_paracetamol_mg(
    medicines: list[ManualMedicine], doses_per_day: int
) -> float:
    """Daily paracetamol for this schedule, from the resolved strengths."""
    from . import extraction  # local import keeps this module import-light

    total = 0.0
    for index, item in enumerate(medicines):
        medicine = extraction.resolve_medicine(item.name, [item.name], index)
        strength = sum(
            ingredient.strength_mg or 0.0
            for ingredient in medicine.ingredients
            if ingredient.canonical == clinical.PARACETAMOL_CANONICAL
        )
        total += strength * doses_per_day
    return total


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def build_plan(request: ReminderRequest) -> ReminderResponse:
    """Turn a request into a schedulable plan, or a localised refusal."""
    schedule, reason = parse_schedule(request.pattern)

    if schedule is None:
        key = {
            "as_needed": "reminder.as_needed",
            "too_many": "reminder.too_many",
            "paracetamol_limit": "reminder.paracetamol_limit",
        }.get(reason, "reminder.unsupported")
        return ReminderResponse(
            scheduled=False,
            reason=reason,
            message=i18n.language_text(key),
            safety_note=i18n.language_text("reminder.safety"),
        )

    paracetamol_mg = _daily_paracetamol_mg(request.medicines, schedule.doses_per_day)
    if paracetamol_mg > clinical.PARACETAMOL_DAILY_MAX_MG:
        return ReminderResponse(
            scheduled=False,
            reason="paracetamol_limit",
            message=i18n.language_text(
                "reminder.paracetamol_limit", total=round(paracetamol_mg)
            ),
            safety_note=i18n.language_text("reminder.safety"),
        )

    names_by_lang = _medicine_names(request.medicines)
    slots: list[ReminderSlot] = []
    sentences: dict[str, list[str]] = {"en": [], "ml": [], "hi": []}

    for time, tablets in schedule.times:
        slot = slot_for_time(time)
        label = i18n.language_text(f"reminder.slot.{slot}")
        speech = LanguageText(
            **{
                lang: i18n.t(
                    "reminder.dose",
                    lang,
                    time=time,
                    medicines=names_by_lang,
                    amount=_amount(tablets, lang),
                )
                for lang in ("en", "ml", "hi")
            }
        )
        slots.append(
            ReminderSlot(
                time=time, slot=slot, tablets=tablets, label=label, speech=speech
            )
        )
        for lang in ("en", "ml", "hi"):
            sentences[lang].append(getattr(speech, lang))

    script = LanguageText(
        **{
            lang: " ".join(
                [
                    i18n.t("reminder.intro", lang),
                    *sentences[lang],
                    i18n.t("reminder.safety", lang),
                ]
            )
            for lang in ("en", "ml", "hi")
        }
    )

    return ReminderResponse(
        scheduled=True,
        doses_per_day=schedule.doses_per_day,
        slots=slots,
        speech=script,
        safety_note=i18n.language_text("reminder.safety"),
        message=i18n.language_text(
            "reminder.scheduled", times=", ".join(time for time, _ in schedule.times)
        ),
    )
