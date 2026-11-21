#!/usr/bin/env python
"""Throwaway stand-in for GroqCloud's chat-completions endpoint.

Purpose: let the live HTTP path be exercised without a provider credential.
It answers in exactly the shape ``app/extraction.py`` expects, and can be told
to reject one bearer key so the dual-key rotator can be proven against a real
server instead of only against mocks.

    python scripts/_stub_vision.py 3010
    python scripts/_stub_vision.py 3010 reject-primary

It is NOT part of the product and is never started by ``serve.sh``.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CANNED = {
    "medicines": [
        {
            "brand_name": "Telma-H",
            "active_ingredients": ["Telmisartan", "Hydrochlorothiazide"],
            "dosage_strength": "40 mg/12.5 mg",
        }
    ]
}

#: In `reject-primary` mode every key but the last one presented is refused.
MODE = "ok"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send(401, {"error": {"message": "missing bearer"}})
            return

        key = auth.split(" ", 1)[1]
        if MODE == "reject-primary" and key == "primary-demo-key":
            # The scenario the rotator exists for: the first key is rate-limited.
            self._send(429, {"error": {"message": "rate limit exceeded", "code": "rate_limit"}})
            return

        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self._send(400, {"error": {"message": "bad json"}})
            return

        # Assert the contract the app is supposed to send.
        content = payload.get("messages", [{}])[-1].get("content")
        assert isinstance(content, list), "image message must be a content list"
        assert any(part.get("type") == "image_url" for part in content), "no image part"
        data_url = next(p["image_url"]["url"] for p in content if p.get("type") == "image_url")
        assert data_url.startswith("data:image/"), "not a base64 data URL"

        self._send(
            200,
            {
                "id": "stub-1",
                "choices": [
                    {"message": {"role": "assistant", "content": json.dumps(CANNED)}}
                ],
            },
        )

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        sys.stderr.write("[stub] " + fmt % args + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3010
    if len(sys.argv) > 2:
        MODE = sys.argv[2]
    print(f"[stub] listening on 127.0.0.1:{port} mode={MODE}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
