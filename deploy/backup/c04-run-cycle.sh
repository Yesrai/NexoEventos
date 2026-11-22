#!/usr/bin/env bash
# C-04: UN ciclo de respaldo MANUAL (no hay timer ni servicio). Se ejecuta EN LA EC2 como root, solo en la fase D autorizada:
#   bash /opt/nexoeventos-c04/deploy/backup/c04-run-cycle.sh
# Carga DATABASE_URL de /etc/nexoeventos/backup.env (0600) sin imprimirla, ejecuta backup_cycle.py y después backup_freshness.py. Códigos: los de backup_cycle.py.
set -uo pipefail
umask 077
CONF=/etc/nexoeventos/c04/backup.json; ENVF=/etc/nexoeventos/backup.env; BASE=/opt/nexoeventos-c04/scripts/multicloud
[[ -f "$CONF" && -f "$ENVF" ]] || { echo "Falta $CONF o $ENVF." >&2; exit 2; }
[[ "$(stat -c %a "$ENVF")" == 600 ]] || { echo "$ENVF debe ser 0600." >&2; exit 2; }
# NO se hace `source`: la URL lleva «&» (sslmode=…&sslrootcert=…) y el shell la cortaría; se lee la línea tal cual (igual que systemd EnvironmentFile)
DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "$ENVF")"; export DATABASE_URL
[[ -n "$DATABASE_URL" ]] || { echo "$ENVF no define DATABASE_URL." >&2; exit 2; }
rc=0; /usr/bin/python3 "$BASE/backup_cycle.py" --config "$CONF" || rc=$?
/usr/bin/python3 "$BASE/backup_freshness.py" --config "$CONF" || true
unset DATABASE_URL
exit "$rc"
