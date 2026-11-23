#!/usr/bin/env bash
# En la VM de recuperación (sin Internet): instala PostgreSQL 18 desde RPM PGDG ya copiados (verificados en la estación local) y deja el servidor SOLO en socket Unix.
# Las dependencias salen del espejo yum de Oracle por el Service Gateway. Uso (como root): install-postgres.sh <directorio-con-rpms>
set -euo pipefail
RPMS="${1:?directorio con los RPM}"; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 1) RAM pequeña (E2.1.Micro): swap ANTES de instalar (el 23-oct dnf agotó la memoria sin swap). 2) Los RPM deben coincidir con la lista fijada de SHA-256 (cadena de suministro).
bash "$HERE/quiesce-vm.sh"    # ANTES de cualquier dnf: el temporizador `dnf makecache` del sistema (todos los repositorios) congeló la VM en T3
bash "$HERE/ensure-swap.sh"
bash "$HERE/verify-rpms.sh" "$RPMS" "$HERE/rpm-checksums.sha256" || { echo "FALLÓ: los RPM no coinciden con la lista fijada; no se instala nada." >&2; exit 5; }
# Idempotente: no reinstala ni reinicializa si ya está hecho.
rpm -q postgresql18-server >/dev/null 2>&1 || bash "$HERE/safe-dnf.sh" -y install "$RPMS"/postgresql18-libs-*.rpm "$RPMS"/postgresql18-18.*.rpm "$RPMS"/postgresql18-server-*.rpm
if [[ ! -f /var/lib/pgsql/18/data/PG_VERSION ]]; then
  /usr/pgsql-18/bin/postgresql-18-setup initdb
  printf "listen_addresses = ''\nfsync = on\n" >> /var/lib/pgsql/18/data/postgresql.conf   # sin TCP: solo socket Unix
fi
systemctl enable --now postgresql-18
sudo -u postgres /usr/pgsql-18/bin/psql -Atc "select version()"
