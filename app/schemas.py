"""Strict request/response contracts for KathaPulse AI.

Design notes
------------
* Every inbound model uses ``extra="forbid"`` so a caller cannot smuggle
  extra keys into a request that later code might trust.
* Free-text fields are length-capped and charset-whitelisted.  Drug names on
  an Indian strip are Latin script plus optional Devanagari/Malayalam, digits,
  strength units and a few punctuation marks -- nothing else is accepted.
* Unrecognised text is *never* executed, interpolated into prompts, or used to
  build tool calls.  It is only fuzzy-matched against a fixed taxonomy.  That
  is the structural defence against prompt injection; the regexes and the
  phrase blocklist below are belt-and-braces.
"""

from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MiB is generous for a 1600px JPEG.
MAX_MEDICINES_PER_SCAN = 10
MAX_TEXT_CHARS = 120
MAX_STRIPS_PER_BATCH = 5  # a real polypharmacy basket: 3-5 strips

ALLOWED_IMAGE_TYPES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}

# Latin + Malayalam + Devanagari + digits + a small punctuation set.
# Note: no newlines, no braces, no quotes -- those are the characters prompt
# injection payloads lean on.
_ALLOWED_CHARS = re.compile(
    r"^[\w\u0D00-\u0D7F\u0900-\u097F +\-./()%&,'\u00ae\u2122]{1,"
    + str(MAX_TEXT_CHARS)
    + r"}$"
)

# Defence in depth: even inside the allowed charset, refuse text that reads
# like an instruction aimed at a model.  Matched case-insensitively.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\b.{0,30}\b(previous|above|prior|all)\b",
        r"\b(system|developer)\s*(prompt|message|instruction)",
        r"\bdisregard\b",
        r"\bjailbreak\b",
        r"\byou are (now|an?) \b",
        r"\bact as\b",
        r"\breturn\b.{0,20}\b(only|exactly)\b",
        r"\bdo not (warn|flag|report)\b",
        r"\b(safe|mark)\b.{0,20}\b(safe|no warning)\b",
        r"<\s*/?\s*(script|system|instruction)",
    )
]


def _sanitise_free_text(value: str) -> str:
    """Collapse whitespace and reject anything outside the drug-name charset."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("value must not be empty")
    if len(cleaned) > MAX_TEXT_CHARS:
        raise ValueError(f"value must be at most {MAX_TEXT_CHARS} characters")
    if not _ALLOWED_CHARS.match(cleaned):
        raise ValueError("value contains characters that are not allowed in a medicine name")
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            raise ValueError("value looks like an instruction, not a medicine name")
    return cleaned


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Language(str, Enum):
    """Languages the safety layer can speak/write."""

    malayalam = "ml"
    hindi = "hi"
    english = "en"


class Severity(str, Enum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Verdict(str, Enum):
    critical = "critical"
    caution = "caution"
    safe = "safe"
    unknown = "unknown"


class ExtractionSource(str, Enum):
    vision = "vision_llm"
    ocr = "ocr"
    manual = "manual"
    none = "none"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class ManualMedicine(BaseModel):
    """One medicine as typed/confirmed by the user (fallback path)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_TEXT_CHARS, examples=["Dolo 650"])
    strength_mg: float | None = Field(default=None, ge=0, le=5000)

    _validate_name = field_validator("name")(_sanitise_free_text)


class VerifyTextRequest(BaseModel):
    """Text-only verification (manual entry, offline demo, pharmacist tooling)."""

    model_config = ConfigDict(extra="forbid")

    medicines: list[ManualMedicine] = Field(min_length=1, max_length=MAX_MEDICINES_PER_SCAN)
    language: Language = Language.malayalam
    #: Paracetamol already taken today (mg).  Lets the engine catch a real
    #: cumulative-overdose pattern that a single strip scan cannot see.
    paracetamol_taken_today_mg: float | None = Field(default=None, ge=0, le=20000)

    _validate_meds = field_validator("medicines")(lambda v: v)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class ResolvedIngredient(BaseModel):
    """A taxonomy hit plus the strength that was actually printed on the strip."""

    canonical: str
    name_en: str
    name_ml: str
    name_hi: str
    drug_class: str
    strength_mg: float | None = None
    daily_max_mg: float | None = None


class ScannedMedicine(BaseModel):
    """One physical strip/box the user showed the camera."""

    label: str = Field(description="Best-effort text the vision layer read")
    matched: bool
    ingredients: list[ResolvedIngredient] = Field(default_factory=list)
    #: A shelf name we recognise but deliberately do not map to molecules
    #: (e.g. Loprin-LS). Still participates in LASA comparison, never in salt rules.
    brand_only: bool = False


class LanguageText(BaseModel):
    """Localised copy for one finding, so the client never translates alone."""

    en: str
    ml: str
    hi: str


class Finding(BaseModel):
    code: str
    severity: Severity
    title: LanguageText
    message: LanguageText
    action: LanguageText
    #: Ingredient canonicals this finding is about -- drives the UI highlight
    #: anchors (high-contrast chips next to the warning).
    anchors: list[str] = Field(default_factory=list)


class SpeechPayload(BaseModel):
    language: Language
    text: str
    #: Slower rate for elderly listeners; the client may still override.
    rate: float = 0.85
    pause_before: float = 0.25


class SafetyReport(BaseModel):
    verdict: Verdict
    findings: list[Finding]
    speech: SpeechPayload


class VerifyResponse(BaseModel):
    scan_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    extraction_status: Literal["ok", "partial", "manual_required"]
    extraction_source: ExtractionSource
    medicines: list[ScannedMedicine]
    safety: SafetyReport
    disclaimer: LanguageText
    language: Language
    processed_in_memory: Literal[True] = True
    image_bytes_received: int = 0

    # -- flat fields for the client contract ------------------------------
    # The full tri-lingual findings stay the source of truth; these mirror the
    # speech script so a client can hand `safety_message_ml` / `safety_message_hi`
    # straight to SpeechSynthesis without walking the findings tree.
    safety_message_ml: str = ""
    safety_message_hi: str = ""
    duplicate_salt_warning: bool = False
    lasa_risk: bool = False


class StripReport(BaseModel):
    """One strip inside a batch, analysed on its own."""

    strip_index: int
    medicines: list[ScannedMedicine]
    safety: SafetyReport


class BatchVerifyResponse(BaseModel):
    """A multi-strip scan: every strip plus the combined basket analysis.

    The combined report is the one that matters clinically — the dangerous
    duplicate usually only appears *across* strips, never inside one.
    """

    scan_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    strip_count: int
    strips: list[StripReport]
    combined: SafetyReport
    disclaimer: LanguageText
    language: Language
    processed_in_memory: Literal[True] = True
    image_bytes_received: int = 0

    # -- flat fields mirroring the combined speech script -----------------
    safety_message_ml: str = ""
    safety_message_hi: str = ""
    duplicate_salt_warning: bool = False
    lasa_risk: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    vision_model: str | None = None
    #: Endpoint host only — never the key, never a token.
    vision_base_url: str | None = None
    ocr_engine: str | None = None
    taxonomy_ingredients: int
