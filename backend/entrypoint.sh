#!/bin/sh
set -e

# Runs as root (see Dockerfile). The static_data named volume is created
# root-owned by Docker on first mount, and appuser can't write into it
# (needed for collectstatic) without this chown. Everything after this
# point — migrate, collectstatic, gunicorn, celery, pytest, whatever the
# caller passed as CMD/command — runs as appuser, never root.
mkdir -p /app/staticfiles
chown -R appuser:appuser /app/staticfiles

exec gosu appuser "$@"
