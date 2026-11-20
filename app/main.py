"""KathaPulse AI -- dialect-aware medication safety companion.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000

Privacy posture (DPDP Act 2023 aligned)
---------------------------------------
* ``/verify-strip`` reads the upload into a ``bytes`` object and never touches
  the filesystem.  There is no ``tempfile`` import anywhere in this package.
* The response carries ``processed_in_memory: true`` so the client can show it.
* No cookies, no sessions, no per-user identifiers, no request-body logging.
* ``Cache-Control: no-store`` on every response, including the HTML shell.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import clinical, extraction, i18n
from .schemas import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    HealthResponse,
    Language,
    VerifyResponse,
    VerifyTextRequest,
)
from .taxonomy import all_drugs

logger = logging.getLogger("kathapulse")

BASE_DIR = __file__.rsplit("/", 1)[0]
STATIC_DIR = f"{BASE_DIR}/../static"

app = FastAPI(
    title="KathaPulse AI",
    description=(
        "Dialect-aware medication safety and strip verification. "
        "Images are processed in RAM only and never stored."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
        "script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'"
    )
    return response


# ---------------------------------------------------------------------------
# Static shell
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(f"{STATIC_DIR}/index.html")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    engines = extraction.active_engines()
    return HealthResponse(
        vision_model=engines["vision_model"],
        vision_base_url=engines["vision_base_url"],
        ocr_engine=engines["ocr_engine"],
        taxonomy_ingredients=len(all_drugs()),
    )


# ---------------------------------------------------------------------------
# Verification endpoints
# ---------------------------------------------------------------------------


def _flatten_flags(safety) -> dict:
    """Derive the client's flat contract fields from the findings tree.

    Keeping one source of truth (the findings) avoids the classic drift where
    a boolean flag and the message text disagree.
    """
    codes = {finding.code for finding in safety.findings}
    return {
        "safety_message_ml": clinical.build_speech(
            safety.findings, Language.malayalam
        ).text,
        "safety_message_hi": clinical.build_speech(
            safety.findings, Language.hindi
        ).text,
        "duplicate_salt_warning": "DUPLICATE_SALT" in codes,
        "lasa_risk": "LASA_RISK" in codes,
    }


async def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Validate and buffer an upload entirely in memory."""
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG or WebP strip photographs are accepted.",
        )

    data = await upload.read(MAX_IMAGE_BYTES + 1)
    await upload.close()  # release the client stream immediately
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image larger than 6 MiB.")

    signatures = ALLOWED_IMAGE_TYPES[content_type]
    if not any(data.startswith(sig) for sig in signatures):
        raise HTTPException(
            status_code=415,
            detail="File content does not match the declared image type.",
        )
    return data, content_type


@app.post("/verify-strip", response_model=VerifyResponse)
async def verify_strip(
    image: UploadFile = File(..., description="Scrubbed strip photograph"),
    language: Language = Form(Language.malayalam),
    paracetamol_taken_today_mg: float = Form(0.0, ge=0, le=20000),
) -> VerifyResponse:
    """Read a strip photograph and return localised safety findings.

    The image is held in a local ``bytes`` buffer for this request only.
    """
    data, content_type = await _read_upload(image)

    result = await extraction.extract(data, content_type)

    if result.status == "manual_required" and not result.medicines:
        # Nothing legible: answer honestly and point the user at manual entry.
        first = clinical.ScannedMedicine(label="unreadable", matched=False, ingredients=[])
        safety = clinical.analyse([first], language, paracetamol_taken_today_mg)
        return VerifyResponse(
            extraction_status="manual_required",
            extraction_source=result.source,
            medicines=[first],
            safety=safety,
            disclaimer=i18n.language_text("disclaimer"),
            language=language,
            image_bytes_received=len(data),
            **_flatten_flags(safety),
        )

    safety = await run_in_threadpool(
        clinical.analyse, result.medicines, language, paracetamol_taken_today_mg
    )
    return VerifyResponse(
        extraction_status=result.status,  # type: ignore[arg-type]
        extraction_source=result.source,
        medicines=result.medicines,
        safety=safety,
        disclaimer=i18n.language_text("disclaimer"),
        language=language,
        image_bytes_received=len(data),
        **_flatten_flags(safety),
    )


@app.post("/verify-medicines", response_model=VerifyResponse)
async def verify_medicines(payload: VerifyTextRequest) -> VerifyResponse:
    """Verify a typed list of medicines (manual entry / pharmacist tooling)."""
    raw = [(m.name, [m.name]) for m in payload.medicines]
    medicines = [
        extraction.resolve_medicine(label, names, index)
        for index, (label, names) in enumerate(raw)
    ]
    safety = clinical.analyse(
        medicines, payload.language, payload.paracetamol_taken_today_mg or 0.0
    )
    matched = sum(1 for m in medicines if m.matched)
    status = "ok" if matched == len(medicines) else ("partial" if matched else "manual_required")
    return VerifyResponse(
        extraction_status=status,
        extraction_source=extraction.ExtractionSource.manual,
        medicines=medicines,
        safety=safety,
        disclaimer=i18n.language_text("disclaimer"),
        language=payload.language,
        **_flatten_flags(safety),
    )


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
