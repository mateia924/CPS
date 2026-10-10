#!/usr/bin/env bash
set -euo pipefail

# Sprint 7.2.8 (§8.8 item 13/2): certificate-expiry monitoring, built
# as its own independent cron — never folded into acme.sh's own
# renewal cron, so a silent failure in one is never masked by the
# other. Reads notAfter straight from the live cert file, not from
# acme.sh's internal bookkeeping, so it catches a renewal failure
# acme.sh itself failed to report just as reliably as a cert nobody
# ever tried to renew (the exact way saas.cps-oracle.com's certificate
# expired unnoticed on 2026-10-05).
#
# No real SMTP exists on this host (EMAIL_HOST is blank — see 7.2.9's
# own blocker) so this cannot send an actual email alert yet. It
# writes a dated line to its own log on every run, and on a WARNING a
# line to stderr as well — cron's default local-mail-to-root behavior
# (if a local MTA exists) is the only automatic delivery channel today.
# This is a known, accepted gap, not a design choice: rule 28's spirit
# applies — a channel that nobody reads is not a channel, so whoever
# owns this host should actually look at LOG_FILE periodically until
# 7.2.9 gives this a real email destination.

CERT_FILE="${CPS_CERT_FILE:-/etc/ssl/cps/fullchain.pem}"
WARN_DAYS="${CPS_CERT_WARN_DAYS:-14}"
LOG_FILE="${CPS_CERT_CHECK_LOG:-/var/log/cps-cert-check.log}"

log() {
    printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >>"$LOG_FILE"
}

if [ ! -f "$CERT_FILE" ]; then
    log "ERROR: $CERT_FILE not found"
    echo "cps-cert-check: ERROR: $CERT_FILE not found" >&2
    exit 1
fi

not_after_str=$(openssl x509 -in "$CERT_FILE" -noout -enddate | sed 's/^notAfter=//')
not_after_epoch=$(date -d "$not_after_str" +%s)
now_epoch=$(date +%s)
days_left=$(( (not_after_epoch - now_epoch) / 86400 ))

if [ "$days_left" -lt 0 ]; then
    log "CRITICAL: $CERT_FILE EXPIRED $days_left days ago (notAfter=$not_after_str)"
    echo "cps-cert-check: CRITICAL: certificate expired $(( -days_left )) days ago (notAfter=$not_after_str)" >&2
    exit 2
elif [ "$days_left" -lt "$WARN_DAYS" ]; then
    log "WARNING: $CERT_FILE expires in $days_left day(s) (notAfter=$not_after_str)"
    echo "cps-cert-check: WARNING: certificate expires in $days_left day(s) (notAfter=$not_after_str)" >&2
    exit 1
else
    log "OK: $CERT_FILE expires in $days_left day(s) (notAfter=$not_after_str)"
    exit 0
fi
