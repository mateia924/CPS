#!/bin/sh
# Sprint 6.0.1-B: thin repo-root wrapper — see scripts/check-brand.sh for
# why the real logic lives under frontend/scripts/ instead.
set -e
cd "$(dirname "$0")/../frontend"
sh scripts/check-money.sh
