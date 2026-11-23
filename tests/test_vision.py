"""Vision-tier tests, runnable with no API key and no network.

The Groq call itself is replaced with a stub client, so these tests pin the
contract that matters: prompt shape, URL, auth header, fence-tolerant parsing,
brand/strength mapping into the taxonomy, and clean degradation on failure.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import config, extraction
from app.extraction import parse_model_json

GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


# ---------------------------------------------------------------------------
# Stub transport
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("POST", GROQ_BASE),
                response=httpx.Response(self.status_code),
            )


class FakeClient:
    """Records every call; returns a scripted response."""

    calls: list[dict] = []
    response: FakeResponse = FakeResponse(200, {})

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None, **kwargs):
        FakeClient.calls.append({"url": url, "headers": headers, "json": json})
        return FakeClient.response


@pytest.fixture()
def groq(monkeypatch):
    monkeypatch.setenv("KATHA_VISION_API_KEY", "unit-test-key")
    monkeypatch.setenv("KATHA_VISION_BASE_URL", GROQ_BASE)
    monkeypatch.setenv("KATHA_VISION_MODEL", GROQ_MODEL)
    monkeypatch.setenv("KATHA_VISION_JSON_MODE", "0")
    FakeClient.calls = []
    FakeClient.response = FakeResponse(200, {})
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return FakeClient


def model_reply(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"medicines":[{"brand_name":"Dolo 650"}]}',
        '```json\n{"medicines":[{"brand_name":"Dolo 650"}]}\n```',
        '```\n{"medicines":[{"brand_name":"Dolo 650"}]}\n```',
        'Here is the JSON you asked for:\n{"medicines":[{"brand_name":"Dolo 650"}]}\nHope that helps.',
    ],
)
def test_model_json_survives_fences_and_chatter(raw):
    assert parse_model_json(raw)["medicines"][0]["brand_name"] == "Dolo 650"


@pytest.mark.parametrize("raw", ["", "not json at all", "[1,2,3]", "null"])
def test_non_json_output_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_model_json(raw)


# ---------------------------------------------------------------------------
# Extraction contract
# ---------------------------------------------------------------------------


def test_vision_extracts_brand_ingredients_and_strength(groq):
    groq.response = FakeResponse(
        200,
        model_reply(
            '{"medicines":[{"brand_name":"DOLO 650",'
            '"active_ingredients":["Paracetamol"],"dosage_strength":"650 mg"}]}'
        ),
    )

    raw = asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0test", "image/jpeg"))
    assert raw, "vision tier returned nothing"
    # A read is (label, names, batch, expiry); the batch fields stay empty when
    # the model did not see them, which is not an error.
    label, names, batch, expiry = raw[0]
    assert label == "DOLO 650 650 mg"
    assert "Paracetamol" in names
    assert (batch, expiry) == ("", "")

    medicines = extraction.build_medicines(raw)
    assert medicines[0].matched is True
    assert medicines[0].ingredients[0].canonical == "paracetamol"
    assert medicines[0].ingredients[0].strength_mg == 650


def test_vision_reads_the_printed_batch_and_expiry(groq):
    """Batch and expiry are copied from the foil, normalised, never invented."""
    groq.response = FakeResponse(
        200,
        model_reply(
            '{"medicines":[{"brand_name":"GLYCOMET 500",'
            '"active_ingredients":["Metformin"],"dosage_strength":"500 mg",'
            '"batch_number":"gm 2407/a","expiry_date":"sep 2026"}]}'
        ),
    )

    medicines = extraction.build_medicines(
        asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    )

    assert medicines[0].batch_no == "GM 2407/A"
    assert medicines[0].expiry == "SEP 2026"
    assert medicines[0].ingredients[0].canonical == "metformin"


def test_vision_drops_control_characters_from_a_batch(groq):
    groq.response = FakeResponse(
        200,
        model_reply(
            '{"medicines":[{"brand_name":"GLYCOMET 500",'
            '"batch_number":"GM24\\u0001<script>","expiry_date":"not visible"}]}'
        ),
    )
    medicines = extraction.build_medicines(
        asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    )
    assert medicines[0].batch_no == "GM24SCRIPT"
    assert medicines[0].expiry == "NOT VISIBLE"


def test_vision_handles_combination_strength(groq):
    groq.response = FakeResponse(
        200,
        model_reply(
            '{"medicines":[{"brand_name":"TELMA-H",'
            '"active_ingredients":["Telmisartan","Hydrochlorothiazide"],'
            '"dosage_strength":"40 mg/12.5 mg"}]}'
        ),
    )
    raw = asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    medicines = extraction.build_medicines(raw)
    strengths = {i.canonical: i.strength_mg for i in medicines[0].ingredients}
    assert strengths["telmisartan"] == 40
    assert strengths["hydrochlorothiazide"] == 12.5


def test_vision_sends_the_configured_groq_endpoint_and_header(groq):
    groq.response = FakeResponse(200, model_reply('{"medicines":[]}'))
    asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg"))

    call = groq.calls[0]
    assert call["url"] == f"{GROQ_BASE}/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer unit-test-key"
    assert call["json"]["model"] == GROQ_MODEL

    # The image travels as an in-memory base64 data URL, never a file path.
    user_content = call["json"]["messages"][1]["content"]
    image_part = next(p for p in user_content if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "/tmp" not in image_part["image_url"]["url"]


def test_no_key_means_no_network_call(monkeypatch):
    monkeypatch.delenv("KATHA_VISION_API_KEY", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.calls = []

    assert asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg")) is None
    assert FakeClient.calls == []

    # And the public entry point degrades instead of raising.
    result = asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert result.status == "manual_required"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(500, {}),
        FakeResponse(401, {}),
        FakeResponse(200, {"choices": []}),
        FakeResponse(200, model_reply("I cannot read this image.")),
    ],
)
def test_vision_failures_degrade_to_manual(groq, response):
    groq.response = response
    result = asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert result.status == "manual_required"
    assert result.medicines == []


def test_unknown_brand_from_vision_does_not_invent_a_molecule(groq):
    groq.response = FakeResponse(
        200, model_reply('{"medicines":[{"brand_name":"Zzqx 10","active_ingredients":[]}]}')
    )
    result = asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert result.status == "manual_required"
    assert all(not m.matched for m in result.medicines)


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_key_never_reaches_logs_or_responses(groq, caplog):
    groq.response = FakeResponse(500, {})
    with caplog.at_level("WARNING"):
        asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0", "image/jpeg"))
    assert "unit-test-key" not in caplog.text


def test_health_reports_endpoint_but_not_key(groq):
    from fastapi.testclient import TestClient

    from app import main

    body = TestClient(main.app).get("/health").json()
    assert body["vision_model"] == GROQ_MODEL
    assert "unit-test-key" not in json.dumps(body)
