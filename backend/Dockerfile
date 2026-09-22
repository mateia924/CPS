FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 gettext gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sprint 4.0 (ARCH_REVIEW_1.md debt from the immediate-fixes review): the
# dev stage bakes requirements-dev.txt (pytest/ruff/factory-boy) into the
# image so a persistent `docker compose ... up -d` backend container can
# run `ruff check .` / `pytest` directly — `make lint`/`make test` still
# work too (they use a throwaway container with a fresh pip install,
# useful in CI where this stage isn't built). Not used for `prod`.
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN chmod +x entrypoint.sh
RUN useradd --create-home --uid 1000 appuser
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

# Default (unspecified) build target — what docker-compose.prod.yml gets.
# Deliberately excludes requirements-dev.txt from the shipped image.
FROM base AS prod

COPY . .
RUN chmod +x entrypoint.sh

RUN useradd --create-home --uid 1000 appuser

EXPOSE 8000

# Stays root at container start on purpose: entrypoint.sh needs root to
# chown the static_data named volume (created root-owned by Docker) once,
# then drops to appuser via gosu before exec'ing the real command (see
# entrypoint.sh). Neither gunicorn nor celery ever run as root.
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
