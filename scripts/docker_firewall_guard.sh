#!/usr/bin/env bash
# 7.2.9-c (حادثة 2026-10-12/13): firewalld على هذا الخادم (docker-ce
# 26.1.3 + firewalld 0.9.11 بخلفية nftables) يمسح سلاسل iptables الخاصة
# بـDocker عند كل reload، وdockerd يفشل في إعادة بنائها فيبقى جدول nat
# فارغًا. الأعراض خادعة: docker ps يُظهر كل الحاويات Up والبورتات تسمع
# فعلًا عبر docker-proxy، لكن المرور بين الحاويات يُسقَط، فلا يصل nginx
# إلى الـbackend وكل طلب ينتهي بمهلة. live بقي كذلك ~25 ساعة ولم ينتبه أحد.
#
# 7.2.9-c defect fix (2026-10-13): the first version ran `iptables` by
# name under cron.d's default PATH (/usr/bin:/bin, no /usr/sbin) — exit
# 127 every time, read as "chain missing", so it restarted Docker (live
# included) every 2 minutes, ~158 times. The rule now: a check that
# could not actually be performed is NEVER a reason to restart.
#   - iptables by absolute path; missing/non-executable  -> "cannot check", exit 0
#   - iptables ran but failed for any reason other than
#     "No chain/target/match by that name"               -> "cannot check", exit 0
#   - chain genuinely absent                             -> restart, at most once
#     per 30 minutes; still absent after that restart    -> STILL MISSING, give up
#     (no further restarts until $GAVE_UP is removed by hand)
# Test hook: IPTABLES=/some/path overrides the binary (used to prove the
# cannot-check branch without touching the real one).
set -u
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

LOG=/var/log/cps-docker-firewall-guard.log
STATE_DIR=/var/lib/cps-docker-firewall-guard
LAST_RESTART="$STATE_DIR/last_restart"
GAVE_UP="$STATE_DIR/gave_up"
MIN_INTERVAL=1800
IPTABLES="${IPTABLES:-/usr/sbin/iptables}"

ts() { date -Iseconds; }
log() { echo "$(ts) $*" >> "$LOG"; }

# Returns 0 = chain present, 1 = chain genuinely absent, 2 = cannot check.
check_chain() {
  if [ ! -x "$IPTABLES" ]; then
    CHECK_DETAIL="$IPTABLES missing or not executable"
    return 2
  fi
  local out rc
  out="$("$IPTABLES" -w 10 -t nat -L DOCKER -n 2>&1 >/dev/null)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "No chain/target/match by that name"; then
    return 1
  fi
  CHECK_DETAIL="iptables exit $rc: ${out:-no output}"
  return 2
}

mkdir -p "$STATE_DIR"

CHECK_DETAIL=""
check_chain
case $? in
  0) exit 0 ;;
  2) log "cannot check DOCKER nat chain ($CHECK_DETAIL) — NOT restarting docker"; exit 0 ;;
esac

# Chain genuinely absent from here on.
if [ -e "$GAVE_UP" ]; then
  log "DOCKER nat chain missing; gave up at $(cat "$GAVE_UP") — manual intervention needed (remove $GAVE_UP to re-arm)"
  exit 0
fi
now=$(date +%s)
last=$(cat "$LAST_RESTART" 2>/dev/null || echo 0)
if [ $((now - last)) -lt "$MIN_INTERVAL" ]; then
  log "DOCKER nat chain missing; last restart $((now - last))s ago (< ${MIN_INTERVAL}s) — not restarting again"
  exit 0
fi

log "DOCKER nat chain MISSING — restarting docker"
echo "$now" > "$LAST_RESTART"
systemctl restart docker >> "$LOG" 2>&1
sleep 20
check_chain
case $? in
  0) log "recovered: chain present again" ;;
  1) log "STILL MISSING after restart — manual intervention needed; guard stops restarting"; ts > "$GAVE_UP" ;;
  2) log "cannot verify after restart ($CHECK_DETAIL)" ;;
esac
exit 0
