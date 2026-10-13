#!/usr/bin/env bash
# 7.2.9-c (حادثة 2026-10-12/13): firewalld على هذا الخادم (docker-ce
# 26.1.3 + firewalld 0.9.11 بخلفية nftables) يمسح سلاسل iptables الخاصة
# بـDocker عند كل reload، وdockerd يفشل في إعادة بنائها فيبقى جدول nat
# فارغًا. الأعراض خادعة: docker ps يُظهر كل الحاويات Up والبورتات تسمع
# فعلًا عبر docker-proxy، لكن المرور بين الحاويات يُسقَط، فلا يصل nginx
# إلى الـbackend وكل طلب ينتهي بمهلة. live بقي كذلك ~25 ساعة ولم ينتبه أحد.
set -u
LOG=/var/log/cps-docker-firewall-guard.log
ts() { date -Iseconds; }
iptables -t nat -L DOCKER -n >/dev/null 2>&1 && exit 0
echo "$(ts) DOCKER nat chain MISSING — restarting docker" >> "$LOG"
systemctl restart docker >> "$LOG" 2>&1
sleep 20
if iptables -t nat -L DOCKER -n >/dev/null 2>&1; then
  echo "$(ts) recovered: chain present again" >> "$LOG"
else
  echo "$(ts) STILL MISSING after restart — manual intervention needed" >> "$LOG"
fi
