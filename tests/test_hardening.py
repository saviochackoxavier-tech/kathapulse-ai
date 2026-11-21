"""Production hardening: schema occlusion, container posture, ingress rules, i18n.

Container and proxy checks are static on purpose. This sandbox has a Docker CLI
but no access to the daemon (``/var/run/docker.sock`` is root-only), so the
Dockerfile cannot be built here; parsing it is the honest alternative, and it
still fails the build of this suite if someone drops ``USER`` or bakes a secret
into an image layer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import i18n, languages, main
from app.schemas import Language

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(main.app)

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


# ---------------------------------------------------------------------------
# Schema occlusion
# ---------------------------------------------------------------------------


def test_api_docs_are_hidden_by_default(monkeypatch):
    monkeypatch.delenv("KATHA_DOCS_ENABLED", raising=False)
    for path in DOCS_PATHS:
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json() == {"detail": "Not Found"}
        # The 404 must not be cacheable either.
        assert response.headers["cache-control"].startswith("no-store")
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_api_docs_can_be_enabled_for_private_deploys(monkeypatch, value):
    monkeypatch.setenv("KATHA_DOCS_ENABLED", value)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_hiding_docs_does_not_affect_real_routes(monkeypatch):
    monkeypatch.delenv("KATHA_DOCS_ENABLED", raising=False)
    assert client.get("/health").status_code == 200
    assert client.get("/taxonomy.json").status_code == 200
    assert client.get("/sw.js").status_code == 200


# ---------------------------------------------------------------------------
# Language registry + i18n coverage
# ---------------------------------------------------------------------------


def test_registry_codes_are_unique_and_enabled_matches_the_api_enum():
    codes = [spec.code for spec in languages.LANGUAGES]
    assert len(codes) == len(set(codes))
    assert set(languages.enabled_codes()) == {language.value for language in Language}


def test_registry_records_script_family_and_tts_locale_for_every_language():
    for spec in languages.LANGUAGES:
        assert spec.script and spec.family
        assert re.fullmatch(r"[a-z]{2}-[A-Z]{2}", spec.tts_locale), spec.code
        assert spec.status in {"live", "planned"}


def test_enabled_languages_are_fully_translated():
    for code in languages.enabled_codes():
        report = i18n.coverage(code)
        assert report["missing"] == [], (code, report["missing"])
        assert report["percent"] == 100.0


def test_planned_languages_fall_back_to_english_instead_of_crashing():
    assert "ta" in languages.planned_codes()
    assert i18n.coverage("ta")["percent"] == 0.0
    # A partial rollout must still produce a safe, readable warning.
    text = i18n.t("disclaimer", "ta")
    assert text == i18n.t("disclaimer", "en")
    assert i18n.t("disclaimer", "xx-x") == i18n.t("disclaimer", "en")


def test_missing_keys_reports_a_real_gap():
    # A language that is absent everywhere must report every key, not an empty list.
    assert len(i18n.missing_keys("zz")) == len(i18n.TEXTS)


# ---------------------------------------------------------------------------
# Container posture (static)
# ---------------------------------------------------------------------------


def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_container_runs_as_an_unprivileged_user():
    body = dockerfile()
    user_lines = [line for line in body.splitlines() if line.strip().upper().startswith("USER ")]
    assert user_lines, "Dockerfile must switch to a non-root user"
    assert "root" not in user_lines[-1].lower()
    assert "10001" in body  # fixed uid, so host volume ownership is predictable
    # The switch must happen after the install, not be undone later.
    assert body.index("USER ") < body.index("CMD ")


def test_container_declares_a_healthcheck_and_no_baked_secrets():
    body = dockerfile()
    assert re.search(r"^HEALTHCHECK[\s\S]{0,400}/health", body, re.MULTILINE)
    # Secrets may only arrive at runtime. The usage comment in the header is
    # allowed to mention the flag; an ENV/ARG/COPY of one is not.
    assert not re.search(
        r"^\s*(ENV|ARG)\s+.*KATHA_(VISION_API_KEY|RELAY_SECRET)", body, re.MULTILINE
    )
    assert "COPY . " not in body, "a blanket COPY could pull .env into a layer"
    assert "COPY app ./app" in body and "COPY static ./static" in body
    assert "--no-cache-dir" in body  # no pip cache layer in the image
    assert "PYTHONDONTWRITEBYTECODE=1" in body


def test_build_context_excludes_secrets_tests_and_the_venv():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip().rstrip("/") for line in ignored if line.strip() and not line.startswith("#")}
    for required in (".env", ".git", ".venv", "tests", "__pycache__"):
        assert required in entries, required


def test_runtime_dependencies_are_exactly_pinned():
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines
    for line in lines:
        assert "==" in line, line
        assert not re.search(r"[<>~!]=|!=|\^|~", line.split("==")[0]), line


# ---------------------------------------------------------------------------
# Ingress rules (documented, checked for the rules that matter)
# ---------------------------------------------------------------------------


def test_nginx_config_enforces_tls_hsts_rate_limits_and_docs_occlusion():
    body = (ROOT / "deploy" / "nginx.kathapulse.conf").read_text(encoding="utf-8")
    assert 'Strict-Transport-Security "max-age=63072000' in body
    assert "limit_req_zone" in body
    assert re.search(r"limit_req\s+zone=kp_scan", body)
    assert "server_tokens off;" in body
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert f"location = {path}" in body and "return 404;" in body
    # WebSocket handshake for the relay must be explicit or it silently fails.
    assert "proxy_set_header Upgrade    $http_upgrade;" in body
    assert "proxy_set_header Connection $connection_upgrade;" in body
    # Upload ceiling stays just above the app's own limit so the app's 413 wins.
    assert "client_max_body_size 7m;" in body
    assert "proxy_request_buffering off;" in body


def test_cloudflare_runbook_covers_the_same_rules():
    body = (ROOT / "deploy" / "cloudflare-rules.md").read_text(encoding="utf-8").lower()
    for needle in ("always use https", "hsts", "rate limiting", "/openapi.json",
                   "bot fight mode", "under attack mode", "cache"):
        assert needle in body, needle
