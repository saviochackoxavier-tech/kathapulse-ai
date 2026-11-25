#!/usr/bin/env bash
# KathaPulse AI — clean, secret-free submission archive.
#
# Builds a ZIP from the files tracked at HEAD (`git archive`), so untracked
# local state — the real `.env`, the virtualenv, caches, screenshots — can never
# be included. It then refuses to leave the archive behind if a forbidden path
# or a real credential shape is found inside it.
#
# Usage:
#   ./scripts/make_submission_archive.sh
#   OUT_DIR=/tmp ./scripts/make_submission_archive.sh
#
# Output: $OUT_DIR/kathapulse-ai-<tag>.zip  (default: artifacts/, git-ignored)
# Exit:   0 clean · non-zero refused/failed (the bad archive is deleted)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/artifacts}"
TAG="$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || echo snapshot)"
NAME="kathapulse-ai-$TAG"
ZIP="$OUT_DIR/$NAME.zip"

mkdir -p "$OUT_DIR"
rm -f "$ZIP"

git -C "$ROOT" archive --format=zip --prefix="$NAME/" -o "$ZIP" HEAD

if ! command -v unzip >/dev/null 2>&1; then
  echo "[archive] unzip is required to verify the archive" >&2
  rm -f "$ZIP"
  exit 1
fi

LIST="$(unzip -Z1 "$ZIP")"

# 1. Forbidden paths: secrets, environments, dependencies, build artefacts.
FORBIDDEN="$(printf '%s\n' "$LIST" | grep -E \
  '(^|/)(\.env$|\.venv/|__pycache__/|node_modules/|\.git/|artifacts/|dist/)|\.pem$|\.key$|(^|/)secret' \
  || true)"
if [ -n "$FORBIDDEN" ]; then
  echo "[archive] REFUSED — forbidden path(s) inside the archive:" >&2
  printf '%s\n' "$FORBIDDEN" >&2
  rm -f "$ZIP"
  exit 1
fi

# 2. Real credential shapes only.
#    Deliberately not matching documentation placeholders such as
#    `KATHA_VISION_API_KEY=gsk_...`, `<set this in Secrets>` or `=stub`.
SECRET_PATTERNS='(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|KATHA_VISION_API_KEY=[A-Za-z0-9_-]{20,}|KATHA_RELAY_SECRET=[A-Za-z0-9]{16,})'
if unzip -p "$ZIP" | grep -aEq "$SECRET_PATTERNS"; then
  echo "[archive] REFUSED — a credential-shaped string is inside the archive" >&2
  echo "[archive] value not printed; inspect tracked files with: git grep -nE '<pattern>'" >&2
  rm -f "$ZIP"
  exit 1
fi

FILES="$(printf '%s\n' "$LIST" | grep -cEv '/$' || true)"
echo "[archive] clean: $ZIP"
echo "[archive] files: $FILES"
echo "[archive] commit: $(git -C "$ROOT" rev-parse --short HEAD) ($TAG)"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ZIP"
else
  shasum -a 256 "$ZIP"
fi
