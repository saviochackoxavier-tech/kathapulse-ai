"""Batch, recall and expiry audit for shelf stock.

The clinical engine answers "is this *combination* dangerous?".  This module
answers the question a pharmacy actually asks across the counter: "is this
*box* still fit to hand over?"   Three signals, all offline and deterministic:

1. **Recall match** -- the printed batch number falls inside a field-safety
   notice for that molecule or brand family.
2. **Expiry** -- the printed expiry month is past, close enough that a long
   course would run past it, or unreadable (which is not the same as "fine").
3. **Cold chain** -- the product needs 2-8 degrees C, something a photograph
   can never confirm, so the pharmacist is pointed at the fridge log.

Honesty about the data
----------------------
``RECALLS`` ships **with the app** as a small curated pilot list.  It is not a
live CDSCO feed, and the ``ref`` values are local trace labels rather than
regulatory citations.  A real deployment replaces this tuple with a signed feed;
until then the wording says "recall list", never "government recall".  A
feature that looks bigger than its data would be worse than no feature.

Everything here is a pure function over already-validated values: no network,
no filesystem, no clock beyond the ``as_of`` the caller passes in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from . import i18n, taxonomy
from .schemas import Finding, LanguageText, ScannedMedicine, Severity

#: A printed expiry this many months away still counts as "running out".
#: One month means: this month, or next month.
EXPIRY_WINDOW_MONTHS = 1

#: Products that must travel and sit at 2-8 degrees C.  Matched against the
#: printed label, because none of these are in the oral-solid taxonomy.
COLD_CHAIN_TERMS: tuple[str, ...] = (
    "insulin",
    "oxytocin",
    "vaccine",
    "toxoid",
    "tetanus",
    "hepatitis b",
    "epinephrine",
    "adrenaline",
)

_MONTH_NAMES = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}

#: Leading words printers put before the date ("EXP 04/2026", "USE BEFORE ...").
_EXPIRY_PREFIX = re.compile(
    r"^(?:EXP(?:IRY|IRES|IRE)?|USE\s*BEFORE|BEST\s*BEFORE|Mfg\.?\s*Exp)\s*[:.\-]?\s*",
)

_YEAR_FIRST = re.compile(r"^(\d{4})\s*[/\-.]\s*(\d{1,2})$")
_MONTH_FIRST = re.compile(r"^(\d{1,2})\s*[/\-.]\s*(\d{2,4})$")
_MONTH_NAME = re.compile(r"^([A-Z]{3,9})\s*[/\-.]?\s*(\d{2,4})$")


# ---------------------------------------------------------------------------
# The pilot recall feed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecallAlert:
    """One field-safety notice, reduced to what a scanned label can match."""

    ref: str
    molecule: str
    brand_tokens: tuple[str, ...]
    batch_prefixes: tuple[str, ...]
    #: Key into ``i18n.TEXTS`` ending in ``.reason.<key>``.
    reason: str

    def matches_drug(self, canonicals: set[str], label: str) -> bool:
        """True when this notice is about the product in the user's hand."""
        if self.molecule and self.molecule in canonicals:
            return True
        token = taxonomy.brand_token(label)
        return bool(token) and token in self.brand_tokens


RECALLS: tuple[RecallAlert, ...] = (
    RecallAlert(
        ref="PILOT-RCL-01",
        molecule="metformin",
        brand_tokens=("glycomet", "glucophage", "metformin"),
        batch_prefixes=("GM24", "GP24"),
        reason="impurity",
    ),
    RecallAlert(
        ref="PILOT-RCL-02",
        molecule="telmisartan",
        brand_tokens=("telma", "telsartan"),
        batch_prefixes=("TL24",),
        reason="potency",
    ),
    RecallAlert(
        ref="PILOT-RCL-03",
        molecule="paracetamol",
        brand_tokens=("dolo", "calpol", "crocin"),
        batch_prefixes=("DL24", "CP24"),
        reason="dissolution",
    ),
    RecallAlert(
        ref="PILOT-RCL-04",
        molecule="pantoprazole",
        brand_tokens=("pan", "pantop", "pan-d"),
        batch_prefixes=("PN24",),
        reason="labelling",
    ),
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def normalise_batch(raw: str) -> str:
    """Uppercase, whitespace- and separator-free batch number (``gm 2407/a``)."""
    return re.sub(r"[\s\-/._]", "", str(raw or "").upper())[:24]


def parse_expiry(raw: str) -> tuple[int, int] | None:
    """Read a printed expiry into ``(year, month)``, or ``None`` if unreadable.

    Accepts the shapes Indian foils actually use: ``04/2026``, ``4/26``,
    ``04-2026``, ``2026-04``, ``APR 2026``, ``APR26``, with or without a leading
    ``EXP``/``USE BEFORE``.  ``None`` is returned for anything else -- the caller
    surfaces that as "not readable" rather than assuming the box is fine.
    """
    text = " ".join(str(raw or "").upper().split())
    if not text:
        return None
    text = _EXPIRY_PREFIX.sub("", text).strip(" .:-")

    year_first = _YEAR_FIRST.match(text)
    if year_first:
        return _validate(int(year_first.group(1)), int(year_first.group(2)))

    named = _MONTH_NAME.match(text)
    if named and named.group(1) in _MONTH_NAMES:
        return _validate(_expand_year(named.group(2)), _MONTH_NAMES[named.group(1)])

    month_first = _MONTH_FIRST.match(text)
    if month_first:
        return _validate(_expand_year(month_first.group(2)), int(month_first.group(1)))

    return None


def _expand_year(raw: str) -> int:
    """``26`` -> 2026; a four-digit year is taken as printed."""
    value = int(raw)
    return value + 2000 if value < 100 else value


def _validate(year: int, month: int) -> tuple[int, int] | None:
    if not 2000 <= year <= 2099 or not 1 <= month <= 12:
        return None
    return year, month


def display_expiry(parsed: tuple[int, int]) -> str:
    """``(2026, 4)`` -> ``04/2026``, the way the foil prints it."""
    year, month = parsed
    return f"{month:02d}/{year}"


def months_until(parsed: tuple[int, int], as_of: date) -> int:
    """Whole calendar months from ``as_of``'s month to the expiry month.

    Negative means the batch has already expired; 0 means it expires in the
    current month.
    """
    return (parsed[0] - as_of.year) * 12 + (parsed[1] - as_of.month)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _localised(key: str, **kwargs: object) -> LanguageText:
    return LanguageText(
        **{lang: i18n.t(key, lang, **kwargs) for lang in ("en", "ml", "hi")}
    )


def _finding(
    code: str,
    severity: Severity,
    title_key: str,
    body_key: str,
    action_key: str,
    *,
    anchors: list[str],
    **kwargs: object,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        title=i18n.language_text(title_key),
        message=_localised(body_key, **kwargs),
        action=i18n.language_text(action_key),
        anchors=anchors,
    )


def _batch_matches(batch_no: str, alert: RecallAlert) -> bool:
    batch = normalise_batch(batch_no)
    return bool(batch) and any(batch.startswith(prefix) for prefix in alert.batch_prefixes)


def _recall_findings_localised(medicine: ScannedMedicine) -> list[Finding]:
    """Recall findings with the reason rendered per language.

    ``recall.body`` embeds a whole reason sentence, so the placeholder carrying
    it has to differ by language.  Building the three strings explicitly keeps
    ``i18n.t`` a plain formatter.
    """
    label = medicine.label or "—"
    canonicals = {ingredient.canonical for ingredient in medicine.ingredients}
    findings: list[Finding] = []

    for alert in RECALLS:
        if not alert.matches_drug(canonicals, label):
            continue
        if not _batch_matches(medicine.batch_no, alert):
            continue
        batch = normalise_batch(medicine.batch_no) or medicine.batch_no
        findings.append(
            Finding(
                code="RECALLED_BATCH",
                severity=Severity.critical,
                title=i18n.language_text("recall.title"),
                message=LanguageText(
                    **{
                        lang: i18n.t(
                            "recall.body",
                            lang,
                            label=label,
                            batch=batch,
                            reason=i18n.t(f"recall.reason.{alert.reason}", lang),
                        )
                        for lang in ("en", "ml", "hi")
                    }
                ),
                action=i18n.language_text("recall.action"),
                anchors=[alert.molecule],
            )
        )
        break  # one notice per strip is enough to stop the dispense

    return findings


def _expiry_findings(medicine: ScannedMedicine, as_of: date) -> list[Finding]:
    if not medicine.expiry:
        return []  # nothing printed was read: not a finding, just no data

    label = medicine.label or "—"
    parsed = parse_expiry(medicine.expiry)
    if parsed is None:
        return [
            _finding(
                "EXPIRY_UNREADABLE",
                Severity.warning,
                "expiry.unreadable.title",
                "expiry.unreadable.body",
                "expiry.unreadable.action",
                anchors=[],
                label=label,
                printed=medicine.expiry[:20],
            )
        ]

    remaining = months_until(parsed, as_of)
    printed = display_expiry(parsed)

    if remaining < 0:
        return [
            _finding(
                "EXPIRED_STOCK",
                Severity.critical,
                "expiry.expired.title",
                "expiry.expired.body",
                "expiry.expired.action",
                anchors=[],
                label=label,
                expiry=printed,
            )
        ]

    if remaining <= EXPIRY_WINDOW_MONTHS:
        return [
            _finding(
                "EXPIRY_SOON",
                Severity.warning,
                "expiry.soon.title",
                "expiry.soon.body",
                "expiry.soon.action",
                anchors=[],
                label=label,
                expiry=printed,
            )
        ]

    return []


def _cold_chain_findings(medicine: ScannedMedicine) -> list[Finding]:
    haystack = " ".join(
        [medicine.label, *(ingredient.name_en for ingredient in medicine.ingredients)]
    ).lower()
    if not any(term in haystack for term in COLD_CHAIN_TERMS):
        return []
    return [
        _finding(
            "COLD_CHAIN_RISK",
            Severity.warning,
            "cold.title",
            "cold.body",
            "cold.action",
            anchors=[],
            label=medicine.label or "—",
        )
    ]


def audit(medicines: list[ScannedMedicine], as_of: date | None = None) -> list[Finding]:
    """Audit every scanned box for recall, expiry and cold-chain risk.

    ``as_of`` exists so the check is testable and auditable; the API passes
    nothing and the current date is used.
    """
    today = as_of or date.today()
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for medicine in medicines:
        for finding in (
            *_recall_findings_localised(medicine),
            *_expiry_findings(medicine, today),
            *_cold_chain_findings(medicine),
        ):
            key = (finding.code, finding.message.en)
            if key in seen:
                continue  # the same box scanned twice must not double the banner
            seen.add(key)
            findings.append(finding)

    return findings
