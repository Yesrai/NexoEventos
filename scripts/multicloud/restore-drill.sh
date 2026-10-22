#!/usr/bin/env bash
# Simulacro de restauración AISLADO: verifica el hash del cifrado, descifra en un directorio temporal 0700 (se destruye al terminar), comprueba el hash del
# volcado en claro y su catálogo, restaura en una base nueva y compara la huella con la línea base. Mide el tiempo. Sale con error ante cualquier diferencia.
# Uso: restore-drill.sh --manifest M --cms F --key K --baseline B.json --baseline-key <clave> [--mode docker|local]
#   --mode docker: PostgreSQL 18 desechable en Docker (pruebas locales). --mode local: PostgreSQL ya instalado (VM de recuperación; PGHOST/PGUSER por entorno).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; MODE=docker
while [[ $# -gt 0 ]]; do case "$1" in --manifest) M="$2"; shift 2;; --cms) F="$2"; shift 2;; --key) K="$2"; shift 2;; --baseline) B="$2"; shift 2;; --baseline-key) BK="$2"; shift 2;; --mode) MODE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
: "${M:?}" "${F:?}" "${K:?}" "${B:?}" "${BK:?}"
t0=$(date +%s); TMP="$(mktemp -d)"; chmod 700 "$TMP"; C=nexo-restore-drill
cleanup() { shred -u "$TMP"/* 2>/dev/null || rm -f "$TMP"/*; rmdir "$TMP" 2>/dev/null || true; [[ "$MODE" == docker ]] && docker rm -f "$C" >/dev/null 2>&1 || true; }
trap cleanup EXIT
fail() { echo "FALLÓ: $*" >&2; exit 1; }; ok() { echo "OK    $*"; }
"$HERE/verify-transfer.sh" "$M" "$F" >/dev/null || fail "el cifrado no coincide con el manifiesto (SHA-256/tamaño)"; ok "SHA-256 del cifrado coincide con el manifiesto"
openssl cms -decrypt -binary -inform DER -in "$F" -inkey "$K" -out "$TMP/db.dump" 2>/dev/null || fail "no se pudo descifrar (clave incorrecta o archivo alterado)"; ok "descifrado correcto"
want_plain="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plaintext_dump_sha256'])" "$M")"
[[ "$(shasum -a 256 "$TMP/db.dump" | cut -d' ' -f1)" == "$want_plain" ]] || fail "el hash del volcado en claro no coincide con el del manifiesto"; ok "hash del volcado en claro coincide"
if [[ "$MODE" == docker ]]; then
  docker run -d --rm --name "$C" -e POSTGRES_PASSWORD=drill-only postgres:18 >/dev/null
  for _ in $(seq 60); do docker logs "$C" 2>&1 | grep -q "init process complete" && docker exec "$C" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
  PSQL() { docker exec -i "$C" psql -U postgres -v ON_ERROR_STOP=1 "$@"; }; RESTORE() { docker exec -i "$C" pg_restore -U postgres "$@"; }
else
  PSQL() { psql -v ON_ERROR_STOP=1 "$@"; }; RESTORE() { pg_restore "$@"; }
fi
RESTORE --list <"$TMP/db.dump" >"$TMP/toc.txt" || fail "catálogo pg_restore inválido"; [[ -s "$TMP/toc.txt" ]] || fail "catálogo vacío"; ok "catálogo de pg_restore válido ($(wc -l <"$TMP/toc.txt" | tr -d ' ') líneas)"
PSQL -d postgres -qc "DROP DATABASE IF EXISTS drill" -c "CREATE DATABASE drill"
RESTORE -d drill --no-owner --no-acl --exit-on-error <"$TMP/db.dump" || fail "pg_restore falló"; ok "restauración en base aislada"
PSQL -d drill -At <"$HERE/fingerprint.sql" | sort >"$TMP/now.txt"
python3 - "$B" "$BK" "$TMP/now.txt" <<'PY' || fail "la huella restaurada no coincide con la línea base"
import json, sys
base = json.load(open(sys.argv[1]))["baselines"][sys.argv[2]]["fingerprint"]
now = dict(l.strip().split("=", 1) for l in open(sys.argv[3]) if "=" in l)
diff = {k: (base[k], now.get(k)) for k in base if base[k] != now.get(k)}
if diff:
    print("Diferencias (esperado, obtenido):", diff); sys.exit(1)
print(f"OK    huella idéntica a la línea base ({len(base)} claves)")
PY
echo "OK    simulacro completo en $(( $(date +%s) - t0 )) s (RTO de la prueba); material temporal destruido al salir"
