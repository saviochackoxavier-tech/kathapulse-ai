"""Local audio pack (draft): manifest contract, precache wiring, load order.

The pack ships with zero clips, so these tests assert the *scaffolding* — that an
empty pack is valid, that the offline shell carries it, and that nothing about
the pack can introduce a remote dependency or a traversal path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import main

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(main.app)


def test_manifest_is_valid_and_ships_empty_by_default():
    response = client.get("/static/audio/manifest.json")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == 1
    assert isinstance(body["version"], str)
    assert isinstance(body["clips"], dict)
    # An empty pack is the safe default: the player reports "unavailable" and
    # speech falls back to the device voice rather than going silent.
    assert body["clips"] == {}
    assert body["note"]


def test_clip_paths_are_relative_and_local():
    body = (ROOT / "static" / "audio" / "manifest.json").read_text(encoding="utf-8")
    for path in json.loads(body)["clips"].values():
        assert path.startswith("/static/audio/"), path
        assert ".." not in path
        assert not re.match(r"^https?://", path)


def test_service_worker_precaches_the_pack_and_bumps_its_version():
    body = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    assert 'CACHE_VERSION = "kathapulse-v2"' in body
    assert "/static/js/audio-pack.js" in body
    assert "/static/audio/manifest.json" in body


def test_page_loads_the_pack_before_the_app():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'src="/static/js/audio-pack.js"' in html
    assert html.index("audio-pack.js") < html.index('src="/static/js/app.js"')
    # A pack script must never be inline: the CSP forbids it.
    assert "<script>" not in html


def test_the_module_exposes_only_the_pack_api():
    body = (ROOT / "static" / "js" / "audio-pack.js").read_text(encoding="utf-8")
    assert "global.AudioPack" in body
    for method in ("load", "canPlay", "play", "stop", "status"):
        assert re.search(rf"\b{method}:", body), method
    # No eval, no remote origin, no service worker writes of patient data.
    assert "eval(" not in body
    assert "https://" not in body
