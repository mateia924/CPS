#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.6.4: the retention policy docs/prompts/sprint-6.6.md §2
# (block 6.6.4) asks for — every backup from the last 30 days, plus
# one (the newest) per calendar month for the 12 months before that.
# A flat N-day window (what this project used before this sprint)
# can't express "one per month going back a year" at all, so this is
# its own script rather than one more inline `find -mtime -delete` in
# scripts/backup.sh.
#
# Parses the timestamp out of the filename itself (cps-db-YYYYMMDD-
# HHMMSS.sql.gz.gpg) rather than relying on mtime — a file's mtime can
# change (a copy, a restore, a touch) in ways its own name never does.
#
# Usage: scripts/prune_backups.sh <backup-dir>

BACKUP_DIR="${1:?usage: prune_backups.sh <backup-dir>}"
NOW_EPOCH="$(date +%s)"
CUTOFF_30D=$(( NOW_EPOCH - 30 * 86400 ))
CUTOFF_12MO_MONTH="$(date -d '12 months ago' +%Y%m)"

declare -A newest_epoch_in_month
declare -A newest_file_in_month

shopt -s nullglob
for f in "$BACKUP_DIR"/cps-db-*.sql.gz.gpg; do
  ts="$(basename "$f" .sql.gz.gpg | sed -E 's/^cps-db-//')"
  epoch="$(date -d "${ts:0:4}-${ts:4:2}-${ts:6:2} ${ts:9:2}:${ts:11:2}:${ts:13:2}" +%s 2>/dev/null)" || continue
  [ "$epoch" -ge "$CUTOFF_30D" ] && continue  # inside the 30-day daily window — always kept

  month="${ts:0:6}"
  current_best="${newest_epoch_in_month[$month]:-0}"
  if [ "$epoch" -gt "$current_best" ]; then
    newest_epoch_in_month[$month]="$epoch"
    newest_file_in_month[$month]="$f"
  fi
done

for f in "$BACKUP_DIR"/cps-db-*.sql.gz.gpg; do
  ts="$(basename "$f" .sql.gz.gpg | sed -E 's/^cps-db-//')"
  epoch="$(date -d "${ts:0:4}-${ts:4:2}-${ts:6:2} ${ts:9:2}:${ts:11:2}:${ts:13:2}" +%s 2>/dev/null)" || continue
  [ "$epoch" -ge "$CUTOFF_30D" ] && continue

  month="${ts:0:6}"
  keeper="${newest_file_in_month[$month]:-}"
  if [ "$f" != "$keeper" ]; then
    echo "[$(date -Iseconds)] pruning (superseded by this month's keeper): $f"
    rm -f "$f"
    continue
  fi
  if [[ "$month" < "$CUTOFF_12MO_MONTH" ]]; then
    echo "[$(date -Iseconds)] pruning (older than the 12 monthly keepers): $f"
    rm -f "$f"
  fi
done
