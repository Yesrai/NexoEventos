#!/usr/bin/env bash
# C-04: restauración AISLADA en el Mac de UN respaldo real (OCI → verificación → descifrado → pg_restore en un PostgreSQL desechable) con medición por etapas.
# SOLO LECTURA en OCI (perfil de lectura), nada en AWS, sin Docker. Todo el material (descarga, volcado en claro, clúster) vive en un directorio 0700 que se destruye al salir.
# Uso (en TU terminal, porque pide la frase de paso de la clave privada sin mostrarla):
#   bash scripts/multicloud/c04-restore-local.sh [--stem nexoeventos-rds-20261119T055432Z] [--pgbin /ruta/a/postgresql-18/bin] [--from-dir DIR (solo pruebas)]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
source "$HERE/lib-cms-key.sh"
STEM=nexoeventos-rds-20261119T055432Z; PGBIN=""; FROMDIR=""; DECRYPT_ONLY=0; PREFIX=backups/c04-20261119/; BUCKET=nexoeventos-recovery; PROFILE=NEXOEVENTOS_UPLOADER
KEY="${NEXO_RECOVERY_KEY:-$HOME/.nexoeventos/recovery-oci/oci-recovery-private.pem}"; SIGNER="${NEXO_SIGNER_PUB:-$ROOT/deploy/backup/signers/c04-backup-sign.pub}"
OUTJSON="$ROOT/work/c04/restore/resultado.json"
CERT=""; CERT_SHA=""
while [[ $# -gt 0 ]]; do case "$1" in --cert) CERT="$2"; shift 2;; --cert-sha256) CERT_SHA="$(printf %s "$2" | tr -d : | tr A-F a-f)"; shift 2;; --stem) STEM="$2"; shift 2;; --pgbin) PGBIN="$2"; shift 2;; --from-dir) FROMDIR="$2"; shift 2;; --decrypt-only) DECRYPT_ONLY=1; shift;; --out) OUTJSON="$2"; shift 2;; --key) KEY="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ "$STEM" =~ ^nexoeventos-rds-[0-9]{8}T[0-9]{6}Z$ ]] || { echo "Identificador de respaldo inválido." >&2; exit 2; }
if [[ "$DECRYPT_ONLY" != 1 && -z "$PGBIN" ]]; then for c in /opt/homebrew/opt/postgresql@18/bin /usr/local/opt/postgresql@18/bin; do [[ -x "$c/postgres" ]] && PGBIN="$c" && break; done; fi
SRV="(sin servidor: --decrypt-only)"
if [[ "$DECRYPT_ONLY" != 1 ]]; then
  [[ -n "$PGBIN" && -x "$PGBIN/postgres" ]] || { echo "Falta un servidor PostgreSQL 18 (use --pgbin). No se usa Docker." >&2; exit 2; }
  SRV="$("$PGBIN/postgres" --version | awk '{print $3}')"; [[ "${NEXO_ALLOW_OTHER_PG:-}" == 1 || "$SRV" == 18.* ]] || { echo "El servidor es $SRV; se exige PostgreSQL 18." >&2; exit 2; }
fi
[[ -r "$KEY" ]] || { echo "No se encuentra la clave privada de recuperación." >&2; exit 2; }
now() { python3 -c 'import time;print(f"{time.time():.3f}")'; }
stage_start() { S0=$(now); }; stage_end() { v=$(python3 -c "print(round($(now)-$S0,3))"); eval "T_$1=$v"; echo "  · $1: $v s"; }  # bash 3.2 de macOS: sin arrays asociativos
fail() { echo "FALLÓ: $*" >&2; exit 1; }; ok() { echo "OK    $*"; }
WORK="$(mktemp -d /tmp/nexo-restore.XXXXXX)"; chmod 700 "$WORK"; PGD="$WORK/pg"; SOCK="$WORK/s"; mkdir -p "$SOCK" "$WORK/dl"; PORT=""
cleanup() {
  [[ -n "$PORT" ]] && "$PGBIN/pg_ctl" -D "$PGD" -m immediate stop >/dev/null 2>&1 || true
  [[ -d "$WORK" ]] && { find "$WORK" -type f \( -name '*.dump' -o -name '*.cms' \) -exec sh -c 'for f; do dd if=/dev/zero of="$f" bs=1k count=$(( $(wc -c <"$f") / 1024 + 1 )) conv=notrunc 2>/dev/null; done' _ {} + 2>/dev/null; rm -rf "$WORK"; }
  unset KEYPW
}
trap cleanup EXIT
T_ALL0=$(now)
echo "Respaldo: $STEM | servidor desechable PostgreSQL $SRV | sin Docker | sin escribir en AWS/OCI"
# 1) descarga (solo lectura, canal independiente)
stage_start
if [[ -n "$FROMDIR" ]]; then for x in cms manifest.json manifest.json.sig; do cp "$FROMDIR/$STEM.$x" "$WORK/dl/"; done
else
  NS="$(SUPPRESS_LABEL_WARNING=True oci os ns get --query data --raw-output 2>/dev/null)"
  for x in cms manifest.json manifest.json.sig; do
    SUPPRESS_LABEL_WARNING=True oci os object get --namespace-name "$NS" --bucket-name "$BUCKET" --name "$PREFIX$STEM.$x" --file "$WORK/dl/$STEM.$x" --profile "$PROFILE" >/dev/null 2>&1 || fail "descarga de $x"
  done
fi
stage_end descarga; ok "descargados: CMS, manifiesto y firma"
# 2) verificación previa al descifrado: firma, tamaño y SHA-256
stage_start
M="$WORK/dl/$STEM.manifest.json"; C="$WORK/dl/$STEM.cms"
openssl dgst -sha256 -verify "$SIGNER" -signature "$WORK/dl/$STEM.manifest.json.sig" "$M" >/dev/null 2>&1 || fail "la firma del manifiesto NO es válida"
python3 - "$M" "$C" "$STEM" <<'PY' || fail "tamaño/SHA-256 del cifrado o nombre no coinciden con el manifiesto"
import hashlib, json, sys
m = json.load(open(sys.argv[1])); b = open(sys.argv[2], "rb").read()
assert m["name"] == sys.argv[3] and m["env"] == "aws-academy"
assert len(b) == m["oci_cms_bytes"] and hashlib.sha256(b).hexdigest() == m["oci_cms_sha256"]
PY
# identidad del certificado (con --cert): huella fijada (si se dio --cert-sha256) y destinatario del CMS; la correspondencia con la clave se comprueba aquí si la clave NO tiene frase, o tras pedirla si la tiene
if [[ -n "$CERT" ]]; then
  [[ -z "$CERT_SHA" || "$(openssl x509 -in "$CERT" -outform DER | openssl sha256 | awk '{print $NF}')" == "$CERT_SHA" ]] || fail "el certificado NO tiene la huella SHA-256 esperada"
  cs="$(openssl x509 -in "$CERT" -noout -serial | cut -d= -f2 | tr 'a-f' 'A-F')"
  rs="$(openssl cms -cmsout -print -inform DER -in "$C" 2>/dev/null | sed -n 's/^ *serialNumber: 0x//p' | head -1 | tr 'a-f' 'A-F')"
  [[ -n "$cs" && "$cs" == "$rs" ]] || fail "el certificado indicado NO es el destinatario del CMS"
  if ! key_is_protected "$KEY"; then
    [[ "$(openssl x509 -in "$CERT" -noout -pubkey | openssl sha256 | awk '{print $NF}')" == "$(openssl pkey -in "$KEY" -pubout 2>/dev/null | openssl sha256 | awk '{print $NF}')" ]] || fail "la clave privada NO corresponde al certificado"
    ok "el certificado es el destinatario del CMS y la clave privada corresponde a su clave pública"
  else ok "el certificado es el destinatario del CMS (la clave está protegida: su correspondencia se comprueba al abrirla)"; fi
fi
stage_end verificacion; ok "firma válida (clave pública fijada) · tamaño y SHA-256 del cifrado coinciden con el manifiesto"
# 3) descifrado (la frase de paso se pide aquí, sin eco, y solo vive en una variable de entorno hasta terminar de descifrar)
# Canal de la frase de paso: `read -s` (sin eco, no entra en el historial) → variable del shell NO exportada → tubería anónima en el descriptor 4 (`printf` es una orden interna:
# no aparece en ningún argumento de proceso) → `openssl -passin fd:4`. No hay variable de entorno heredada, ni archivo temporal, ni salida estándar. Se borra al terminar de descifrar.
PASSIN=""
if key_is_protected "$KEY"; then
  [[ -t 0 ]] || fail "la clave está protegida: ejecute este script en una terminal interactiva"
  IFS= read -r -s -p "Frase de paso de la clave de recuperación (no se muestra): " KEYPW; echo
  exec 4< <(printf '%s\n' "$KEYPW"); PASSIN="fd:4"
  if [[ -n "$CERT" ]]; then   # correspondencia clave protegida ↔ certificado (la frase viaja por un segundo descriptor; solo se compara el hash de la clave PÚBLICA)
    exec 5< <(printf '%s\n' "$KEYPW")
    [[ "$(openssl pkey -in "$KEY" -pubout -passin fd:5 2>/dev/null | openssl sha256 | awk '{print $NF}')" == "$(openssl x509 -in "$CERT" -noout -pubkey | openssl sha256 | awk '{print $NF}')" ]] \
      || { exec 5<&-; exec 4<&-; unset KEYPW; fail "la clave protegida NO se pudo abrir con esa frase o NO corresponde al certificado"; }
    exec 5<&-; ok "la clave protegida se abre con la frase y corresponde al certificado"
  fi
fi
stage_start
cms_decrypt_key "$C" "$KEY" "$PASSIN" "$WORK/db.dump" || { exec 4<&-; unset KEYPW; fail "descifrado (motivo arriba)"; }
exec 4<&-; unset KEYPW
stage_end descifrado
[[ "$(head -c5 "$WORK/db.dump")" == "PGDMP" ]] || fail "el volcado no empieza por PGDMP"
python3 - "$M" "$WORK/db.dump" <<'PY' || fail "el SHA-256 del volcado en claro no coincide con el del manifiesto"
import hashlib, json, sys
m = json.load(open(sys.argv[1])); b = open(sys.argv[2], "rb").read()
assert len(b) == m["plaintext_dump_bytes"] and hashlib.sha256(b).hexdigest() == m["plaintext_dump_sha256"]
PY
ok "descifrado correcto · cabecera PGDMP · hash y tamaño del volcado coinciden con el manifiesto"
if [[ "$DECRYPT_ONLY" == 1 ]]; then
  echo "OK    prueba de descifrado completada (--decrypt-only): la clave descifra el respaldo y el volcado coincide con el manifiesto. Material temporal destruido al salir."; exit 0
fi
# 4) restauración en un clúster desechable (solo socket Unix dentro del directorio temporal; puerto libre aleatorio)
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
export PGHOST="$SOCK" PGPORT="$PORT" PGUSER=postgres; unset PGPASSWORD PGDATABASE PGSERVICE DATABASE_URL
"$PGBIN/initdb" -D "$PGD" -U postgres -E UTF8 --locale=C -A trust >/dev/null || fail "initdb"
LC_ALL=en_US.UTF-8 "$PGBIN/pg_ctl" -D "$PGD" -o "-c listen_addresses= -c unix_socket_directories=$SOCK -c port=$PORT -c fsync=off" -l "$WORK/pg.log" -w start >/dev/null || fail "no arrancó el clúster desechable"
[[ -n "$(ls "$PGBIN"/pg_restore 2>/dev/null)" ]] && RESTORE="$PGBIN/pg_restore" || RESTORE="$(command -v pg_restore)"
PSQL="$PGBIN/psql"; [[ -x "$PSQL" ]] || PSQL="$(command -v psql)"
"$RESTORE" --version | sed 's/^/  pg_restore: /'
stage_start
"$PSQL" -v ON_ERROR_STOP=1 -qd postgres -c "CREATE DATABASE drill" || fail "no se pudo crear la base aislada"
"$RESTORE" -d drill --no-owner --no-acl --exit-on-error <"$WORK/db.dump" 2>"$WORK/restore.err" || { echo "--- primeras líneas del error de pg_restore:"; head -5 "$WORK/restore.err"; fail "pg_restore falló"; }
stage_end restauracion; ok "pg_restore correcto en la base aislada"
# 5) comprobación final: esquema, migración y conteos contra la huella del PROPIO manifiesto
stage_start
"$PSQL" -d drill -At <"$HERE/fingerprint.sql" | sort >"$WORK/now.txt" || fail "no se pudo calcular la huella"
python3 - "$M" "$STEM" "$WORK/base.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); json.dump({"baselines": {sys.argv[2]: {"fingerprint": m["fingerprint_before"], "fingerprint_after": m["fingerprint_after"]}}}, open(sys.argv[3], "w"))
PY
python3 "$HERE/compare-fingerprint.py" "$WORK/base.json" "$STEM" "$WORK/now.txt" || fail "la huella restaurada no coincide con la del manifiesto"
TABLES="$("$PSQL" -d drill -At -c "select count(*) from information_schema.tables where table_schema='public'")"
stage_end comprobacion
TOTAL="$(python3 -c "print(round($(now)-$T_ALL0,3))")"
echo "Conteos restaurados: $(tr '\n' ' ' <"$WORK/now.txt")| tablas en public: $TABLES"
mkdir -p "$(dirname "$OUTJSON")"
python3 - "$OUTJSON" "$STEM" "$SRV" "$TOTAL" "$TABLES" "$WORK/now.txt" "$T_descarga" "$T_verificacion" "$T_descifrado" "$T_restauracion" "$T_comprobacion" <<'PY'
import json, sys
a = sys.argv; now = dict(l.strip().split("=", 1) for l in open(a[6]) if "=" in l)
json.dump({"respaldo": a[2], "servidor_desechable": a[3], "tipo": "tiempo observado de recuperación aislada en Mac (NO es el RTO del failover AWS–OCI)",
           "segundos": {"descarga": float(a[7]), "verificacion": float(a[8]), "descifrado": float(a[9]), "restauracion": float(a[10]), "comprobacion_final": float(a[11]), "total_procedimiento": float(a[4])},
           "tablas_public": int(a[5]), "huella_restaurada": now}, open(a[1], "w"), indent=1, ensure_ascii=False)
PY
echo "OK    recuperación aislada completa. Total del procedimiento: ${TOTAL} s (tiempo observado en Mac, no RTO de failover). Material temporal destruido al salir."
