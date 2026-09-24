#!/bin/sh
# Sprint 6.0.1-A: thin repo-root wrapper — the actual check lives in
# frontend/scripts/check-brand.sh (it must be inside frontend/ so it
# also runs from the Dockerfile's builder stage and CI, both scoped to
# the frontend/ directory; this wrapper is for `make check` at the repo
# root and for anyone running it by the path this project's docs use).
set -e
cd "$(dirname "$0")/../frontend"
sh scripts/check-brand.sh
