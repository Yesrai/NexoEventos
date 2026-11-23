#!/usr/bin/env bash
# Se ejecuta EN LA EC2 de V1 (como root, por SSM o SSH) y SOLO tras autorización. Tres modos:
#   check  <rds-id> <región> [CA]   SOLO LECTURA: identidad de la base, ¿existe el rol?, holgura de conexiones y instantánea del catálogo (antes).
#   apply  <rds-id> <región> [CA]   crea el rol `nexoeventos_backup` (deploy/backup/backup-role.sql) y escribe /etc/nexoeventos/backup.env (0600); compara la instantánea
#                                   del catálogo antes/después (los demás roles y objetos no deben cambiar). Aborta si el rol ya existe o si backup.env ya existe.
#   verify                          usa backup.env (rol de volcado): conexión TLS verify-full, pg_dump y huella de datos, y comprueba que NO puede escribir. Sin escribir nada.
# El secreto maestro de RDS se lee DENTRO de la instancia (rol de la EC2), se pasa a psql por variable de entorno (nunca por argumentos) y NUNCA se imprime; la contraseña
# nueva se genera aquí y solo se guarda en backup.env. Salida: líneas «OK …/DIFF …» con nombres, conteos y hashes de catálogo; ningún secreto.
set -euo pipefail
umask 077
MODE="${1:?modo: check|apply|verify}"
SQL="${NEXO_BACKUP_SQL:-/opt/nexoeventos-c04/deploy/backup/backup-role.sql}"
SNAP="${NEXO_SNAPSHOT_SQL:-/opt/nexoeventos-c04/deploy/backup/c04-db-snapshot.sql}"
FP="${NEXO_FINGERPRINT_SQL:-/opt/nexoeventos-c04/scripts/multicloud/fingerprint.sql}"
ENVF=/etc/nexoeventos/backup.env
[[ "$(id -u)" == 0 ]] || { echo "Ejecutar como root." >&2; exit 1; }
work="$(mktemp -d)"; trap 'shred -u "$work"/* 2>/dev/null || true; rm -rf "$work"' EXIT

admin_connect() {  # exporta PGPASSWORD (maestro) y fija ADMIN_URI / CA / ENDPOINT
  DB_ID="${1:?identificador de RDS}"; REGION="${2:?región}"; CA="${3:-/etc/nexoeventos/rds-ca-bundle.pem}"
  [[ -f "$CA" && -f "$SQL" && -f "$SNAP" ]] || { echo "Falta la CA ($CA), el SQL del rol o el de la instantánea." >&2; exit 1; }
  read -r ENDPOINT MASTER_USER SECRET_ARN <<<"$(aws rds describe-db-instances --region "$REGION" --db-instance-identifier "$DB_ID" \
    --query 'DBInstances[0].[Endpoint.Address,MasterUsername,MasterUserSecret.SecretArn]' --output text)"
  [[ -n "$ENDPOINT" && "$ENDPOINT" != None && -n "$SECRET_ARN" && "$SECRET_ARN" != None ]] || { echo "No se pudo resolver el endpoint o el secreto maestro." >&2; exit 1; }
  aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ARN" --query SecretString --output text >"$work/master.json"
  MASTER_USER="$(jq -er .username "$work/master.json")"; PGPASSWORD="$(jq -er .password "$work/master.json")"; export PGPASSWORD
  SSL="sslmode=verify-full&sslrootcert=$CA"
  ADMIN_URI="postgresql://$MASTER_USER@$ENDPOINT:5432/nexoeventos?$SSL"
}
snapshot() { psql "$ADMIN_URI" -At -v ON_ERROR_STOP=1 -f "$SNAP"; }

case "$MODE" in
check)
  admin_connect "${2:-}" "${3:-}" "${4:-}"
  snapshot >"$work/snap.txt"; cat "$work/snap.txt"
  echo "OK identidad de la base y conexión TLS verify-full con el administrador comprobadas (solo lectura)"
  ;;
apply)
  admin_connect "${2:-}" "${3:-}" "${4:-}"
  [[ ! -e "$ENVF" ]] || { echo "ABORTA: $ENVF ya existe (no se sobrescribe)." >&2; exit 1; }
  snapshot >"$work/antes.txt"
  grep -q '^rol_backup_existe|0$' "$work/antes.txt" || { echo "ABORTA: el rol nexoeventos_backup ya existe (no se recrea ni se cambia su contraseña)." >&2; exit 1; }
  read -r CUR MAX <<<"$(awk -F'[|=]' '/^conexiones\|/{print $2, $4}' "$work/antes.txt")"
  (( CUR * 100 < MAX * 70 )) || { echo "ABORTA: conexiones $CUR de $MAX (≥ 70 %)." >&2; exit 1; }
  BACKUP_PW="$(openssl rand -hex 24)"; export NEXO_BACKUP_PASSWORD="$BACKUP_PW"
  psql "$ADMIN_URI" -v ON_ERROR_STOP=1 -q -f "$SQL" >/dev/null
  unset NEXO_BACKUP_PASSWORD
  install -m 0600 -o root -g root /dev/null "$ENVF"
  printf 'DATABASE_URL=postgresql://nexoeventos_backup:%s@%s:5432/nexoeventos?%s\n' "$BACKUP_PW" "$ENDPOINT" "$SSL" >"$ENVF"
  chmod 0600 "$ENVF"; unset BACKUP_PW
  echo "OK rol nexoeventos_backup creado (solo lectura) y backup.env escrito (0600)"
  snapshot >"$work/despues.txt"
  if diff <(grep -vE '^(rol_backup_existe|conexiones)\|' "$work/antes.txt") <(grep -vE '^(rol_backup_existe|conexiones)\|' "$work/despues.txt") >"$work/diff.txt"; then
    echo "OK instantánea del catálogo antes/después idéntica: no cambiaron los demás roles, permisos ni objetos"
  else
    echo "DIFF la instantánea cambió (revisar y, si no es esperado, revertir con backup-role-revert.sql):"; cat "$work/diff.txt"
  fi
  ;;
verify)
  [[ -f "$ENVF" && "$(stat -c %a "$ENVF")" == 600 ]] || { echo "Falta $ENVF (0600)." >&2; exit 1; }
  # NO se hace `source`: la URL lleva «&» (sslmode=…&sslrootcert=…) y el shell la cortaría; se lee la línea tal cual (igual que systemd EnvironmentFile)
  DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "$ENVF")"; export DATABASE_URL
  [[ -n "$DATABASE_URL" ]] || { echo "FALLÓ $ENVF no define DATABASE_URL" >&2; exit 1; }
  case "$DATABASE_URL" in *sslmode=verify-full*sslrootcert=*) echo "OK la URL del rol exige sslmode=verify-full con sslrootcert";; *) echo "FALLÓ la URL no exige verify-full"; exit 1;; esac
  psql "$DATABASE_URL" -At -c "select 'OK conexión: usuario='||current_user||' ssl='||(select ssl from pg_stat_ssl where pid=pg_backend_pid())||' sólo_lectura='||current_setting('default_transaction_read_only')"
  psql "$DATABASE_URL" -At -c "select 'OK atributos: super='||rolsuper||' createdb='||rolcreatedb||' createrole='||rolcreaterole||' repl='||rolreplication||' bypassrls='||rolbypassrls||' limite='||rolconnlimit from pg_roles where rolname=current_user"
  psql "$DATABASE_URL" -At -c "select 'OK membresías: '||coalesce(string_agg(g.rolname, ','),'(ninguna)') from pg_auth_members m join pg_roles g on g.oid=m.roleid where m.member=(select oid from pg_roles where rolname=current_user)"
  # pg_dump en TUBERÍA (no se guarda ningún volcado en claro): cabecera PGDMP, tamaño y SHA-256
  pg_dump "$DATABASE_URL" -Fc --no-owner --no-acl | python3 -c '
import hashlib,sys
h=hashlib.sha256(); n=0; head=b""
while True:
    b=sys.stdin.buffer.read(1<<20)
    if not b: break
    if not head: head=b[:5]
    h.update(b); n+=len(b)
print("OK pg_dump -Fc por tubería: cabecera=%s bytes=%d sha256=%s…" % (head.decode("ascii","replace"), n, h.hexdigest()[:12])); sys.exit(0 if head==b"PGDMP" and n>0 else 1)'
  echo "OK huella de datos con el rol de volcado:"; psql "$DATABASE_URL" -At -f "$FP" | sed 's/^/    /'
  deny() { local n="$1"; shift; if psql "$DATABASE_URL" -At -v ON_ERROR_STOP=1 -c "$*" >/dev/null 2>&1; then echo "FALLÓ el rol PUDO: $n"; exit 1; else echo "OK no puede: $n"; fi; }
  deny "escribir (UPDATE sin filas, en transacción de lectura-escritura)" "begin read write; update users set display_name = display_name where false; rollback"
  deny "borrar (DELETE sin filas)" "begin read write; delete from users where false; rollback"
  deny "crear una tabla" "begin read write; create table c04_intruso(i int); rollback"
  deny "crear un rol" "begin read write; create role c04_intruso; rollback"
  deny "cambiar su propia contraseña de rol a superusuario" "begin read write; alter role current_user superuser; rollback"
  ;;
*) echo "Modo desconocido: $MODE" >&2; exit 2;;
esac
