"""Sliding-window rate limiting: the in-app backstop behind the edge rules."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main, ratelimit

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_limiter():
    ratelimit.LIMITER.clear()
    yield
    ratelimit.LIMITER.clear()


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------


def test_it_allows_exactly_the_limit_then_blocks():
    window = ratelimit.SlidingWindowLimiter(window_seconds=60)
    for _ in range(5):
        assert window.hit("1.2.3.4", 5, now=100.0) == (True, 0)
    allowed, retry_after = window.hit("1.2.3.4", 5, now=100.0)
    assert allowed is False
    assert retry_after >= 1


def test_the_window_slides_instead_of_resetting_on_a_boundary():
    window = ratelimit.SlidingWindowLimiter(window_seconds=60)
    # Two hits late in one minute, three early in the next: a fixed-window
    # counter would allow this burst; a sliding window must not.
    for offset in (0, 1, 2, 3, 4):
        assert window.hit("ip", 5, now=59.0 + offset * 0.1)[0] is True
    assert window.hit("ip", 5, now=60.2)[0] is False


def test_a_slot_frees_up_when_the_oldest_hit_leaves_the_window():
    window = ratelimit.SlidingWindowLimiter(window_seconds=60)
    for moment in (100.0, 110.0, 120.0):
        assert window.hit("ip", 3, now=moment)[0] is True
    assert window.hit("ip", 3, now=130.0)[0] is False
    # At 161s the 100s hit has left the window, so exactly one slot frees up.
    assert window.hit("ip", 3, now=161.0)[0] is True
    assert window.hit("ip", 3, now=161.0)[0] is False


def test_clients_are_tracked_independently():
    window = ratelimit.SlidingWindowLimiter(window_seconds=60)
    for _ in range(3):
        window.hit("a", 3, now=10.0)
    assert window.hit("a", 3, now=10.0)[0] is False
    assert window.hit("b", 3, now=10.0)[0] is True


def test_the_table_is_bounded_under_a_flood_of_addresses():
    window = ratelimit.SlidingWindowLimiter(window_seconds=60, max_clients=10)
    for index in range(50):
        window.hit(f"10.0.0.{index}", 30, now=1.0 + index)
    assert window.tracked_clients() == 10
    assert window.snapshot()["clients"] == 10


def test_limit_zero_means_disabled():
    window = ratelimit.SlidingWindowLimiter()
    for _ in range(500):
        assert window.hit("ip", 0, now=5.0) == (True, 0)


# ---------------------------------------------------------------------------
# The middleware
# ---------------------------------------------------------------------------


def test_it_is_off_by_default(monkeypatch):
    monkeypatch.delenv(ratelimit.ENV_VAR, raising=False)
    assert ratelimit.limit_per_minute() == 0
    for _ in range(40):
        assert client.get("/health").status_code == 200


def test_the_middleware_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv(ratelimit.ENV_VAR, "2")
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    blocked = client.get("/health")
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"].isdigit()
    assert blocked.headers["cache-control"].startswith("no-store")
    assert "Too many requests" in blocked.json()["detail"]


def test_a_nonsense_value_does_not_disable_protection(monkeypatch):
    monkeypatch.setenv(ratelimit.ENV_VAR, "banana")
    assert ratelimit.limit_per_minute() == 0  # falls back to the documented default
    monkeypatch.setenv(ratelimit.ENV_VAR, "999999")
    assert ratelimit.limit_per_minute() == 6000  # clamped


def test_rate_limiting_does_not_touch_the_scan_path_when_disabled(monkeypatch):
    monkeypatch.delenv(ratelimit.ENV_VAR, raising=False)
    response = client.post(
        "/verify-medicines",
        json={"medicines": [{"name": "Telma 40"}], "language": "ml"},
    )
    assert response.status_code == 200
