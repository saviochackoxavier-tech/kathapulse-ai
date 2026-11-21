"""Strip reading: multimodal extraction, then taxonomy resolution.

Three tiers, each optional and independently degradable:

1. **Vision LLM** (`KATHA_VISION_API_KEY`): sends the scrubbed JPEG as a base64
   data URL to any OpenAI-compatible chat-completions endpoint — GroqCloud
   (`https://api.groq.com/openai/v1`, `meta-llama/llama-4-scout-17b-16e-instruct`)
   or OpenAI itself — and asks for strictly shaped JSON.
2. **Local OCR** (pytesseract + tesseract-ocr, if installed): plain text, then
   the taxonomy matcher.
3. **Nothing**: the caller returns ``manual_required`` and the UI asks the user
   to type the printed name. We never invent a medicine.

Privacy: the image lives only in a ``bytes`` object for the duration of the
request. No temporary files, no ``tempfile``, no upload to disk, no cache.
The API key is read from the environment per request and never logged, echoed
or placed in a response.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import config, taxonomy
from .schemas import ExtractionSource, ResolvedIngredient, ScannedMedicine

logger = logging.getLogger("kathapulse.extraction")

#: Responses that mean "this key cannot serve us" rather than "we sent rubbish".
#: 429 = rate limited, 401/403 = revoked, exhausted or scoped to another model.
_ROTATE_STATUSES = frozenset({401, 403, 429})

_VISION_PROMPT = (
    "You read medicine strips sold in Indian pharmacies. "
    "Return ONLY minified JSON, no prose, no markdown: "
    '{"medicines":[{"brand_name":"<printed brand>",'
    '"active_ingredients":["<molecule exactly as printed>"],'
    '"dosage_strength":"<e.g. 650 mg or 40 mg/12.5 mg>"}]}. '
    "One object per physical strip or box visible. Max 4 objects, max 4 ingredients each. "
    "Copy only text you can actually see; never guess, never add commentary, "
    "never invent a molecule. If nothing is legible return {\"medicines\":[]}."
)


# ---------------------------------------------------------------------------
# Vision output contract (untrusted -> validated)
# ---------------------------------------------------------------------------


class _VisionMedicine(BaseModel):
    """Accepts both the Groq shape and looser shapes some models emit."""

    model_config = ConfigDict(extra="ignore")

    brand_name: str = Field(default="", max_length=200)
    active_ingredients: list[str] = Field(default_factory=list, max_length=8)
    dosage_strength: str = Field(default="", max_length=40)

    # Tolerated aliases: older prompts used label/names.
    label: str = Field(default="", max_length=200)
    names: list[str] = Field(default_factory=list, max_length=8)

    def as_label(self) -> str:
        """Brand + strength, so the taxonomy can read the printed dose."""
        base = _clean(self.brand_name or self.label)
        strength = _clean(self.dosage_strength)
        if strength and strength.lower() not in base.lower():
            return f"{base} {strength}".strip()[:120]
        return base

    def as_names(self) -> list[str]:
        raw = [*self.active_ingredients, *self.names]
        return [_clean(n) for n in raw if _clean(n)][:8]


class _VisionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    medicines: list[_VisionMedicine] = Field(default_factory=list, max_length=6)


@dataclass
class Extraction:
    medicines: list[ScannedMedicine]
    source: ExtractionSource
    status: str  # "ok" | "partial" | "manual_required"


# ---------------------------------------------------------------------------
# Resolution: raw printed text -> taxonomy molecules
# ---------------------------------------------------------------------------


def resolve_medicine(label: str, raw_names: list[str], strip_index: int) -> ScannedMedicine:
    """Map printed text onto the taxonomy, keeping printed strengths."""
    haystack = " ".join([label, *raw_names]).strip()

    # A brand we recognise but refuse to resolve (Loprin-LS): stop here rather
    # than letting a long-alias match quietly attribute Loprin's molecule to it.
    if taxonomy.knows_brand(haystack):
        return ScannedMedicine(
            label=taxonomy.brand_display(haystack),
            matched=False,
            ingredients=[],
            brand_only=True,
        )

    matches = taxonomy.lookup(haystack)

    printed_strength = taxonomy.parse_strength(haystack)
    combo = taxonomy.combo_members(haystack)
    combo_strength = {canonical: strength for canonical, strength in combo}

    ingredients: list[ResolvedIngredient] = []
    for drug in matches:
        strength = combo_strength.get(drug.canonical)
        if strength is None:
            strength = printed_strength or drug.default_strength
        ingredients.append(
            ResolvedIngredient(
                canonical=drug.canonical,
                name_en=drug.name_en,
                name_ml=drug.name_ml,
                name_hi=drug.name_hi,
                drug_class=drug.drug_class,
                strength_mg=strength,
                daily_max_mg=drug.daily_max_mg,
            )
        )

    return ScannedMedicine(
        label=label or (raw_names[0] if raw_names else f"Strip {strip_index + 1}"),
        matched=bool(ingredients),
        ingredients=ingredients,
    )


def build_medicines(labels: list[tuple[str, list[str]]]) -> list[ScannedMedicine]:
    return [
        resolve_medicine(label, names, index)
        for index, (label, names) in enumerate(labels[:10])
    ]


# ---------------------------------------------------------------------------
# Tier 1: vision LLM
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    """Strip control characters and hard-cap length on untrusted model text."""
    value = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return " ".join(value.split())[:120]


def parse_model_json(content: str) -> dict:
    """Extract a JSON object from model output.

    Llama-family models on Groq often wrap JSON in ```json fences or prepend a
    sentence even when told not to. Both are tolerated here rather than failing
    the scan; anything that still is not JSON raises ValueError and the caller
    degrades to the next tier.
    """
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")

    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    return parsed


async def _vision_extract(
    image_bytes: bytes, content_type: str
) -> list[tuple[str, list[str]]] | None:
    """Return [(label, names)] or None if the vision tier is unavailable."""
    cfg = config.vision_settings()  # re-read per request: no restart needed
    keys = cfg.api_keys()
    if not keys:
        return None

    data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"
    payload: dict[str, Any] = {
        "model": cfg.model,
        "temperature": 0,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": _VISION_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List the medicines on these strips."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    # JSON mode is not supported by every Groq model, so it is opt-in.
    if cfg.json_mode:
        payload["response_format"] = {"type": "json_object"}

    content: str | None = None
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_s) as client:
            for index, key in enumerate(keys):
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                # With a fallback configured, a rejected key is worth abandoning
                # immediately: retrying a limited key only spends the demo's
                # remaining seconds. A lone key keeps the quiet single retry.
                last_key = index == len(keys) - 1
                for attempt in range(2):
                    response = await client.post(
                        f"{cfg.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code in _ROTATE_STATUSES:
                        if last_key and response.status_code == 429 and attempt == 0:
                            await asyncio.sleep(1.2)
                            continue
                        # Status only: never the key, never the response body.
                        logger.warning(
                            "vision key %d/%d unusable (%s)",
                            index + 1,
                            len(keys),
                            response.status_code,
                        )
                        break
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    break
                if content:
                    break
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        # Log the failure type only: never the payload, never the key.
        logger.warning("vision tier unavailable (%s), trying next tier", type(exc).__name__)
        return None

    if not content:
        return None

    try:
        parsed = _VisionResult.model_validate(parse_model_json(content))
    except (ValueError, ValidationError, TypeError) as exc:
        logger.warning("vision output unparseable (%s), trying next tier", type(exc).__name__)
        return None

    results: list[tuple[str, list[str]]] = []
    for item in parsed.medicines:
        label = item.as_label()
        names = item.as_names()
        if label or names:
            results.append((label, names))
    return results or None


# ---------------------------------------------------------------------------
# Tier 2: local OCR
# ---------------------------------------------------------------------------


def _ocr_extract(image_bytes: bytes) -> list[tuple[str, list[str]]] | None:
    if not config.ocr_enabled():
        return None

    try:
        import io

        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except Exception:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            text = pytesseract.image_to_string(image, lang="eng")
    except Exception:
        return None

    lines = [_clean(line) for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 4]
    if not lines:
        return None

    # Each OCR line that resolves to a molecule becomes one "strip".
    found: list[tuple[str, list[str]]] = []
    for line in lines[:10]:
        if taxonomy.lookup(line):
            found.append((line, [line]))
    return found or None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def extract(image_bytes: bytes, content_type: str) -> Extraction:
    """Run the tier chain and return whatever the best tier produced."""
    for tier in (_vision_extract, _ocr_extract):
        try:
            raw = (
                await tier(image_bytes, content_type)
                if tier is _vision_extract
                else tier(image_bytes)
            )
        except Exception:
            logger.exception("extraction tier crashed")
            raw = None
        if not raw:
            continue

        medicines = build_medicines(raw)
        matched = [m for m in medicines if m.matched]
        source = (
            ExtractionSource.vision if tier is _vision_extract else ExtractionSource.ocr
        )
        if not matched:
            # Text was read but nothing is in the verified taxonomy.
            return Extraction(medicines=medicines, source=source, status="manual_required")
        status = "ok" if len(matched) == len(medicines) else "partial"
        return Extraction(medicines=medicines, source=source, status=status)

    return Extraction(medicines=[], source=ExtractionSource.none, status="manual_required")


async def extract_batch(
    payloads: list[tuple[bytes, str]], concurrency: int = 3
) -> list[Extraction]:
    """Read several strips for one basket, still entirely in RAM.

    Each payload is the same ``(bytes, content_type)`` pair :func:`extract`
    takes; the image bytes are already validated and bounded by the caller.
    Concurrency is capped at three so a five-strip basket cannot spin up five
    vision calls at once on a cheap phone's shared connection.
    """
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(payload: tuple[bytes, str]) -> Extraction:
        async with gate:
            return await extract(*payload)

    return list(await asyncio.gather(*(one(payload) for payload in payloads)))


def active_engines() -> dict[str, Any]:
    """Report which extraction tiers are live (used by /health)."""
    cfg = config.vision_settings()
    ocr = None
    if config.ocr_enabled():
        try:
            import pytesseract  # type: ignore

            pytesseract.get_tesseract_version()
            ocr = "tesseract"
        except Exception:
            ocr = None
    return {
        "vision_model": cfg.model if cfg.configured else None,
        "vision_base_url": cfg.base_url if cfg.configured else None,
        # Rotation status, never key material: how many keys can serve, and
        # whether a rejected primary has somewhere to go.
        "vision_keys": cfg.key_count,
        "vision_fallback": bool(cfg.fallback_api_key),
        "ocr_engine": ocr,
    }
