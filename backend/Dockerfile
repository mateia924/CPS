FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 gettext gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
