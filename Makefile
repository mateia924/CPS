.PHONY: dev-up dev-down dev-logs dev-build prod-up prod-down prod-config dev-config test lint check smoke backup e2e migrate

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

## Sprint 6.5.16 (incident: 6.5.15's six data migrations ran with no
## prior backup — scripts/backup.sh only ran once, after the fact).
## backup.sh first, then migrate — and apps.tenants's own migrate
## command override refuses to apply any pending migration on a real
## (non-test) database without a backups.log entry newer than 15
## minutes anyway, so this target is the convenient path, not the only
## enforcement; a bare `manage.py migrate` is guarded the same way.
migrate:
	./scripts/backup.sh "make migrate"
	$(DC) $(DEV) exec backend python manage.py migrate

## Brand/money/forms structural checks (sprint 6.0.1, permanent rules
## 1-4; forms check added 6.5.6): zero literal colors outside
## tokens.css, tokens.css matches docs/brand/tokens.css, WCAG AA
## contrast, no raw money field without <Money>, no raw
## input/select/textarea outside FormField and no raw field-name error
## dump. Runs against the already-running dev frontend service
## (`make dev-up` first) — node_modules live there via its volume.
check:
	$(DC) $(DEV) exec frontend npm run check-brand
	$(DC) $(DEV) exec frontend npm run check-money
	$(DC) $(DEV) exec frontend npm run check-forms
	$(DC) $(DEV) exec frontend npm run check-entity-default

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

## Real headless-browser E2E suite (sprint 6.5.8, docs/CPS_MASTER_PLAN.md
## §9.3) — required for any block that touches the UI. Creates and
## archives its own smoke-* tenant; never touches a real one. See
## scripts/e2e.sh and frontend/e2e/*.spec.ts.
e2e:
	./scripts/e2e.sh

## Prod (future production host only — never run on this dev host)
prod-up:
	$(DC) $(PROD) up -d --build

prod-down:
	$(DC) $(PROD) down

prod-config:
	$(DC) $(PROD) config
