#!/usr/bin/env python
"""Live end-to-end vision check.

Posts a real medicine-strip JPEG to the running server and prints what the
vision tier extracted. This is the verification the pass-by-pass loop needs:
`manual_required` means the Groq call did not happen or did not resolve.

Usage
-----
    # 1. put the key somewhere the process can see it (never in git):
    #    Settings -> Project settings -> Secrets, or .env  (gitignored)
    # 2. generate a sample strip if you have none:
    cd tests/js && node make-sample-strip.mjs && cd ../..
    # 3. run it:
    ./.venv/bin/python scripts/check_vision.py
    ./.venv/bin/python scripts/check_vision.py --image samples/mystrip.jpg --lang hi

Exit code 0 = the vision tier produced taxonomy-matched medicines.
It never prints the API key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def build_multipart(image_bytes: bytes, filename: str, language: str) -> tuple[bytes, str]:
    boundary = "----katha" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    tail = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="language"\r\n\r\n'
        f"{language}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return head + image_bytes + tail, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=str(ROOT / "samples" / "strip-dolo.jpg"))
    parser.add_argument("--lang", default="ml", choices=["ml", "hi", "en"])
    parser.add_argument("--url", default=None)
    args = parser.parse_args()

    port = os.getenv("PORT", "3004")
    url = args.url or f"http://127.0.0.1:{port}/verify-strip"

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"image not found: {image_path}")
        print("generate one:  cd tests/js && node make-sample-strip.mjs")
        return 2

    cfg = config.vision_settings()
    print("vision tier :", "configured" if cfg.configured else "NOT configured")
    print("endpoint    :", cfg.base_url)
    print("model       :", cfg.model)
    print("key         :", "present (value never printed)" if cfg.configured else "missing")
    if not cfg.configured:
        print(
            "\nSet KATHA_VISION_API_KEY in Settings -> Project settings -> Secrets,\n"
            "or as a line in .env (gitignored). Then re-run this script.\n"
        )

    body, content_type = build_multipart(image_path.read_bytes(), image_path.name, args.lang)
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read()[:400].decode(errors='replace')}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"request failed: {type(exc).__name__}: {exc}")
        print("is the server running?  ./scripts/serve.sh")
        return 1

    status = payload.get("extraction_status")
    source = payload.get("extraction_source")
    print("\nstatus      :", status)
    print("source      :", source)
    print("in-memory   :", payload.get("processed_in_memory"))
    print("verdict     :", payload.get("safety", {}).get("verdict"))

    for medicine in payload.get("medicines", []):
        if medicine.get("matched"):
            parts = [
                f"{i['name_en']} {i.get('strength_mg')} mg" for i in medicine["ingredients"]
            ]
            print(f"  strip     : {medicine['label']} -> {', '.join(parts)}")
        else:
            print(f"  strip     : {medicine['label']} -> (unresolved)")

    speech = payload.get("safety_message_ml", "")
    if speech:
        print("speech (ml) :", speech[:140])

    ok = status in {"ok", "partial"} and any(m.get("matched") for m in payload.get("medicines", []))
    print("\nRESULT      :", "PASS — vision extraction worked" if ok else "FAIL — manual_required")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
