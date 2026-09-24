#!/bin/sh
# Sprint 6.0.1-A: fails if (1) any literal hex/rgb/hsl color exists in
# frontend/src outside tokens.css, (2) the app's tokens.css has drifted
# from docs/brand/tokens.css, or (3) any AA contrast pair fails.
# Run from the frontend/ directory (matches CI's working-directory and
# the Dockerfile builder stage's context).
set -e

FAIL=0

echo "== check-brand: literal colors in frontend/src =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' -o -name '*.css' \) -type f \
  ! -path 'src/styles/tokens.css' \
  -exec grep -nE '#[0-9a-fA-F]{3,8}\b|rgb\(|rgba\(|hsl\(' {} + || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: literal colors found outside src/styles/tokens.css"
  FAIL=1
else
  echo "PASS: zero literal colors outside src/styles/tokens.css"
fi

echo ""
echo "== check-brand: src/styles/tokens.css matches docs/brand/tokens.css =="
# docs/brand/tokens.css lives one level above the frontend/ Docker build
# context (context: ../frontend in docker-compose.yml) and isn't copied
# into the production image build — only available when the full repo
# checkout is present (local dev, CI). Skip gracefully rather than fail
# when it's genuinely unreachable.
SOURCE_TOKENS="../docs/brand/tokens.css"
if [ -f "$SOURCE_TOKENS" ]; then
  if diff -q "$SOURCE_TOKENS" src/styles/tokens.css > /dev/null; then
    echo "PASS: src/styles/tokens.css is an exact copy of docs/brand/tokens.css"
  else
    diff "$SOURCE_TOKENS" src/styles/tokens.css || true
    echo "FAIL: src/styles/tokens.css differs from docs/brand/tokens.css"
    FAIL=1
  fi
else
  echo "SKIP: docs/brand/tokens.css not reachable from this build context (expected in the Docker production build; not a failure)"
fi

echo ""
echo "== check-brand: WCAG AA contrast =="
if ! node scripts/contrast-check.mjs; then
  FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-brand: FAILED"
  exit 1
fi
echo ""
echo "check-brand: all checks passed"
