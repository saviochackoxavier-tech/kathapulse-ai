"""Runtime configuration.

Everything is read from the environment **at call time**, not at import time, so
a key added to `.env` (or to the process environment) takes effect without a
code change or a restart dance.  No dependency is used for the `.env` parse: it
is thirty lines of parsing and keeps the image free of python-dotenv.

Secrets are never logged, echoed or returned. `/health` exposes only whether a
tier is configured, never the value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse KEY=VALUE lines into os.environ without overriding real env vars.

    Real environment always wins: on a host (Freebuff, Docker, systemd) the
    platform's variables must not be shadowed by a stray file in the repo.
    """
    target = path or ENV_FILE
    loaded: dict[str, str] = {}
    if not target.exists():
        return loaded

    try:
        for raw in target.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key or key in os.environ:
                continue
            os.environ[key] = value
            loaded[key] = value
    except OSError:
        # An unreadable .env must not take the service down; the app degrades
        # to the manual-entry tier, which is still clinically correct.
        return loaded
    return loaded


# Load once on import so the first request already sees the file.
load_env_file()


@dataclass(frozen=True)
class VisionSettings:
    api_key: str
    base_url: str
    model: str
    timeout_s: float
    json_mode: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def vision_settings() -> VisionSettings:
    """Current vision-tier configuration (re-read on every call)."""
    return VisionSettings(
        api_key=os.getenv("KATHA_VISION_API_KEY", "").strip(),
        base_url=os.getenv("KATHA_VISION_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        model=os.getenv("KATHA_VISION_MODEL", "gpt-4o-mini").strip(),
        timeout_s=float(os.getenv("KATHA_VISION_TIMEOUT_S", "12")),
        json_mode=os.getenv("KATHA_VISION_JSON_MODE", "0").strip().lower()
        in {"1", "true", "yes"},
    )


def docs_enabled() -> bool:
    """Expose /docs, /redoc and /openapi.json? Off unless explicitly enabled.

    A public safety tool has no reason to publish its schema; hiding it is the
    app-side half of the ingress rule that blocks those paths at the proxy.
    """
    return os.getenv("KATHA_DOCS_ENABLED", "0").strip().lower() in {"1", "true", "yes"}


def ocr_enabled() -> bool:
    """True when the local OCR tier is switched on and its library imports."""
    if os.getenv("KATHA_OCR_DISABLED", "").strip() in {"1", "true", "yes"}:
        return False
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return True
