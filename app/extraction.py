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

from . import config, knowledge_base, taxonomy
from .schemas import ExtractionSource, ResolvedIngredient, ScannedMedicine

logger = logging.getLogger("kathapulse.extraction")

#: Responses that mean "this key cannot serve us" rather than "we sent rubbish".
#: 429 = rate limited, 401/403 = revoked, exhausted or scoped to another model.
_ROTATE_STATUSES = frozenset({401, 403, 429})

#: Pause before the single quiet retry of a 429. Only ever reached when there
#: is no other key to try, so a configured fallback never pays this delay.
_RATE_LIMIT_BACKOFF_S = 1.2

_VISION_PROMPT = (
    "You read medicine strips sold in Indian pharmacies. "
    "Return ONLY minified JSON, no prose, no markdown: "
    '{"medicines":[{"brand_name":"<printed brand>",'
    '"active_ingredients":["<molecule exactly as printed>"],'
    '"dosage_strength":"<e.g. 650 mg or 40 mg/12.5 mg>",'
    '"batch_number":"<batch printed after B.No./Batch/Lot, or empty>",'
    '"expiry_date":"<printed expiry as MM/YYYY, or empty>"}]}. '
    "One object per physical strip or box visible. Max 4 objects, max 4 ingredients each. "
    "Copy only text you can actually see; never guess, never add commentary, "
    "never invent a molecule, a batch number or a date. "
    "If nothing is legible return {\"medicines\":[]}."
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
    #: Batch and expiry are optional by design: the pharmacy audit needs them,
    #: the clinical rules never do, and an unread foil must not fail the scan.
    batch_number: str = Field(default="", max_length=40)
    expiry_date: str = Field(default="", max_length=40)

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

    def as_batch(self) -> str:
        """Printed batch number, or "" -- never a guess."""
        return _code(self.batch_number)

    def as_expiry(self) -> str:
        """Printed expiry, or "" -- ``app.recall`` decides what it means."""
        return _code(self.expiry_date)


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


def resolve_medicine(
    label: str,
    raw_names: list[str],
    strip_index: int,
    batch_no: str = "",
    expiry: str = "",
) -> ScannedMedicine:
    """Map printed text onto the taxonomy, keeping printed strengths.

    ``batch_no`` and ``expiry`` are carried through untouched: they belong to
    the box, not to the molecule, and the batch audit reads them verbatim.
    """
    haystack = " ".join([label, *raw_names]).strip()

    # A brand we recognise but refuse to resolve (Loprin-LS): stop here rather
    # than letting a long-alias match quietly attribute Loprin's molecule to it.
    if taxonomy.knows_brand(haystack):
        return ScannedMedicine(
            label=taxonomy.brand_display(haystack),
            matched=False,
            ingredients=[],
            brand_only=True,
            batch_no=batch_no,
            expiry=expiry,
        )

    matches = taxonomy.lookup(haystack)
    verified_by = "taxonomy" if matches else ""
    fixed = dict(taxonomy.combo_members(haystack))

    # Deterministic fallback: the local ground truth catches spacings, dashes and
    # OCR slips the taxonomy's exact/fuzzy lookup lets through. It also wins when
    # it is *more* specific: "Glycomet GP" contains the alias "glycomet", so the
    # taxonomy answers metformin alone and would silently drop the glimepiride.
    # Only a proper superset of molecules replaces the taxonomy's answer, and it
    # can only return drugs the taxonomy already knows -- so a miss still leaves
    # the honest "manual entry" path untouched.
    resolution = knowledge_base.resolve(haystack)
    if resolution:
        kb_matches = tuple(
            taxonomy.BY_CANONICAL[canonical]
            for canonical in resolution.molecules
            if canonical in taxonomy.BY_CANONICAL
        )
        if kb_matches and (
            not matches
            or {d.canonical for d in kb_matches} > {d.canonical for d in matches}
        ):
            matches = kb_matches
            verified_by = "ground_truth"
            fixed = fixed or dict(resolution.strengths)

    printed_strength = taxonomy.parse_strength(haystack)
    combo_strength = fixed

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
        batch_no=batch_no,
        expiry=expiry,
        # "taxonomy" or "ground_truth": which layer verified the molecule. The UI
        # shows this, so a fallback-resolved strip is never passed off as a
        # confident model read.
        verified_by=verified_by if ingredients else "",
    )


def build_medicines(reads: list[tuple]) -> list[ScannedMedicine]:
    """Build medicines from ``(label, names)`` or ``(label, names, batch, expiry)``.

    Both shapes are accepted because the OCR tier only ever has text, while the
    vision tier also reads the batch and expiry line.
    """
    medicines: list[ScannedMedicine] = []
    for index, read in enumerate(reads[:10]):
        label, names = read[0], read[1]
        batch_no = read[2] if len(read) > 2 else ""
        expiry = read[3] if len(read) > 3 else ""
        medicines.append(resolve_medicine(label, names, index, batch_no, expiry))
    return medicines


# ---------------------------------------------------------------------------
# Tier 1: vision LLM
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    """Strip control characters and hard-cap length on untrusted model text."""
    value = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return " ".join(value.split())[:120]


def _code(value: str) -> str:
    """Normalise a printed batch/expiry code: ASCII alphanumerics and separators.

    Untrusted model text never reaches a rule unclamped, and a stray sentence
    ("batch not visible") collapses to its usable characters rather than being
    trusted as a batch number.
    """
    text = re.sub(r"[^A-Za-z0-9 ./_\-]", "", str(value or "")).strip()
    return " ".join(text.split())[:20].upper()


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


async def _read_with_key(
    client: httpx.AsyncClient,
    cfg: config.VisionSettings,
    key: str,
    payload: dict[str, Any],
    *,
    has_fallback: bool,
    key_position: tuple[int, int],
) -> str | None:
    """One key's turn at the vision endpoint.

    Returns the model's content, or ``None`` when this key cannot serve us and
    the caller should move to the next one. Provider-side failures (5xx, a
    malformed envelope) are deliberately *not* caught here: they are not the
    key's fault, so the whole tier is abandoned rather than walking a second key
    that would fail in exactly the same way.

    Two retry policies live here, and exactly one applies to any given key:

    * **a key with another key behind it** — a 401/403/429 is final. Retrying a
      rate-limited key only spends the demo's remaining seconds when the next
      key is already waiting;
    * **a key with nothing behind it** (a lone key, or the last one in the
      chain) — a 429 gets one quiet retry, which is the pre-failover behaviour.
      401/403 still stop immediately: a revoked key does not heal in a second.
    """
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(1 if has_fallback else 2):
        response = await client.post(
            f"{cfg.base_url}/chat/completions", headers=headers, json=payload
        )
        if response.status_code not in _ROTATE_STATUSES:
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        if not has_fallback and attempt == 0 and response.status_code == 429:
            await asyncio.sleep(_RATE_LIMIT_BACKOFF_S)
            continue

        # Status only: never the key, never the response body.
        logger.warning(
            "vision key %d/%d unusable (%s)",
            key_position[0],
            key_position[1],
            response.status_code,
        )
        return None
    return None


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
            for position, key in enumerate(keys, start=1):
                content = await _read_with_key(
                    client,
                    cfg,
                    key,
                    payload,
                    has_fallback=position < len(keys),
                    key_position=(position, len(keys)),
                )
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

    results: list[tuple[str, list[str], str, str]] = []
    for item in parsed.medicines:
        label = item.as_label()
        names = item.as_names()
        if label or names:
            results.append((label, names, item.as_batch(), item.as_expiry()))
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
