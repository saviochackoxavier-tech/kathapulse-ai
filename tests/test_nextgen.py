"""Next-gen surface: offline feed, batch basket scan, zero-retention relay.

Everything here is still a stub-level feature, so the tests are contract tests:
the shapes are stable, the privacy guarantees hold, and nothing needs a network
or a vision key to pass.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main, relay


def jpeg_bytes(size: int = 1024) -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Offline shell
# ---------------------------------------------------------------------------


def test_taxonomy_feed_is_public_data_only():
    response = client.get("/taxonomy.json")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["drugs"]) > 40
    first = body["drugs"][0]
    assert {"canonical", "name_en", "name_ml", "name_hi", "aliases"} <= set(first)
    # A public feed must never leak configuration.
    assert "api_key" not in json.dumps(body).lower()


def test_service_worker_is_served_from_root_with_scope_header():
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"].startswith("no-store")
    assert "javascript" in response.headers["content-type"]
    assert "CACHE_VERSION" in response.text
    # The offline shell must never attempt to cache a scan POST.
    assert 'request.method !== "GET"' in response.text


def test_service_worker_precaches_taxonomy_and_shell():
    body = client.get("/sw.js").text
    for asset in ("/static/css/styles.css", "/static/js/app.js", "/taxonomy.json"):
        assert asset in body


# ---------------------------------------------------------------------------
# Batch basket scanning
# ---------------------------------------------------------------------------


def test_batch_scan_returns_each_strip_plus_a_combined_verdict():
    response = client.post(
        "/verify-strips/batch",
        files=[
            ("strips", ("one.jpg", jpeg_bytes(), "image/jpeg")),
            ("strips", ("two.jpg", jpeg_bytes(2048), "image/jpeg")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["strip_count"] == 2
    assert [strip["strip_index"] for strip in body["strips"]] == [0, 1]
    assert body["processed_in_memory"] is True
    assert body["image_bytes_received"] == 1024 + 2048
    # No vision key here: both strips are honestly unreadable, never invented.
    assert body["combined"]["verdict"] == "unknown"
    assert body["combined"]["speech"]["text"]


def test_batch_accepts_a_five_strip_basket():
    files = [("strips", (f"{i}.jpg", jpeg_bytes(), "image/jpeg")) for i in range(5)]
    response = client.post("/verify-strips/batch", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["strip_count"] == 5
    assert [strip["strip_index"] for strip in body["strips"]] == [0, 1, 2, 3, 4]


def test_batch_rejects_more_than_five_strips():
    files = [("strips", (f"{i}.jpg", jpeg_bytes(), "image/jpeg")) for i in range(6)]
    response = client.post("/verify-strips/batch", files=files)
    assert response.status_code == 413
    assert "5" in response.json()["detail"]


def test_batch_rejects_an_empty_basket():
    response = client.post("/verify-strips/batch", files=[])
    assert response.status_code == 422


def test_batch_validates_each_upload_like_a_single_scan():
    response = client.post(
        "/verify-strips/batch",
        files=[
            ("strips", ("ok.jpg", jpeg_bytes(), "image/jpeg")),
            ("strips", ("fake.jpg", b"not an image", "image/jpeg")),
        ],
    )
    assert response.status_code == 415


def test_basket_analysis_catches_a_cross_strip_duplicate():
    from app import clinical, extraction

    first = [extraction.resolve_medicine("Telma 40", ["Telma 40"], 0)]
    second = [extraction.resolve_medicine("Telma-H 40/12.5", ["Telma-H 40/12.5"], 1)]
    from app.schemas import Language

    report = clinical.analyse_basket([first, second], Language.malayalam)
    assert len(report.per_strip) == 2
    # Each strip alone is unremarkable...
    assert all(strip.verdict != "critical" for strip in report.per_strip)
    # ...the basket is not.
    assert report.combined.verdict == "critical"
    codes = {finding.code for finding in report.combined.findings}
    assert "DUPLICATE_SALT" in codes


# ---------------------------------------------------------------------------
# Pharmacist relay (zero retention)
# ---------------------------------------------------------------------------


def test_relay_ticket_round_trip_and_rejections(monkeypatch):
    monkeypatch.setenv("KATHA_RELAY_SECRET", "test-secret-value-1234567890")
    ticket = relay.issue_ticket("kochi-7")
    assert relay.verify_ticket("kochi-7", ticket) is True
    assert relay.verify_ticket("kochi-8", ticket) is False
    assert relay.verify_ticket("kochi-7", "garbage") is False
    assert relay.verify_ticket("kochi-7", ticket, now=10**10) is False


def test_relay_refuses_when_unconfigured(monkeypatch):
    monkeypatch.delenv("KATHA_RELAY_SECRET", raising=False)
    assert relay.configured() is False
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/relay/kochi-1?ticket=whatever"):
            pass


def test_relay_refuses_a_forged_ticket(monkeypatch):
    monkeypatch.setenv("KATHA_RELAY_SECRET", "test-secret-value-1234567890")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/relay/kochi-2?ticket=999.deadbeef"):
            pass


def test_relay_forwards_to_peers_and_keeps_nothing(monkeypatch):
    monkeypatch.setenv("KATHA_RELAY_SECRET", "test-secret-value-1234567890")
    ticket = relay.issue_ticket("kochi-demo")
    with client.websocket_connect(f"/ws/relay/kochi-demo?ticket={ticket}") as patient:
        with client.websocket_connect(f"/ws/relay/kochi-demo?ticket={ticket}") as pharmacist:
            patient.send_text("Telma 40 + Telma-H: ഇരട്ട")
            assert pharmacist.receive_text() == "Telma 40 + Telma-H: ഇരട്ട"
    # The hub holds no transcript: rooms are dropped when the last peer leaves.
    assert relay.HUB.peer_count("kochi-demo") == 0
    assert set(relay.HUB.stats()) == {"rooms", "peers"}


def test_relay_drops_oversized_frames(monkeypatch):
    monkeypatch.setenv("KATHA_RELAY_SECRET", "test-secret-value-1234567890")
    ticket = relay.issue_ticket("kochi-big")
    with client.websocket_connect(f"/ws/relay/kochi-big?ticket={ticket}") as patient:
        with client.websocket_connect(f"/ws/relay/kochi-big?ticket={ticket}") as pharmacist:
            patient.send_text("x" * (relay.MAX_MESSAGE_BYTES + 10))
            patient.send_text("short")
            assert pharmacist.receive_text() == "short"
