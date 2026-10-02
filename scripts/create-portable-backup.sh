#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="$PROJECT_ROOT/work/portable-backups"
if [[ -z "${PGHOST:-}" || -z "${PGDATABASE:-}" || -z "${PGUSER:-}" || -z "${PGPASSWORD:-}" ]]; then
  echo "Define PGHOST, PGDATABASE, PGUSER y PGPASSWORD para una identidad dedicada de solo lectura." >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$PROJECT_ROOT/work" "$BACKUP_ROOT"
stage="$(mktemp -d "$PROJECT_ROOT/work/nexoeventos-backup.XXXXXX")"
output="$BACKUP_ROOT/nexoeventos-${timestamp}.tar.enc"
cleanup() {
  unset BACKUP_PASSWORD BACKUP_PASSWORD_CONFIRM
  rm -rf -- "$stage"
}
trap cleanup EXIT
umask 077

pg_dump --format=custom --no-owner --no-acl --file="$stage/database.dump"
git -C "$PROJECT_ROOT" archive --format=tar.gz --output="$stage/application-source.tar.gz" HEAD
git -C "$PROJECT_ROOT" rev-parse HEAD >"$stage/git-commit.txt"
pg_restore --list "$stage/database.dump" >"$stage/database-contents.txt"
(cd "$stage" && shasum -a 256 database.dump application-source.tar.gz >SHA256SUMS)

read -rsp "Contraseña del paquete de respaldo (mínimo 20 caracteres): " BACKUP_PASSWORD
echo
read -rsp "Repite la contraseña: " BACKUP_PASSWORD_CONFIRM
echo
if [[ ${#BACKUP_PASSWORD} -lt 20 || "$BACKUP_PASSWORD" != "$BACKUP_PASSWORD_CONFIRM" ]]; then
  echo "Las contraseñas no coinciden o son demasiado cortas." >&2
  exit 1
fi
unset BACKUP_PASSWORD_CONFIRM
tar -C "$stage" -cf - . | \
  openssl enc -aes-256-cbc -pbkdf2 -salt -pass fd:3 -out "$output" 3<<<"$BACKUP_PASSWORD"
unset BACKUP_PASSWORD
chmod 0600 "$output"
echo "Respaldo cifrado creado fuera de Git: $output"
echo "Aún debe copiarse a un destino protegido fuera de la cuenta AWS de origen."
