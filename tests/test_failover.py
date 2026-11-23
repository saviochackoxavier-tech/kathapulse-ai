"""Dual-key vision failover: a rejected primary must not take the warning down.

The rotator exists for one scenario: a live demo where the primary Groq key is
rate-limited (429) or revoked (401) mid-scan. These tests script the provider's
answer per key and assert what the client does, with no network and no real key.

What is pinned here:
  * 429 / 401 / 403 on the primary rotates to the fallback and succeeds;
  * the retry carries the *other* key, not the rejected one;
  * both keys unusable → clean `manual_required`, never an exception;
  * one key behaves exactly as before (quiet 429 retry, then degrade);
  * `/health` reports rotation status as counts/booleans, never key material;
  * neither key reaches the logs or a temp file.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, extraction, main

PRIMARY = "primary-test-key-value"
FALLBACK = "fallback-test-key-value"
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

DOLO_REPLY = {
    "choices": [
        {
            "message": {
                "content": '{"medicines":[{"brand_name":"DOLO 650",'
                '"active_ingredients":["Paracetamol"],"dosage_strength":"650 mg"}]}'
            }
        }
    ]
}


# ---------------------------------------------------------------------------
# Stub transport: one scripted response per call
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

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
    """Answers from a queue, recording the Authorization header of each call."""

    calls: list[dict] = []
    queue: list[FakeResponse] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None, **kwargs):
        FakeClient.calls.append({"url": url, "auth": (headers or {}).get("Authorization")})
        if not FakeClient.queue:
            raise AssertionError("more provider calls than scripted responses")
        return FakeClient.queue.pop(0)


@pytest.fixture()
def keys(monkeypatch):
    """Both keys configured; a clean provider script for each test."""
    monkeypatch.setenv("KATHA_VISION_API_KEY", PRIMARY)
    monkeypatch.setenv("KATHA_VISION_API_KEY_FALLBACK", FALLBACK)
    monkeypatch.setenv("KATHA_VISION_BASE_URL", GROQ_BASE)
    monkeypatch.setenv("KATHA_VISION_MODEL", GROQ_MODEL)
    monkeypatch.setenv("KATHA_VISION_JSON_MODE", "0")
    FakeClient.calls = []
    FakeClient.queue = []
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return FakeClient


def scan():
    return asyncio.run(extraction.extract(b"\xff\xd8\xff\xe0strip", "image/jpeg"))


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rejection", [429, 401, 403])
def test_a_rejected_primary_rotates_to_the_fallback_and_extracts(keys, rejection):
    keys.queue = [FakeResponse(rejection), FakeResponse(200, DOLO_REPLY)]

    result = scan()

    assert result.status == "ok", f"{rejection} on the primary did not fail over"
    assert result.source == extraction.ExtractionSource.vision
    assert result.medicines[0].ingredients[0].canonical == "paracetamol"

    assert [c["auth"] for c in keys.calls] == [
        f"Bearer {PRIMARY}",
        f"Bearer {FALLBACK}",
    ], "the retry did not switch keys"


def test_failover_happens_on_the_first_rejection_without_burning_a_retry(keys):
    """A primary with a fallback behind it is abandoned immediately.

    Retrying a rate-limited key only spends the demo's remaining seconds.
    """
    keys.queue = [FakeResponse(429), FakeResponse(200, DOLO_REPLY)]

    started = asyncio.run(_timed_scan())

    assert started["status"] == "ok"
    assert started["calls"] == 2, f"made {started['calls']} calls instead of one per key"
    assert started["seconds"] < 1.0, "failover waited on the rejected key"


async def _timed_scan() -> dict:
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await extraction.extract(b"\xff\xd8\xff\xe0strip", "image/jpeg")
    return {
        "status": result.status,
        "calls": len(FakeClient.calls),
        "seconds": loop.time() - started,
    }


def test_both_keys_rate_limited_retries_only_the_last_key(keys):
    """The two retry policies must not leak into each other.

    Both keys answer 429: the primary is abandoned on its first answer because a
    fallback is waiting, and the fallback — which has nothing behind it — keeps
    the one quiet retry. Three calls, never four, and never a second try at the
    primary.
    """
    keys.queue = [FakeResponse(429), FakeResponse(429), FakeResponse(200, DOLO_REPLY)]

    result = scan()

    assert result.status == "ok"
    assert [c["auth"] for c in keys.calls] == [
        f"Bearer {PRIMARY}",
        f"Bearer {FALLBACK}",
        f"Bearer {FALLBACK}",
    ], "the last key's single retry did not happen, or the primary was retried"


def test_both_keys_rejected_degrades_cleanly(keys):
    keys.queue = [FakeResponse(429), FakeResponse(401)]

    result = scan()

    assert result.status == "manual_required"
    assert result.medicines == []
    assert len(keys.calls) == 2


def test_both_keys_failing_for_the_provider_also_degrades(keys):
    keys.queue = [FakeResponse(500), FakeResponse(500)]

    result = scan()

    assert result.status == "manual_required"


def test_duplicate_keys_are_not_tried_twice(monkeypatch):
    monkeypatch.setenv("KATHA_VISION_API_KEY", PRIMARY)
    monkeypatch.setenv("KATHA_VISION_API_KEY_FALLBACK", PRIMARY)
    for name, value in (
        ("KATHA_VISION_BASE_URL", GROQ_BASE),
        ("KATHA_VISION_MODEL", GROQ_MODEL),
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.calls = []
    FakeClient.queue = [FakeResponse(429)]

    settings = config.vision_settings()
    assert settings.key_count == 1, "the same key configured twice was counted twice"

    result = scan()
    assert result.status == "manual_required"
    # One distinct key means one key's worth of attempts: the quiet 429 retry,
    # then degrade. Never a second copy of the same key.
    assert len(FakeClient.calls) == 2
    assert {c["auth"] for c in FakeClient.calls} == {f"Bearer {PRIMARY}"}


def test_single_key_keeps_the_old_quiet_retry(monkeypatch):
    """With no fallback there is nothing to rotate to, so the 429 retry stays."""
    monkeypatch.setenv("KATHA_VISION_API_KEY", PRIMARY)
    monkeypatch.delenv("KATHA_VISION_API_KEY_FALLBACK", raising=False)
    monkeypatch.setenv("KATHA_VISION_BASE_URL", GROQ_BASE)
    monkeypatch.setenv("KATHA_VISION_MODEL", GROQ_MODEL)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.calls = []
    FakeClient.queue = [FakeResponse(429), FakeResponse(200, DOLO_REPLY)]

    result = scan()

    assert result.status == "ok"
    assert [c["auth"] for c in FakeClient.calls] == [
        f"Bearer {PRIMARY}",
        f"Bearer {PRIMARY}",
    ]


def test_a_fallback_alone_is_enough_to_run(monkeypatch):
    monkeypatch.delenv("KATHA_VISION_API_KEY", raising=False)
    monkeypatch.setenv("KATHA_VISION_API_KEY_FALLBACK", FALLBACK)
    monkeypatch.setenv("KATHA_VISION_BASE_URL", GROQ_BASE)
    monkeypatch.setenv("KATHA_VISION_MODEL", GROQ_MODEL)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.calls = []
    FakeClient.queue = [FakeResponse(200, DOLO_REPLY)]

    result = scan()

    assert result.status == "ok"
    assert FakeClient.calls[0]["auth"] == f"Bearer {FALLBACK}"


def test_no_keys_means_no_network_call(monkeypatch):
    for name in ("KATHA_VISION_API_KEY", "KATHA_VISION_API_KEY_FALLBACK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.calls = []

    assert asyncio.run(extraction._vision_extract(b"\xff\xd8\xff\xe0", "image/jpeg")) is None
    assert FakeClient.calls == []


# ---------------------------------------------------------------------------
# Health: rotation status without secrets
# ---------------------------------------------------------------------------


def test_health_reports_rotation_status_for_two_keys(keys):
    body = TestClient(main.app).get("/health").json()

    assert body["vision_keys"] == 2
    assert body["vision_fallback"] is True
    serialised = json.dumps(body)
    assert PRIMARY not in serialised
    assert FALLBACK not in serialised


def test_health_reports_a_single_key_honestly(monkeypatch):
    monkeypatch.setenv("KATHA_VISION_API_KEY", PRIMARY)
    monkeypatch.delenv("KATHA_VISION_API_KEY_FALLBACK", raising=False)

    body = TestClient(main.app).get("/health").json()

    assert body["vision_keys"] == 1
    assert body["vision_fallback"] is False


def test_health_reports_zero_when_unconfigured(monkeypatch):
    for name in ("KATHA_VISION_API_KEY", "KATHA_VISION_API_KEY_FALLBACK"):
        monkeypatch.delenv(name, raising=False)

    body = TestClient(main.app).get("/health").json()

    assert body["vision_model"] is None
    assert body["vision_keys"] == 0
    assert body["vision_fallback"] is False


# ---------------------------------------------------------------------------
# Secret hygiene and zero persistence
# ---------------------------------------------------------------------------


def test_neither_key_reaches_the_logs(keys, caplog):
    keys.queue = [FakeResponse(429), FakeResponse(401)]

    with caplog.at_level("WARNING"):
        scan()

    assert "unusable" in caplog.text, "failover was not logged at all"
    assert PRIMARY not in caplog.text
    assert FALLBACK not in caplog.text


def test_failover_writes_nothing_to_the_temp_directory(keys, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    keys.queue = [FakeResponse(429), FakeResponse(200, DOLO_REPLY)]

    result = scan()

    assert result.status == "ok"
    assert list(Path(scratch).iterdir()) == [], "a failover left a file on disk"
