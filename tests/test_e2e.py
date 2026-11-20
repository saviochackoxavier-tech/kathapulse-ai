"""Pass 4 — end-to-end loop test through the real HTTP surface.

This exercises the whole chain the phone walks:
  multipart image -> /verify-strip -> extraction -> clinical rules -> JSON with
  localised cards + speech script + flat flags.

Only the vision boundary is stubbed (there is no API key in CI); every layer
below it — validation, taxonomy, rules, localisation, serialisation — is real.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.extraction import Extraction, build_medicines
from app.schemas import ExtractionSource

client = TestClient(main.app)


def jpeg_bytes(size: int = 2048) -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


@pytest.fixture()
def two_strip_scan(monkeypatch):
    """Vision tier reports two separate paracetamol strips."""

    async def fake_extract(image_bytes: bytes, content_type: str):
        return Extraction(
            medicines=build_medicines(
                [("Dolo 650", ["Dolo 650"]), ("Crocin 650", ["Crocin 650"])]
            ),
            source=ExtractionSource.vision,
            status="ok",
        )

    monkeypatch.setattr(main.extraction, "extract", fake_extract)


def test_end_to_end_capture_to_audio_script(two_strip_scan):
    response = client.post(
        "/verify-strip",
        files={"image": ("strip.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")},
        data={"language": "ml"},
    )
    assert response.status_code == 200

    body = response.json()

    # 1. Structured JSON parsed from the Pydantic model.
    assert body["scan_id"]
    assert body["extraction_status"] == "ok"
    assert body["processed_in_memory"] is True
    assert body["image_bytes_received"] > 0

    # 2. The clinical verdict the user sees.
    assert body["safety"]["verdict"] == "critical"
    codes = [f["code"] for f in body["safety"]["findings"]]
    assert "DUPLICATE_SALT" in codes
    assert "PARACETAMOL_DAILY_MAX" not in codes  # 1300 mg alone is under 4000

    # 3. Cards carry all three languages, ready for any device.
    finding = next(f for f in body["safety"]["findings"] if f["code"] == "DUPLICATE_SALT")
    for lang in ("en", "ml", "hi"):
        assert finding["title"][lang]
        assert finding["message"][lang]
        assert finding["action"][lang]

    # 4. The strings handed straight to SpeechSynthesis.
    assert "പാരസെറ്റമോൾ" in body["safety_message_ml"]
    assert "पैरासिटामोल" in body["safety_message_hi"]
    assert body["safety"]["speech"]["language"] == "ml"
    assert body["safety"]["speech"]["rate"] < 1.0

    # 5. The flat flags cannot disagree with the findings.
    assert body["duplicate_salt_warning"] is True
    assert body["lasa_risk"] is False


def test_end_to_end_hindi_round_trip(two_strip_scan):
    response = client.post(
        "/verify-strip",
        files={"image": ("strip.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")},
        data={"language": "hi"},
    )
    body = response.json()
    assert body["language"] == "hi"
    assert body["safety"]["speech"]["language"] == "hi"
    assert "पैरासिटामोल" in body["safety"]["speech"]["text"]
    assert body["disclaimer"]["hi"]


def test_word_sized_payload_stays_under_a_slow_3g_budget(two_strip_scan):
    """A low-end phone on 3G: the JSON must stay small enough to be usable."""
    response = client.post(
        "/verify-strip",
        files={"image": ("strip.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")},
        data={"language": "ml"},
    )
    payload = json.dumps(response.json(), ensure_ascii=False)
    assert len(payload.encode("utf-8")) < 12000, f"JSON is {len(payload)} bytes"


def test_error_paths_are_json_and_localisable():
    """Every failure the client must classify arrives as a JSON body."""
    too_big = client.post(
        "/verify-strip",
        files={
            "image": ("big.jpg", io.BytesIO(jpeg_bytes(main.MAX_IMAGE_BYTES + 2048)), "image/jpeg")
        },
        data={"language": "ml"},
    )
    assert too_big.status_code == 413
    assert "detail" in too_big.json()

    wrong_type = client.post(
        "/verify-strip",
        files={"image": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"language": "ml"},
    )
    assert wrong_type.status_code == 415
    assert "detail" in wrong_type.json()

    bad_json = client.post("/verify-medicines", json={"medicines": [], "language": "ml"})
    assert bad_json.status_code == 422
