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

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import (
    audio_reminders,
    clinical,
    config,
    extraction,
    i18n,
    knowledge_base,
    ratelimit,
    recall,
    relay,
)
from .schemas import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    MAX_STRIPS_PER_BATCH,
    BatchVerifyResponse,
    HealthResponse,
    Language,
    StripReport,
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


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Optional sliding-window backstop (``KATHA_RATE_LIMIT_PER_MIN``).

    Off by default: nginx and Cloudflare carry the 30 req/min budget in a normal
    deployment. Switched on, it protects a bare container or a LAN install where
    no proxy exists. It never logs the client and keeps only timestamps in RAM.
    """
    limit = ratelimit.limit_per_minute()
    if limit:
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = ratelimit.LIMITER.hit(client, limit)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment and try again."},
                headers={
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store, max-age=0",
                    "X-Content-Type-Options": "nosniff",
                },
            )
    return await call_next(request)


#: Schema routes a public deployment should not advertise.
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


@app.middleware("http")
async def hide_api_docs(request: Request, call_next):
    """Occlude the OpenAPI surface unless ``KATHA_DOCS_ENABLED=1``.

    This is the app-side half of the ingress rule that blocks these paths at the
    proxy: even with a misconfigured proxy, a production deploy does not publish
    its schema. Development can turn it back on with one env var.
    """
    if request.url.path in _DOCS_PATHS and not config.docs_enabled():
        return JSONResponse(
            status_code=404,
            content={"detail": "Not Found"},
            headers={
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            },
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Static shell
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(f"{STATIC_DIR}/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Browsers probe /favicon.ico even with a declared icon; answer it."""
    return FileResponse(f"{STATIC_DIR}/favicon.svg", media_type="image/svg+xml")


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    """Serve the offline shell from the root so its scope covers the whole app."""
    return FileResponse(
        f"{STATIC_DIR}/sw.js",
        media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/taxonomy.json", include_in_schema=False)
async def taxonomy_feed() -> JSONResponse:
    """Public, cacheable taxonomy feed for the offline shell and pharmacist tools.

    Data only: no patient data, no keys, nothing request-specific.
    """
    drugs = [
        {
            "canonical": drug.canonical,
            "name_en": drug.name_en,
            "name_ml": drug.name_ml,
            "name_hi": drug.name_hi,
            "drug_class": drug.drug_class,
            "default_strength_mg": drug.default_strength,
            "daily_max_mg": drug.daily_max_mg,
            "combo_partner": drug.combo_partner,
            "aliases": list(drug.aliases),
        }
        for drug in all_drugs()
    ]
    return JSONResponse(
        {"version": app.version, "count": len(drugs), "drugs": drugs}
    )


@app.get("/knowledge.json", include_in_schema=False)
async def knowledge_feed() -> JSONResponse:
    """Public ground-truth catalogue: brands, molecules, cautions, age bands.

    Drug data only -- no patient data, no keys, nothing request-specific -- so a
    pharmacist tool or the offline shell can read the same facts the server
    verifies against. Localised cautions are included so a client never has to
    translate a safety string itself.
    """
    entries = knowledge_base.catalogue()
    counts = knowledge_base.stats()
    return JSONResponse(
        {
            "version": app.version,
            "count": len(entries),
            "brands": counts["brands"],
            "indexed_names": counts["indexed_names"],
            "molecules": counts["molecules"],
            "fuzzy_threshold": knowledge_base.FUZZY_MIN_SCORE,
            "entries": entries,
        }
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    engines = extraction.active_engines()
    return HealthResponse(
        vision_model=engines["vision_model"],
        vision_base_url=engines["vision_base_url"],
        vision_keys=engines["vision_keys"],
        vision_fallback=engines["vision_fallback"],
        ocr_engine=engines["ocr_engine"],
        taxonomy_ingredients=len(all_drugs()),
        recall_notices=len(recall.RECALLS),
        knowledge_base_entries=knowledge_base.stats()["indexed_names"],
        knowledge_base_brands=knowledge_base.stats()["brands"],
    )


# ---------------------------------------------------------------------------
# Verification endpoints
# ---------------------------------------------------------------------------


def _flatten_flags(safety, medicines: list) -> dict:
    """Derive the client's flat contract fields from the findings tree.

    Keeping one source of truth (the findings) avoids the classic drift where
    a boolean flag and the message text disagree. Verification provenance is the
    one thing the findings cannot see, so it comes from the medicines.
    """
    codes = {finding.code for finding in safety.findings}
    return {
        "safety_message_ml": clinical.build_speech(
            safety.findings, Language.malayalam
        ).text,
        "safety_message_hi": clinical.build_speech(
            safety.findings, Language.hindi
        ).text,
        "safety_message_en": clinical.build_speech(
            safety.findings, Language.english
        ).text,
        "duplicate_salt_warning": "DUPLICATE_SALT" in codes,
        "lasa_risk": "LASA_RISK" in codes,
        # Box-level audit, derived from the same findings tree so a banner can
        # never say "recalled" while the findings list stays silent.
        "recall_warning": "RECALLED_BATCH" in codes,
        "expiry_warning": bool(
            codes & {"EXPIRED_STOCK", "EXPIRY_SOON", "EXPIRY_UNREADABLE"}
        ),
        "ground_truth_verified": any(
            getattr(medicine, "verified_by", "") == "ground_truth"
            for medicine in medicines
        ),
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
    age_years: int | None = Form(None, ge=0, le=120),
) -> VerifyResponse:
    """Read a strip photograph and return localised safety findings.

    The image is held in a local ``bytes`` buffer for this request only.
    """
    data, content_type = await _read_upload(image)

    result = await extraction.extract(data, content_type)

    if result.status == "manual_required" and not result.medicines:
        # Nothing legible: answer honestly and point the user at manual entry.
        first = clinical.ScannedMedicine(label="unreadable", matched=False, ingredients=[])
        safety = clinical.analyse(
            [first], language, paracetamol_taken_today_mg, age_years=age_years
        )
        return VerifyResponse(
            extraction_status="manual_required",
            extraction_source=result.source,
            medicines=[first],
            safety=safety,
            disclaimer=i18n.language_text("disclaimer"),
            language=language,
            image_bytes_received=len(data),
            **_flatten_flags(safety, [first]),
        )

    safety = await run_in_threadpool(
        clinical.analyse,
        result.medicines,
        language,
        paracetamol_taken_today_mg,
        age_years=age_years,
    )
    return VerifyResponse(
        extraction_status=result.status,  # type: ignore[arg-type]
        extraction_source=result.source,
        medicines=result.medicines,
        safety=safety,
        disclaimer=i18n.language_text("disclaimer"),
        language=language,
        image_bytes_received=len(data),
        **_flatten_flags(safety, result.medicines),
    )


@app.post("/verify-medicines", response_model=VerifyResponse)
async def verify_medicines(payload: VerifyTextRequest) -> VerifyResponse:
    """Verify a typed list of medicines (manual entry / pharmacist tooling).

    Batch and expiry are optional; when the pharmacist types them the box is
    audited against the recall list and the printed date as well.
    """
    medicines = [
        extraction.resolve_medicine(
            item.name,
            [item.name],
            index,
            batch_no=item.batch_no,
            expiry=item.expiry,
        )
        for index, item in enumerate(payload.medicines)
    ]
    safety = clinical.analyse(
        medicines,
        payload.language,
        payload.paracetamol_taken_today_mg or 0.0,
        age_years=payload.age_years,
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
        **_flatten_flags(safety, medicines),
    )


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.post("/verify-strips/batch", response_model=BatchVerifyResponse)
async def verify_strips_batch(
    strips: list[UploadFile] = File(..., description="One photo per strip, 1-4 strips"),
    language: Language = Form(Language.malayalam),
    paracetamol_taken_today_mg: float = Form(0.0, ge=0, le=20000),
    age_years: int | None = Form(None, ge=0, le=120),
) -> BatchVerifyResponse:
    """Read several strips for one basket and analyse them together.

    Every upload is validated by the same in-memory path as a single scan and
    released as soon as it is read; nothing is written to disk, and no strip is
    cached beyond this request.
    """
    if not strips:
        raise HTTPException(status_code=400, detail="Send at least one strip photo.")
    if len(strips) > MAX_STRIPS_PER_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"A basket is limited to {MAX_STRIPS_PER_BATCH} strips per scan.",
        )

    payloads: list[tuple[bytes, str]] = []
    total_bytes = 0
    for upload in strips:
        data, content_type = await _read_upload(upload)
        payloads.append((data, content_type))
        total_bytes += len(data)

    results = await extraction.extract_batch(payloads)

    baskets: list[list[clinical.ScannedMedicine]] = []
    for result in results:
        medicines = result.medicines
        if not medicines:
            # Nothing legible: keep the strip honest rather than dropping it.
            medicines = [
                clinical.ScannedMedicine(label="unreadable", matched=False, ingredients=[])
            ]
        baskets.append(medicines)

    report = await run_in_threadpool(
        clinical.analyse_basket,
        baskets,
        language,
        paracetamol_taken_today_mg,
        age_years=age_years,
    )
    return BatchVerifyResponse(
        strip_count=len(results),
        strips=[
            StripReport(strip_index=index, medicines=medicines, safety=safety)
            for index, (medicines, safety) in enumerate(zip(baskets, report.per_strip))
        ],
        combined=report.combined,
        disclaimer=i18n.language_text("disclaimer"),
        language=language,
        image_bytes_received=total_bytes,
        **_flatten_flags(report.combined, [m for strip in baskets for m in strip]),
    )


@app.post("/reminders", response_model=audio_reminders.ReminderResponse)
async def schedule_reminders(
    payload: audio_reminders.ReminderRequest,
) -> audio_reminders.ReminderResponse:
    """Derive a dose-reminder plan from a schedule the user typed.

    Nothing is stored: the plan is computed from the request, returned once, and
    dropped. The browser schedules the times on the patient's own device.
    """
    return await run_in_threadpool(audio_reminders.build_plan, payload)


@app.websocket("/ws/relay/{room_id}")
async def pharmacist_relay(websocket: WebSocket, room_id: str) -> None:
    """Zero-retention pharmacist relay: forward, then forget.

    Refuses every connection unless ``KATHA_RELAY_SECRET`` is configured, and
    every connection needs a valid short-lived ticket for this room. Messages
    are never stored, logged or replayed; the room disappears with its last peer.
    """
    if not relay.configured():
        await websocket.close(code=1011, reason="relay not configured")
        return
    if not relay.verify_ticket(room_id, websocket.query_params.get("ticket", "")):
        await websocket.close(code=1008, reason="invalid ticket")
        return
    if relay.HUB.is_full(room_id):
        await websocket.close(code=1013, reason="room full")
        return

    await relay.HUB.connect(room_id, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if len(message.encode("utf-8")) > relay.MAX_MESSAGE_BYTES:
                continue  # oversized frames are dropped, not relayed
            await relay.HUB.broadcast(room_id, websocket, message)
    except WebSocketDisconnect:
        pass
    finally:
        await relay.HUB.disconnect(room_id, websocket)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
