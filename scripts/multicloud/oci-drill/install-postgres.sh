#!/usr/bin/env bash
# En la VM de recuperación (sin Internet): instala PostgreSQL 18 desde RPM PGDG ya copiados (verificados en la estación local) y deja el servidor SOLO en socket Unix.
# Las dependencias salen del espejo yum de Oracle por el Service Gateway. Uso (como root): install-postgres.sh <directorio-con-rpms>
set -euo pipefail
RPMS="${1:?directorio con los RPM}"
# Idempotente: no reinstala ni reinicializa si ya está hecho.
rpm -q postgresql18-server >/dev/null 2>&1 || dnf -y install "$RPMS"/postgresql18-libs-*.rpm "$RPMS"/postgresql18-18.*.rpm "$RPMS"/postgresql18-server-*.rpm
if [[ ! -f /var/lib/pgsql/18/data/PG_VERSION ]]; then
  /usr/pgsql-18/bin/postgresql-18-setup initdb
  printf "listen_addresses = ''\nfsync = on\n" >> /var/lib/pgsql/18/data/postgresql.conf   # sin TCP: solo socket Unix
fi
systemctl enable --now postgresql-18
sudo -u postgres /usr/pgsql-18/bin/psql -Atc "select version()"
