.PHONY: dev-up dev-down dev-logs dev-build dev-config prod-up prod-down prod-config test lint check smoke backup restore-test e2e migrate deploy staging-up staging-down staging-refresh staging-config

# Sprint 6.6.5 (CI #46): absolute, anchored to wherever `make` itself
# was invoked from (repo root, by every existing convention here) —
# evaluated once, so a recipe that `cd`s elsewhere first (test/lint's
# own `cd backend`, needed for the native/no-RUN branch) can't break
# these paths' resolution the way plain relative ones would.
REPO_ROOT := $(CURDIR)
COMPOSE_DIR := $(REPO_ROOT)/infra
ENV_FILE := $(REPO_ROOT)/.env
STAGING_ENV_FILE := $(REPO_ROOT)/.env.staging
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

## Sprint 6.6.5 (CI #46): lint/test run through $(RUN), which the
## interactive dev sandbox and CI point at two different things — "the
## checks are ONE; the dev sandbox runs them inside the already-built
## `cps-dev` backend container, CI runs them natively on the runner"
## (README). Default (RUN unset): exec into the already-running
## persistent `cps-dev` backend container (`make dev-up` first) — its
## `dev` build target already bakes in requirements-dev.txt (pytest/
## ruff/factory-boy), so no per-run pip install is needed, unlike the
## old throwaway `run --rm --entrypoint ''` container this replaced.
## CI overrides `RUN=` (empty, via ci.yml's job-level `env:`) — make's
## `?=` only applies when a variable is COMPLETELY unset, so an
## environment-provided empty string is honored, not defaulted — which
## makes `$(RUN) pytest ...`/`$(RUN) ruff ...` below reduce to a bare
## shell command, executed directly on the runner (no docker compose,
## no .env, no image build at all): CI #46's actual root cause — every
## `make` target unconditionally went through `docker compose -p
## cps-dev`, which needs a real `.env` and a from-scratch image build,
## neither of which exists nor is wanted on a GitHub-hosted runner.
RUN ?= $(DC) $(DEV) exec -T backend

## `cd backend` only matters for the native (RUN empty) branch, where
## `make` itself runs from the repo root — inside the container, exec
## already starts at its own WORKDIR (/app, == this repo's backend/),
## so the `cd` is a harmless no-op there (host-side chdir, irrelevant
## to what the exec'd command's own cwd is).
test:
	cd backend && $(RUN) pytest -v --create-db

## Sprint 7.0 (CI #56): the `clamav`-marked tests (a real ClamAV round
## trip) — excluded from `test` above by pyproject.toml's own default
## marker filter. Needs a dev/staging box with the `clamav` service
## actually running (never CI). Run before every live deploy
## (docs/ops/DEPLOY.md).
test-integration:
	cd backend && $(RUN) pytest -v -m clamav

lint:
	cd backend && $(RUN) ruff check .

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
	$(DC) $(DEV) exec frontend npm run check-dates
	$(DC) $(DEV) exec frontend npm run check-arabic-ui
	$(DC) $(DEV) exec frontend npm run check-links

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
