#!/bin/bash
# cloud-init (primer arranque, ANTES de que nadie entre por SSH): neutraliza los actualizadores en segundo plano del SO que, en la E2.1.Micro (945 MB), agotaron la memoria en T3 (22-nov-2026):
# `dnf makecache --timer` (~500 MB RSS) y `ksplice-agent`. `mask` impide además que otra unidad los reactive. No toca sshd, PostgreSQL ni Nginx. VM temporal.
for u in dnf-makecache.timer dnf-makecache.service ksplice-agent.timer ksplice-agent.service kdump.service; do systemctl mask --now "$u" >/dev/null 2>&1 || true; done
kexec -p -u 2>/dev/null; [ -w /sys/kernel/kexec_crash_size ] && echo 0 > /sys/kernel/kexec_crash_size   # devuelve al sistema los 448 MB reservados para kdump (OL 9.8)
pkill -f '^/usr/bin/python3? /usr/bin/dnf makecache' || true
echo "$(date -u +%FT%TZ) actualizadores en segundo plano neutralizados en el primer arranque" > /var/log/nexo-quiesce.log
