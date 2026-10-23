#!/usr/bin/env bash
# En la VM de recuperación: recibe el volcado EN CLARO por stdin (llega por el túnel SSH desde la estación local, donde se descifró; la clave privada nunca sale de allí),
# lo guarda solo en tmpfs (/dev/shm), verifica su SHA-256, restaura en una base nueva y imprime la huella. Destruye el volcado al terminar.
# Uso (como postgres, vía sudo): remote-restore.sh <sha256-del-volcado-en-claro> <fingerprint.sql>
set -euo pipefail
PG=/usr/pgsql-18/bin; DB="${DRILL_DB:-drill}"   # base de destino (por defecto la base aislada de pruebas)
# --check: comprobación previa sin datos (se ejecuta ANTES de pedir la frase de paso): servidor activo, sin TCP y base 'drill' vacía o ausente.
if [[ "${1:-}" == "--check" ]]; then
  [[ "$("$PG/psql" -d postgres -Atc 'show listen_addresses')" == "" ]] || { echo "FALLÓ: PostgreSQL escucha por TCP" >&2; exit 5; }
  echo "LISTO: PostgreSQL $("$PG/psql" -d postgres -Atc 'show server_version') en socket Unix; id=$(id -un); $(df --output=avail -m /dev/shm | tail -1 | tr -d ' ') MB libres en tmpfs"
  exit 0
fi
WANT="${1:?}"; SQL="${2:?}"; D="$(mktemp -d /dev/shm/drill.XXXXXX)"; chmod 700 "$D"
trap 'shred -u "$D"/* 2>/dev/null || rm -f "$D"/*; rmdir "$D" 2>/dev/null || true' EXIT
cat > "$D/db.dump"
[[ "$(sha256sum "$D/db.dump" | cut -d' ' -f1)" == "$WANT" ]] || { echo "FALLÓ: SHA-256 del volcado distinto del manifiesto" >&2; exit 3; }
echo "OK    SHA-256 del volcado en claro coincide"
"$PG/pg_restore" --list "$D/db.dump" >/dev/null || { echo "FALLÓ: catálogo inválido" >&2; exit 4; }
"$PG/psql" -d postgres -qAt -c "DROP DATABASE IF EXISTS \"$DB\"" -c "CREATE DATABASE \"$DB\""
"$PG/pg_restore" -d "$DB" --no-owner --no-acl --exit-on-error "$D/db.dump"
echo "OK    restauración en base aislada"
"$PG/psql" -d "$DB" -At -v ON_ERROR_STOP=1 -f "$SQL" | sort
