#!/usr/bin/env bash
# Respaldo LOCAL CIFRADO de lo imprescindible para reconstruir NexoEventos (AWS V2) en otra sesión, cuenta o laboratorio.
#   create [--cert RUTA]          crea work/respaldo-cifrado/nexoeventos-reconstruccion-<fecha>.tar.cms (CMS con la clave PÚBLICA de recuperación; no pide ni imprime contraseñas)
#   verify --key RUTA [--file F]  descifra en un directorio temporal 0700, comprueba hash del paquete, manifiesto, repositorio (git bundle) y ausencia de claves privadas/credenciales; borra el temporal
# Contenido: repositorio (git bundle --all) + archivos modificados o nuevos sin publicar + subconjunto de work/ (tfvars, estado de Terraform, secretos de Ansible, respaldos cifrados de la BD,
# registros de operación, evidencias locales). NO incluye: claves privadas (recovery-private, *.pem, *.key, claves de OCI/SSH), credenciales de AWS Academy, planes de Terraform (*.tfplan),
# cachés de proveedores (.terraform), entornos virtuales, paquetes de release regenerables, work/ia-s14 ni capturas originales sin redactar. No sube nada a ningún servicio externo.
# La CLAVE PRIVADA de recuperación NO está en el paquete a propósito (cifrar la clave dentro de su propio paquete lo haría irrecuperable): debe guardarse aparte (ver docs/operacion/respaldo-local-cifrado.md).
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"   # herramientas del sistema primero (un git de /usr/local sin Rosetta rompe `git bundle`)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"; cd "$ROOT"
OUT="${NEXO_BACKUP_DIR:-$ROOT/work/respaldo-cifrado}"; CMD="${1:-}"; shift || true; CERT=""; KEY=""; FILE=""
while [[ $# -gt 0 ]]; do case "$1" in --cert) CERT="$2"; shift 2;; --key) KEY="$2"; shift 2;; --file) FILE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
umask 077; export COPYFILE_DISABLE=1
say() { printf '%s\n' "$*"; }
TMP=""; cleanup() { [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"; }; trap cleanup EXIT

collect_work_list() {   # lista NUL de archivos de work/ permitidos (sin claves privadas, credenciales, planes ni cachés)
  local dirs=() d; for d in terraform-envs terraform-state ansible ansible-secrets backups portable-backups restauracion evidencias observability failover-lab oci-transfer cloud-readonly carga obs-lab c04; do [[ -d work/$d ]] && dirs+=("work/$d"); done
  { find "${dirs[@]}" -type f -print0 2>/dev/null
    find work/operacion -maxdepth 1 -type f -print0 2>/dev/null
    find work/recovery-keys -maxdepth 2 -type f -name 'recovery-public.crt' -print0 2>/dev/null
    [[ -f work/aws-v1-plan.txt ]] && printf 'work/aws-v1-plan.txt\0'
  } | while IFS= read -r -d '' f; do
      case "$(basename "$f")" in .DS_Store|*.tfplan|*recovery-private*|*private*|*.pem|*.key|*credentials*|id_rsa*|id_ed25519*) continue;; esac
      printf '%s\0' "$f"; done
}
collect_unpublished_list() {   # modificados o nuevos sin publicar (excluye lo ignorado por Git) y que aún existen
  git ls-files -m -o --exclude-standard -z | while IFS= read -r -d '' f; do [[ -f "$f" ]] && printf '%s\0' "$f"; done
}

if [[ "$CMD" == create ]]; then
  [[ -n "$CERT" ]] || CERT="$(ls -t work/recovery-keys/*/recovery-public.crt 2>/dev/null | head -1 || true)"
  [[ -f "$CERT" ]] && grep -q "BEGIN CERTIFICATE" "$CERT" && ! grep -q "PRIVATE" "$CERT" || { echo "Falta el certificado PÚBLICO de recuperación (--cert)." >&2; exit 2; }
  mkdir -p "$OUT"; chmod 700 "$OUT"; TS="$(date -u +%Y%m%dT%H%M%SZ)"; TMP="$(mktemp -d)"; S="$TMP/pkg"; mkdir -p "$S"
  say "1/6 repositorio (git bundle --all)…"; git bundle create "$S/repositorio.bundle" --all >/dev/null 2>&1
  say "2/6 archivos sin publicar (modificados o nuevos)…"; collect_unpublished_list >"$TMP/unp.list"; tar --null -czf "$S/sin-publicar.tar.gz" -T "$TMP/unp.list"
  say "3/6 subconjunto esencial de work/…"; collect_work_list >"$TMP/work.list"; tar --null -czf "$S/work-esencial.tar.gz" -T "$TMP/work.list"
  say "4/6 manifiesto SHA-256 por archivo…"
  { xargs -0 shasum -a 256 <"$TMP/unp.list" | sed 's#  #  sin-publicar/#'; xargs -0 shasum -a 256 <"$TMP/work.list" | sed 's#  #  work-esencial/#'; } >"$S/MANIFIESTO.sha256"
  shasum -a 256 "$S/repositorio.bundle" "$S/sin-publicar.tar.gz" "$S/work-esencial.tar.gz" | sed -E "s#$S/##" >"$S/PARTES.sha256"
  cat >"$S/LEEME-RESTAURAR.txt" <<'R'
NexoEventos — paquete de reconstrucción (cifrado con CMS; descifrar con la clave PRIVADA de recuperación, que NO está aquí).
1) openssl cms -decrypt -binary -inform DER -in <paquete>.tar.cms -inkey <clave-privada> -out paquete.tar      (la clave no se imprime)
2) tar xf paquete.tar ; shasum -a 256 -c PARTES.sha256
3) Repositorio: git clone repositorio.bundle <dir>   (contiene todas las ramas y commits locales)
4) tar xzf sin-publicar.tar.gz -C <dir>   (cambios sin commit y archivos nuevos; reaplicar encima del clon)
5) tar xzf work-esencial.tar.gz -C <dir>  (tfvars, estado de Terraform, secretos de Ansible, respaldos cifrados de la BD, registros) ; permisos 0600/0700
6) Comprobar: shasum -a 256 -c MANIFIESTO.sha256 (rutas relativas a sin-publicar/ y work-esencial/ tras extraer cada tar)
Los recursos de AWS (AMI, instantáneas, secretos, certificados, ALB, RDS) NO están aquí y NO se trasladan a otra cuenta con Terraform: ver docs/operacion/respaldo-local-cifrado.md.
R
  say "5/6 empaquetado y cifrado (CMS, AES-256, clave pública)…"
  ( cd "$S" && tar -cf "$TMP/paquete.tar" . ); P_SHA="$(shasum -a 256 "$TMP/paquete.tar" | cut -d' ' -f1)"
  FINAL="$OUT/nexoeventos-reconstruccion-$TS.tar.cms"
  openssl cms -encrypt -binary -aes-256-cbc -stream -outform DER -in "$TMP/paquete.tar" -out "$FINAL" "$CERT"
  say "6/6 registros…"; chmod 600 "$FINAL"
  printf '%s  paquete.tar (texto plano; solo para comprobar el descifrado)\n' "$P_SHA" >"$OUT/nexoeventos-reconstruccion-$TS.paquete.sha256"
  ( cd "$OUT" && shasum -a 256 "$(basename "$FINAL")" >"$(basename "$FINAL").sha256" )
  UNP=$(tr -cd '\0' <"$TMP/unp.list" | wc -c | tr -d ' '); WRK=$(tr -cd '\0' <"$TMP/work.list" | wc -c | tr -d ' ')
  { echo "# Inventario saneado del respaldo $TS (sin nombres de archivos sensibles ni contenidos)"; echo
    echo "- Paquete cifrado: nexoeventos-reconstruccion-$TS.tar.cms — $(du -h "$FINAL" | cut -f1)"
    echo "- Repositorio (git bundle --all): $(du -h "$S/repositorio.bundle" | cut -f1); ramas y etiquetas: $(git bundle list-heads "$S/repositorio.bundle" | wc -l | tr -d ' ')"
    echo "- Archivos sin publicar (modificados o nuevos): $UNP"; echo "- Archivos esenciales de work/: $WRK"
    echo "- SHA-256 del paquete cifrado: $(cut -d' ' -f1 "$FINAL.sha256")"
    echo "- Cifrado: CMS (AES-256-CBC), clave pública de recuperación; la clave privada NO está en el paquete."; } >"$OUT/nexoeventos-reconstruccion-$TS.inventario.md"
  say "OK: $FINAL ($(du -h "$FINAL" | cut -f1))"; say "Siguiente: scripts/ops/respaldo-reconstruccion.sh verify --key <clave-privada>"
elif [[ "$CMD" == verify ]]; then
  [[ -f "$KEY" ]] || { echo "Falta --key (ruta a la clave privada de recuperación; no se imprime)." >&2; exit 2; }
  [[ -n "$FILE" ]] || FILE="$(ls -t "$OUT"/nexoeventos-reconstruccion-*.tar.cms 2>/dev/null | head -1)"; [[ -f "$FILE" ]] || { echo "No hay paquete .cms en $OUT" >&2; exit 2; }
  BASE="${FILE%.tar.cms}"; ok() { say "OK    $1"; }; ko() { say "FALLÓ $1"; FAILS=$((FAILS+1)); }; FAILS=0; TMP="$(mktemp -d)"
  ( cd "$(dirname "$FILE")" && shasum -a 256 -c "$(basename "$FILE").sha256" >/dev/null 2>&1 ) && ok "SHA-256 del archivo cifrado coincide con el registrado" || ko "SHA-256 del archivo cifrado"
  openssl cms -decrypt -binary -inform DER -in "$FILE" -inkey "$KEY" -out "$TMP/paquete.tar" 2>/dev/null && ok "descifrado con la clave privada" || { ko "no se pudo descifrar"; exit 1; }
  [[ "$(shasum -a 256 "$TMP/paquete.tar" | cut -d' ' -f1)" == "$(cut -d' ' -f1 "$BASE.paquete.sha256")" ]] && ok "el paquete descifrado es idéntico al original (SHA-256)" || ko "hash del paquete descifrado"
  mkdir "$TMP/x" && tar -xf "$TMP/paquete.tar" -C "$TMP/x"
  ( cd "$TMP/x" && shasum -a 256 -c PARTES.sha256 >/dev/null 2>&1 ) && ok "partes del paquete íntegras (repositorio, sin publicar, work)" || ko "PARTES.sha256"
  git bundle verify "$TMP/x/repositorio.bundle" >/dev/null 2>&1 && ok "git bundle válido ($(git bundle list-heads "$TMP/x/repositorio.bundle" | wc -l | tr -d ' ') referencias)" || ko "git bundle"
  mkdir "$TMP/x/sin-publicar" "$TMP/x/work-esencial"; tar -xzf "$TMP/x/sin-publicar.tar.gz" -C "$TMP/x/sin-publicar"; tar -xzf "$TMP/x/work-esencial.tar.gz" -C "$TMP/x/work-esencial"
  ( cd "$TMP/x" && shasum -a 256 -c MANIFIESTO.sha256 2>/dev/null | grep -vc ': OK$' ) >"$TMP/bad.txt" || true
  [[ "$(cat "$TMP/bad.txt")" == 0 ]] && ok "manifiesto: todos los archivos extraídos coinciden con su SHA-256 ($(wc -l <"$TMP/x/MANIFIESTO.sha256" | tr -d ' ') archivos)" || ko "manifiesto ($(cat "$TMP/bad.txt") discrepancias)"
  n=$(find "$TMP/x/sin-publicar" "$TMP/x/work-esencial" -type f \( -name '*private*' -o -name '*.pem' -o -name '*.key' -o -name '*credentials*' -o -name '*.tfplan' \) | wc -l | tr -d ' '); [[ "$n" == 0 ]] && ok "sin archivos de claves privadas, credenciales ni planes por nombre" || ko "archivos sensibles por nombre: $n"
  PAT="BEGIN [A-Z ]*PRIVATE KEY|aws_session_token|aws_secret_access_key|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}"
  mw=$( { grep -rIlE "$PAT" "$TMP/x/work-esencial" 2>/dev/null || true; } | wc -l | tr -d ' '); [[ "$mw" == 0 ]] && ok "work-esencial: ningún archivo de texto con claves privadas o credenciales de AWS reales por patrón" || ko "work-esencial contiene $mw archivo(s) con patrones de claves/credenciales"
  ms=$( { grep -rIlE "$PAT" "$TMP/x/sin-publicar" 2>/dev/null || true; } | wc -l | tr -d ' '); say "INFO  sin-publicar: $ms archivo(s) de código o documentación que NOMBRAN esos patrones (detectores y pruebas); solo se cuentan por tipo:"
  { grep -rIlE "$PAT" "$TMP/x/sin-publicar" 2>/dev/null || true; } | sed -E "s#$TMP/x/sin-publicar/##; s#/[^/]*\$##" | sort | uniq -c | sed 's/^/        /'
  tp=$( { tar -tzf "$TMP/x/work-esencial.tar.gz" | /usr/bin/grep -c "terraform-state/" || true; } ); say "INFO  archivos de estado de Terraform incluidos: $tp"
  (( FAILS == 0 )) && say "VERIFICACIÓN COMPLETA: el respaldo se abre y su contenido coincide" || { say "$FAILS FALLO(S)"; exit 1; }
else
  echo "Uso: $0 create [--cert RUTA] | verify --key RUTA [--file PAQUETE.tar.cms]" >&2; exit 2
fi
