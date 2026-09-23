.PHONY: dev-up dev-down dev-logs dev-build prod-up prod-down prod-config dev-config test lint smoke backup

COMPOSE_DIR := infra
ENV_FILE := .env
BASE := -f $(COMPOSE_DIR)/docker-compose.yml
DEV := $(BASE) -f $(COMPOSE_DIR)/docker-compose.dev.yml
PROD := $(BASE) -f $(COMPOSE_DIR)/docker-compose.prod.yml
DC := docker compose --env-file $(ENV_FILE)

## Dev (this host — always port 3000, see README "Reserved ports on this host")
dev-up:
	$(DC) $(DEV) up -d --build

dev-down:
	$(DC) $(DEV) down

dev-logs:
	$(DC) $(DEV) logs -f

dev-build:
	$(DC) $(DEV) build

dev-config:
	$(DC) $(DEV) config

## Tests run against the real dev Postgres service (starts it via
## depends_on if not already up), in a separate test_<db> database that
## pytest-django creates and drops automatically — never SQLite. The
## throwaway test/lint container bypasses entrypoint.sh's non-root
## privilege-drop (--entrypoint '') since it's a one-off run, not a
## persistent service; dev deps aren't baked into the image, so each
## run installs them fresh.
test:
	$(DC) $(DEV) run --rm --entrypoint '' backend sh -c "pip install -q -r requirements-dev.txt && pytest -v"

lint:
	$(DC) $(DEV) run --rm --entrypoint '' backend sh -c "pip install -q -r requirements-dev.txt && ruff check ."

## Live-environment smoke test (sprint 5.0, CFO_REVIEW_1 O8) — run this
## after every `docker compose restart backend celery_worker`, before
## trusting the environment for UAT or real use. See scripts/smoke.sh
## for what it checks and how to point it at a different tenant/user.
smoke:
	./scripts/smoke.sh

## Daily backup (sprint 5.0, CFO_REVIEW_1 O1) — also runs from root's
## crontab at 03:00 daily; this target is for running it on demand.
backup:
	./scripts/backup.sh

## Prod (future production host only — never run on this dev host)
prod-up:
	$(DC) $(PROD) up -d --build

prod-down:
	$(DC) $(PROD) down

prod-config:
	$(DC) $(PROD) config
