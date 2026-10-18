# shellcheck shell=bash
# Pre-deploy 1 (2026-10-17), rule 32 (docs/SYSTEM_ANALYSIS.md §4): the
# ONE definition of the gates a deploy passes through, sourced by both
# scripts/deploy.sh (live) and scripts/staging_refresh.sh (the
# rehearsal, both modes). Before this, each script carried its own copy
# of the sequence, and they drifted the way copies do: the rehearsal
# skipped add_missing_system_accounts and check_chart_health
# --fail-on-findings entirely, the full refresh had neither smoke.sh nor
# the readiness poll that --code-only had (the most destructive mode
# was the least guarded), and backed up live, not the staging data it
# was about to wipe. A rehearsal that runs different gates proves
# nothing about the deploy. Same pattern as apps/approvals/defaults.py
# (7.4): one definition, two callers. What does not exist twice cannot
# drift. tests/test_production_gates.py fails if a caller runs a gate
# command of its own or skips cps_run_gates.
#
# Not executable on its own — `source` it, set the GATE_* parameters,
# then call cps_run_gates. The caller does what is truly its own
# (building images, staging's restore and anonymize); everything that
# decides whether the result is fit to serve happens here.
#
# Parameters (all required):
#   GATE_REPO_DIR        repo root
#   GATE_COMPOSE         the full `docker compose ...` prefix for the stack
#   GATE_BACKUP_TARGET   scripts/backup.sh --target (live|staging|dev)
#   GATE_BACKUP_REASON   the reason written to docs/ops/backups.log
#   GATE_HTTP_PORT       host port nginx serves this stack on
# Optional: SMOKE_BASE_URL/SMOKE_SUBDOMAIN/SMOKE_EMAIL, exported by the
# caller, reach scripts/smoke.sh unchanged. SMOKE_PASSWORD comes from
# cps_gates_preflight (below), never from a default (rule 50), and where
# it comes from follows GATE_BACKUP_TARGET alone — no switch of its own.
# Optional: GATE_ENV_SECRETS, space-separated names of further variables
# the caller's run needs non-empty (it can only add checks).

CPS_PRODUCTION_GATES=(
  backup
  migrate
  setup_rls
  verify_rls
  add_missing_system_accounts
  check_chart_health
  start
  ready
  smoke
)

cps_gate_log() { echo "[gates $(date -Iseconds)] $1"; }

# Pre-deploy 2 (2026-10-17), rule 50: every secret the run needs is
# checked BEFORE the first gate — and callers call this before their own
# first step too (build; staging's wipe). A secret first read by gate 9
# (smoke) is found missing after migrate and start already changed the
# stack; this check changes nothing, so failing here costs nothing.
# Messages name the path and the permissions it needs, never a value.
# The file's trailing newline (an editor's, `echo >`'s) is stripped, and
# a CR with it.
#
# Where SMOKE_PASSWORD comes from is decided by GATE_BACKUP_TARGET — the
# parameter the migrate guard already binds to the database's identity —
# and by nothing else: live reads the file below (fixed path, checked
# owner and mode), staging takes the value its caller exported from
# .env.staging, any other target is refused. Until the follow-up to 907f5e3
# there were two more variables (the directory, and a "file"/"env"
# mode): one edited line could switch live off the file check, with no
# guard to refuse it — a kill switch, not a guard (rules 49, 50).
CPS_PREFLIGHT_PASSED=0
cps_gates_preflight() {
  local file=/etc/cps-secrets/smoke_password owner mode value var failed=0
  case "${GATE_BACKUP_TARGET-}" in
    live)
      if [ ! -f "$file" ]; then
        echo "ERROR: secrets preflight: $file does not exist — gate smoke logs in with it. Create it root:root, mode 600, holding only the password." >&2
        failed=1
      else
        read -r owner mode < <(stat -c '%u %a' "$file")
        if [ "$owner" != "0" ] || [ $((8#$mode & 8#077)) -ne 0 ]; then
          echo "ERROR: secrets preflight: $file is owned by uid $owner with mode $mode — it must be root:root, mode 600 (no group or other access)." >&2
          failed=1
        elif [ ! -r "$file" ]; then
          echo "ERROR: secrets preflight: $file is not readable by $(id -un) — run as root (the file is root:root, mode 600)." >&2
          failed=1
        else
          value="$(<"$file")"
          value="${value%$'\r'}"
          if [ -z "$value" ]; then
            echo "ERROR: secrets preflight: $file is empty — it must hold the smoke password (root:root, mode 600)." >&2
            failed=1
          else
            export SMOKE_PASSWORD="$value"
          fi
        fi
      fi
      ;;
    staging)
      if [ -z "${SMOKE_PASSWORD:-}" ]; then
        echo "ERROR: secrets preflight: SMOKE_PASSWORD is empty — staging_refresh.sh exports it from .env.staging for gate smoke." >&2
        failed=1
      fi
      ;;
    *)
      echo "ERROR: secrets preflight: knows GATE_BACKUP_TARGET live and staging only, got \"${GATE_BACKUP_TARGET-}\" — refusing." >&2
      failed=1
      ;;
  esac
  for var in ${GATE_ENV_SECRETS:-}; do
    if [ -z "${!var:-}" ]; then
      echo "ERROR: secrets preflight: $var is empty — set it in the caller's env file." >&2
      failed=1
    fi
  done
  [ "$failed" -eq 0 ] || return 1
  CPS_PREFLIGHT_PASSED=1
  cps_gate_log "secrets preflight passed."
}

# One-off containers (`run --rm`), never the persistent service's own
# startup chain: starting the persistent backend first races its own
# startup `migrate` against the guard and crash-loops it (found live on
# staging, 6.6.3d). Everything below runs to completion before `start`.
cps_gate_manage() {
  $GATE_COMPOSE run --rm --entrypoint '' backend python manage.py "$@"
}

# A backup of the database about to be migrated — the migrate guard
# matches its db= identity, so a dump of any other database (live's,
# when this is staging) no longer satisfies it. An optional $1 replaces
# the reason, for a caller's extra backup of the same target (staging's
# data before its full refresh wipes it).
cps_gate_backup() {
  "$GATE_REPO_DIR/scripts/backup.sh" --target "$GATE_BACKUP_TARGET" "${1:-$GATE_BACKUP_REASON}"
}

cps_gate_migrate() {
  cps_gate_manage migrate --noinput
}

cps_gate_setup_rls() {
  cps_gate_manage setup_rls
}

# pg_dump --no-privileges strips every policy, and a migration can add a
# tenant-scoped table: count the tenant_isolation policies against the
# tenant-scoped tables, so RLS can never be quietly OFF on one of them.
cps_gate_verify_rls() {
  local result tables policies
  result="$(cps_gate_manage shell -c "
from django.db import connection
from apps.common.rls import tenant_scoped_tables
tables = [name for name, _model in tenant_scoped_tables()]
with connection.cursor() as cursor:
    cursor.execute(
        \"SELECT count(*) FROM pg_policies WHERE schemaname = 'public' \"
        \"AND policyname = 'tenant_isolation' AND tablename = ANY(%s)\",
        [tables],
    )
    policy_count = cursor.fetchone()[0]
print(f'{len(tables)} {policy_count}')
" | tail -1 | tr -d '\r')" || return 1
  tables="$(echo "$result" | cut -d' ' -f1)"
  policies="$(echo "$result" | cut -d' ' -f2)"
  if [ -z "$tables" ] || [ "$tables" != "$policies" ]; then
    echo "ERROR: ${tables:-?} tenant-scoped table(s) but ${policies:-?} tenant_isolation polic(y/ies) — RLS is not fully applied." >&2
    return 1
  fi
  cps_gate_log "RLS verified: $policies/$tables tenant-scoped tables have the tenant_isolation policy."
}

# Idempotent for every tenant (sprint 7.0, D1).
cps_gate_add_missing_system_accounts() {
  cps_gate_manage add_missing_system_accounts
}

# Sprint 7.0.2 (incidents #5/#6): a tenant's chart can silently disable
# an automated posting path. A committed exception
# (docs/ops/chart_health_exceptions.json) is the only way past this.
cps_gate_check_chart_health() {
  cps_gate_manage check_chart_health --fail-on-findings
}

# Pre-deploy 1 (2026-10-17): `build` has already moved every image tag
# to the new code, but the existing containers still hold the previous
# images by ID (stopped ones too: staging --full stops backend first) —
# the last moment anything can name them. Each one is tagged
# <image>:rollback-<time> (also keeps `docker image prune` off it), and
# CPS_ROLLBACK_COMMAND is the command that puts them back: printed when
# `ready` times out, run by a human, never automatically. Migrations are
# not rolled back by it: the previous code would serve the migrated
# schema, exactly as it did between `migrate` and `start`.
#
# Pre-deploy 3 (2026-10-18): ONLY images this project builds itself.
# staging and live share the host's one image store, and both pull the
# same external images by the same tags (postgres:16-alpine, nginx,
# redis, minio, clamav). Tagging every container's image made the
# printed rollback re-point `postgres:16-alpine` & co. — tags live's
# containers read — to whatever image staging had: harmless only while
# both happened to hold the same ID (2026-10-18 they did). An external
# image is pinned by its own tag, is not changed by `build`, and is
# never tagged or re-tagged here. A built image is one compose named
# after its project and service, <project>-<service> (no `image:` in
# the compose files): cps-staging-backend vs infra-backend — so every
# rollback tag carries the project's name, and one stack's tag cannot
# be read by the other's containers. A built service that ever gets an
# `image:` of its own is left untagged (named in the log), never tagged
# under a name another stack might read.
CPS_ROLLBACK_COMMAND=""
cps_record_previous_images() {
  local stamp container info image image_id project service tags="" built="" external=""
  stamp="rollback-$(date +%Y%m%d-%H%M%S)"
  for container in $($GATE_COMPOSE ps -a -q); do
    info="$(docker inspect -f '{{.Config.Image}} {{.Image}} {{index .Config.Labels "com.docker.compose.project"}} {{index .Config.Labels "com.docker.compose.service"}}' "$container")" || return 1
    read -r image image_id project service <<< "$info"
    case "$image" in *:*) ;; *) image="$image:latest" ;; esac
    if [ -z "$project" ] || [ "${image%:*}" != "$project-$service" ]; then
      external="$external $image"
      continue
    fi
    docker tag "$image_id" "${image%:*}:$stamp" || return 1
    tags="$tags docker tag ${image%:*}:$stamp $image &&"
    built="$built ${image%:*}"
  done
  [ -z "$external" ] || cps_gate_log "not tagged (external, pinned by their own tag — rollback never touches them):$external"
  if [ -z "$tags" ]; then
    CPS_ROLLBACK_COMMAND=""
    cps_gate_log "no built image running before start — nothing to roll back to."
    return 0
  fi
  CPS_ROLLBACK_COMMAND="cd $GATE_REPO_DIR/infra &&$tags $GATE_COMPOSE up -d --no-build && $GATE_COMPOSE restart nginx"
  cps_gate_log "previous built images tagged :$stamp (rollback target):$built"
}

# nginx resolves "backend" once and keeps the old IP after backend is
# recreated (6.6.0) — restarting it forces a fresh lookup.
cps_gate_start() {
  cps_record_previous_images && $GATE_COMPOSE up -d && $GATE_COMPOSE restart nginx
}

# nginx answers before gunicorn binds; any real status from
# /admin/login/ (never rate-limited, unlike /api/auth/login/) means the
# request reached Django — except 502/503/504, which are nginx's own.
# Pre-deploy 1 (2026-10-17): 180s, not 30. By now `start` has already
# replaced the containers — failing fast brings nothing back, it only
# gives up on a backend that may be a minute from binding (cold image,
# collectstatic, a slow first import). Measured by the clock, not by
# loop turns. Rule 36 (docs/SYSTEM_ANALYSIS.md §4): one request may run
# 70s, longer than nginx's own 60s proxy timeout, so a backend that
# accepts and never answers ends as nginx's 504 — counted as NOT ready
# (before this, 504 passed: the 2026-10-13 outage answered exactly
# that, with every container `Up`). On timeout it says what the stack
# may be serving and prints the rollback, ready to copy.
CPS_READY_TIMEOUT_SECONDS=180
cps_gate_ready() {
  local status="" deadline=$((SECONDS + CPS_READY_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    status="$(curl -s -o /dev/null --max-time 70 -w '%{http_code}' "http://localhost:$GATE_HTTP_PORT/admin/login/" || true)"
    if [ "$status" != "502" ] && [ "$status" != "503" ] && [ "$status" != "504" ] && [ "$status" != "000" ]; then
      return 0
    fi
    sleep 2
  done
  {
    echo "ERROR: backend never accepted a connection within ${CPS_READY_TIMEOUT_SECONDS}s (last status: ${status:-none})."
    echo "!!! $GATE_BACKUP_TARGET (port $GATE_HTTP_PORT) MAY BE SERVING 502 RIGHT NOW: the containers were already replaced by the new images."
    echo "Container states:"
    $GATE_COMPOSE ps 2>&1 || true
    if [ -n "$CPS_ROLLBACK_COMMAND" ]; then
      echo "To go back to the previous images (code only — migrations stay applied), copy and run:"
      echo
      echo "  $CPS_ROLLBACK_COMMAND"
      echo
    else
      echo "No previous images were recorded (nothing was running before start) — there is nothing to roll back to."
    fi
    echo "Nothing was rolled back automatically. Check first: cd $GATE_REPO_DIR/infra && $GATE_COMPOSE logs --tail 100 backend"
  } >&2
  return 1
}

cps_gate_smoke() {
  SMOKE_BASE_URL="${SMOKE_BASE_URL:-http://localhost:$GATE_HTTP_PORT/api}" "$GATE_REPO_DIR/scripts/smoke.sh"
}

# Runs every gate in order and stops at the first failure, leaving its
# name in CPS_FAILED_GATE for the caller's own failure record.
cps_run_gates() {
  local var gate i=0 n=${#CPS_PRODUCTION_GATES[@]}
  for var in GATE_REPO_DIR GATE_COMPOSE GATE_BACKUP_TARGET GATE_BACKUP_REASON GATE_HTTP_PORT; do
    if [ -z "${!var:-}" ]; then
      CPS_FAILED_GATE="parameter $var not set"
      echo "ERROR: production_gates.sh: $var is not set." >&2
      return 1
    fi
  done
  if [ "$CPS_PREFLIGHT_PASSED" != "1" ] && ! cps_gates_preflight; then
    CPS_FAILED_GATE="secrets preflight"
    cps_gate_log "FAILED before gate 1/$n: secrets preflight"
    return 1
  fi
  for gate in "${CPS_PRODUCTION_GATES[@]}"; do
    i=$((i + 1))
    cps_gate_log "gate $i/$n: $gate"
    if ! "cps_gate_$gate"; then
      CPS_FAILED_GATE="$gate"
      cps_gate_log "FAILED at gate $i/$n: $gate"
      return 1
    fi
  done
  CPS_FAILED_GATE=""
}
