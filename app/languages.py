"""Language registry: one row per language, so expansion is data, not surgery.

Adding a language is meant to touch three files and no logic:

1. add a :class:`LanguageSpec` row here with ``enabled=False`` first;
2. add the code to :class:`app.schemas.Language` (the API enum);
3. add one string per key in ``app/i18n.py`` (31 keys today) and one field per
   language in ``LanguageText``.

``enabled`` is the rollout gate. A row can exist — with its script, family and
TTS locale recorded — long before anyone has translated a word, which keeps the
planning honest: the pipeline is visible, the coverage is not faked.
"""

from __future__ import annotations

from dataclasses import dataclass

#: BCP-47 tags a phone's TTS engine is most likely to expose. The device voice
#: is the real dependency here: an absent voice means the written warning is the
#: only channel unless the WASM audio pack (README, Pass 18) ships.
DEFAULT_TTS_LOCALE = "en-IN"


@dataclass(frozen=True)
class LanguageSpec:
    """Everything the app needs to know about one language."""

    code: str  # ISO 639-1, matches app.schemas.Language values
    english_name: str
    native_name: str
    script: str
    family: str
    tts_locale: str
    enabled: bool
    #: Short, concrete note an expansion engineer needs.
    notes: str = ""

    @property
    def status(self) -> str:
        return "live" if self.enabled else "planned"


LANGUAGES: tuple[LanguageSpec, ...] = (
    # -- live in this build -------------------------------------------------
    LanguageSpec(
        "ml", "Malayalam", "മലയാളം", "Malayalam", "Dravidian", "ml-IN", True,
        "Kerala pilot language. Many budget phones ship no ml-IN voice; the UI "
        "detects that and shows an install hint instead of speaking English.",
    ),
    LanguageSpec(
        "hi", "Hindi", "हिन्दी", "Devanagari", "Indo-Aryan", "hi-IN", True,
        "Second pilot language; hi-IN is present on most Android builds.",
    ),
    LanguageSpec(
        "en", "English", "English", "Latin", "Germanic", "en-IN", True,
        "Technical fallback and the pharmacist-facing copy.",
    ),
    # -- registered, not yet translated -------------------------------------
    LanguageSpec(
        "ta", "Tamil", "தமிழ்", "Tamil", "Dravidian", "ta-IN", False,
        "Tamil Nadu expansion. Same Dravidian sentence shapes as Malayalam, so "
        "the 31 strings translate cleanly; check ta-IN voice availability.",
    ),
    LanguageSpec(
        "te", "Telugu", "తెలుగు", "Telugu", "Dravidian", "te-IN", False,
        "Andhra/Telangana expansion; longest drug transliterations of the "
        "southern set — budget for layout testing at 320px.",
    ),
    LanguageSpec(
        "kn", "Kannada", "ಕನ್ನಡ", "Kannada", "Dravidian", "kn-IN", False,
        "Karnataka expansion; shares the Dravidian copy structure.",
    ),
    LanguageSpec(
        "bn", "Bengali", "বাংলা", "Bengali", "Indo-Aryan", "bn-IN", False,
        "West Bengal expansion; Indo-Aryan, so Hindi copy is a closer base.",
    ),
    LanguageSpec(
        "mr", "Marathi", "मराठी", "Devanagari", "Indo-Aryan", "mr-IN", False,
        "Maharashtra expansion; reuses the Devanagari font stack and hi-IN "
        "layout assumptions.",
    ),
    LanguageSpec(
        "gu", "Gujarati", "ગુજરાતી", "Gujarati", "Indo-Aryan", "gu-IN", False,
        "Gujarat expansion; new script, so it needs its own font check.",
    ),
)

BY_CODE: dict[str, LanguageSpec] = {spec.code: spec for spec in LANGUAGES}


def get(code: str) -> LanguageSpec | None:
    return BY_CODE.get(code)


def enabled_codes() -> tuple[str, ...]:
    return tuple(spec.code for spec in LANGUAGES if spec.enabled)


def planned_codes() -> tuple[str, ...]:
    return tuple(spec.code for spec in LANGUAGES if not spec.enabled)


def tts_locale(code: str) -> str:
    spec = BY_CODE.get(code)
    return spec.tts_locale if spec else DEFAULT_TTS_LOCALE
