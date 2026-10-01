.PHONY: dev-up dev-down dev-logs dev-build dev-config prod-up prod-down prod-config test lint check smoke backup restore-test e2e migrate deploy staging-up staging-down staging-refresh staging-config

COMPOSE_DIR := infra
ENV_FILE := .env
STAGING_ENV_FILE := .env.staging
BASE := -f $(COMPOSE_DIR)/docker-compose.yml
# Sprint 6.6.0: three separate overlays, three separate compose
# projects — "infra" (unchanged name, the same containers/volumes this
# host has always run under) for LOCAL (live, no-reload, port 3000,
# scripts/deploy.sh-managed only); "cps-dev" for the interactive
# sandbox (hot-reload, port 3002, own independent stack — never UAT,
# never Fatma/acme, see §0 rule 3); "cps-staging" for staging (port
# 3001, own independent stack, refreshed from a dev backup).
LOCAL := $(BASE) -f $(COMPOSE_DIR)/docker-compose.local.yml
DEV := -p cps-dev $(BASE) -f $(COMPOSE_DIR)/docker-compose.dev.yml
STAGING := -p cps-staging $(BASE) -f $(COMPOSE_DIR)/docker-compose.staging.yml
PROD := $(BASE) -f $(COMPOSE_DIR)/docker-compose.prod.yml
DC := docker compose --env-file $(ENV_FILE)
DC_STAGING := docker compose --env-file $(STAGING_ENV_FILE)

## Interactive dev sandbox (sprint 6.6.0) — hot-reload, bind-mounted
## source, its own independent stack on port 3002. Never UAT: create
## and use smoke-* tenants here (§0 rule 3), never Fatma/acme.
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

## Tests run against the dev sandbox's own Postgres service (starts it
## via depends_on if not already up), in a separate test_<db> database
## pytest-django creates and drops automatically — never SQLite, never
## the local/live stack. The throwaway test/lint container bypasses
## entrypoint.sh's non-root privilege-drop (--entrypoint '') since it's
## a one-off run, not a persistent service; dev deps aren't baked into
## the image, so each run installs them fresh.
##
## `--create-db`: found (and reproduced, in a concurrent/overlapping-
## runs scenario — NOT confirmed as CI run #43's own actual cause,
## which a faithful from-scratch `dev-up` -> `lint` -> `test` sequence
## never reproduced) that a `make test` interrupted before pytest-
## django's own teardown (timeout, cancelled job, Ctrl-C) leaves
## test_<db> behind; the NEXT run against the same Postgres then hits
## `psycopg.errors.DuplicateDatabase` immediately, which pytest-django
## turns into a bare `SystemExit(2)`. `--create-db` forces a fresh
## DROP + CREATE every run regardless of what a prior run left behind
## — a real, harmless hardening either way, whether or not it turns
## out to be what CI #43 actually hit.
test:
	$(DC) $(DEV) run --rm --entrypoint '' backend sh -c "pip install -q -r requirements-dev.txt && pytest -v --create-db"

lint:
	$(DC) $(DEV) run --rm --entrypoint '' backend sh -c "pip install -q -r requirements-dev.txt && ruff check ."

## Sprint 6.6.0: migrating the dev sandbox directly is still fine (its
## own throwaway database) — but the LOCAL stack (port 3000, what
## deploy.sh serves) is never migrated this way anymore, only through
## `scripts/deploy.sh` itself (backup → build → migrate-with-guard →
## restart → smoke, as one atomic step). apps.tenants's own migrate
## command override still refuses any pending migration on a real
## (non-test) database without a backups.log entry newer than 15
## minutes regardless of which path reaches it.
migrate:
	./scripts/backup.sh "make migrate"
	$(DC) $(DEV) exec backend python manage.py migrate

## Brand/money/forms structural checks (sprint 6.0.1, permanent rules
## 1-4; forms check added 6.5.6): zero literal colors outside
## tokens.css, tokens.css matches docs/brand/tokens.css, WCAG AA
## contrast, no raw money field without <Money>, no raw
## input/select/textarea outside FormField and no raw field-name error
## dump. Runs against the already-running dev sandbox's frontend
## service (`make dev-up` first) — node_modules live there via its volume.
check:
	$(DC) $(DEV) exec frontend npm run check-brand
	$(DC) $(DEV) exec frontend npm run check-money
	$(DC) $(DEV) exec frontend npm run check-forms
	$(DC) $(DEV) exec frontend npm run check-entity-default

## Live-environment smoke test (sprint 5.0, CFO_REVIEW_1 O8) — run this
## after every deploy/restart, before trusting an environment for UAT
## or real use. See scripts/smoke.sh for what it checks and how to
## point it at a different tenant/user/port (SMOKE_BASE_URL etc).
smoke:
	./scripts/smoke.sh

## Daily backup (sprint 5.0, CFO_REVIEW_1 O1) — also runs from root's
## crontab at 03:00 daily; this target is for running it on demand.
backup:
	./scripts/backup.sh

## Automated monthly restore health-check (sprint 6.6.4) — also runs
## from root's crontab on the 1st of each month; this target is for
## running it on demand. See docs/ops/BACKUP.md.
restore-test:
	./scripts/restore_test.sh

## Real headless-browser E2E suite (sprint 6.5.8, docs/CPS_MASTER_PLAN.md
## §9.3) — required for any block that touches the UI. Creates and
## archives its own smoke-* tenant; never touches a real one. See
## scripts/e2e.sh and frontend/e2e/*.spec.ts.
e2e:
	./scripts/e2e.sh

## The ONLY supported way to change what port 3000 (project "infra")
## serves — sprint 6.6.0. See scripts/deploy.sh for the full backup →
## build → migrate-with-guard → restart → smoke sequence and its log
## in docs/ops/deploys.log.
deploy:
	./scripts/deploy.sh

## Staging (sprint 6.6.0) — its own independent stack on port 3001,
## project "cps-staging", .env.staging. Every human UAT session from
## now on happens here, never on port 3000. `staging-refresh` is the
## only way its data ever changes (restore latest dev backup + rewrite
## every user's password to a known UAT value) — never hand-edited.
staging-up:
	$(DC_STAGING) $(STAGING) up -d --build

staging-down:
	$(DC_STAGING) $(STAGING) down

staging-config:
	$(DC_STAGING) $(STAGING) config

staging-refresh:
	./scripts/staging_refresh.sh

## Prod (future production host only — never run on this dev host)
prod-up:
	$(DC) $(PROD) up -d --build

prod-down:
	$(DC) $(PROD) down

prod-config:
	$(DC) $(PROD) config
