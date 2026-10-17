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
# Optional: SMOKE_BASE_URL/SMOKE_SUBDOMAIN/SMOKE_EMAIL/SMOKE_PASSWORD,
# exported by the caller, reach scripts/smoke.sh unchanged.

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

# nginx resolves "backend" once and keeps the old IP after backend is
# recreated (6.6.0) — restarting it forces a fresh lookup.
cps_gate_start() {
  $GATE_COMPOSE up -d && $GATE_COMPOSE restart nginx
}

# nginx answers before gunicorn binds; any real status from
# /admin/login/ (never rate-limited, unlike /api/auth/login/) means the
# request reached Django.
cps_gate_ready() {
  local status=""
  for _ in $(seq 1 30); do
    status="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$GATE_HTTP_PORT/admin/login/" || true)"
    if [ "$status" != "502" ] && [ "$status" != "503" ] && [ "$status" != "000" ]; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: backend never accepted a connection within 30s (last status: ${status:-none})" >&2
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
