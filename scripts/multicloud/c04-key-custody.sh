#!/usr/bin/env bash
# C-04: custodia de la clave privada de recuperación (la que descifra los respaldos). NUNCA imprime la clave; solo booleanos. La clave no sale de la Mac ni va a Git/AWS/OCI.
#   check   --src CLAVE --cert CERT          permisos/propietario, no rastreada por Git, y su clave pública corresponde al certificado
#   copy    --src CLAVE --dest-dir DIR       copia a un directorio 0700 fuera del repositorio (archivo 0600, sin sobrescribir; verifica hash idéntico)
#   protect --src CLAVE --dest-dir DIR       crea DIR/recovery-private.protected.pem cifrada con una frase NUEVA que se teclea aquí (dos veces, sin eco, mínimo 12 caracteres)
#   verify  --key CLAVE_PROTEGIDA [--stem ID] prueba REAL: descifra un respaldo C-04 con esa clave (pide la frase) y comprueba hash/tamaño contra el manifiesto
# La frase viaja por un descriptor (printf interno → openssl -passout/-passin fd:N); no hay variables de entorno, archivos temporales ni argumentos con ella.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
MODE="${1:-}"; shift || true; SRC=""; CERT=""; DEST=""; KEY=""; STEM=""; FROMDIR=""; CERT_SHA=""
while [[ $# -gt 0 ]]; do case "$1" in --src) SRC="$2"; shift 2;; --cert) CERT="$2"; shift 2;; --dest-dir) DEST="$2"; shift 2;; --key) KEY="$2"; shift 2;; --stem) STEM="$2"; shift 2;; --from-dir) FROMDIR="$2"; shift 2;; --cert-sha256) CERT_SHA="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
ok() { echo "OK    $*"; }; bad() { echo "FALLÓ $*" >&2; exit 1; }
pubhash() { openssl pkey -in "$1" -pubout 2>/dev/null | openssl sha256 | awk '{print $NF}'; }
case "$MODE" in
check)
  [[ -f "$SRC" && ! -L "$SRC" ]] || bad "la clave no existe o es un enlace"
  [[ "$(stat -f %Lp "$SRC" 2>/dev/null || stat -c %a "$SRC")" == 600 ]] && ok "permisos 0600" || bad "permisos distintos de 0600"
  [[ "$(stat -f %u "$SRC" 2>/dev/null || stat -c %u "$SRC")" == "$(id -u)" ]] && ok "propietario = usuario actual" || bad "propietario distinto del usuario actual"
  GIT=/usr/bin/git; [[ -x "$GIT" ]] || GIT=git; SD="$(cd "$(dirname "$SRC")" && pwd)"; SA="$SD/$(basename "$SRC")"
  inside="$("$GIT" -C "$SD" rev-parse --is-inside-work-tree 2>/dev/null || true)"
  if [[ "$inside" == true ]]; then
    "$GIT" -C "$SD" ls-files --error-unmatch "$SA" >/dev/null 2>&1 && bad "la clave está RASTREADA por Git" || ok "no está rastreada por Git"
    [[ -z "$("$GIT" -C "$SD" log --all --oneline -- "$SA" 2>/dev/null | head -1)" ]] && ok "nunca estuvo en el historial de Git" || bad "la clave aparece en el historial de Git"
    "$GIT" -C "$SD" check-ignore -q "$SA" && ok "ignorada por .gitignore" || echo "AVISO la ruta no está en .gitignore"
  elif "$GIT" --version >/dev/null 2>&1; then ok "fuera de un repositorio Git"
  else echo "AVISO no se pudo ejecutar git: no se comprobó el seguimiento en Git"; fi
  if grep -q -E 'ENCRYPTED' "$SRC"; then echo "AVISO la clave ya está cifrada con frase: no se puede comprobar su correspondencia sin la frase"
  else [[ -n "$CERT" ]] || bad "indique --cert"; [[ "$(pubhash "$SRC")" == "$(openssl x509 -in "$CERT" -noout -pubkey | openssl sha256 | awk '{print $NF}')" ]] && ok "la clave privada corresponde al certificado (huella SHA-256 del cert: $(openssl x509 -in "$CERT" -outform DER | openssl sha256 | awk '{print $NF}'))" || bad "la clave privada NO corresponde al certificado"; fi ;;
copy)
  [[ -f "$SRC" && -n "$DEST" ]] || bad "uso: copy --src CLAVE --dest-dir DIR"
  case "$(cd "$(dirname "$DEST")" 2>/dev/null && pwd)/$(basename "$DEST")" in "$ROOT"/*) bad "el destino no puede estar dentro del repositorio";; esac
  umask 077; mkdir -p "$DEST"; chmod 700 "$DEST"; T="$DEST/recovery-private.pem"
  [[ ! -e "$T" ]] || bad "ya existe $T; no se sobrescribe"
  cp "$SRC" "$T"; chmod 600 "$T"   # cp no imprime el contenido
  [[ "$(openssl sha256 <"$SRC" | awk '{print $NF}')" == "$(openssl sha256 <"$T" | awk '{print $NF}')" ]] && ok "copia idéntica (SHA-256 igual); original intacto" || { rm -f "$T"; bad "la copia no es idéntica"; }
  [[ "$(stat -f %Lp "$T" 2>/dev/null || stat -c %a "$T")" == 600 && "$(stat -f %Lp "$DEST" 2>/dev/null || stat -c %a "$DEST")" == 700 ]] && ok "archivo 0600 y directorio 0700" ;;
protect)
  [[ -f "$SRC" && -n "$DEST" && -t 0 ]] || bad "uso: protect --src CLAVE --dest-dir DIR, en una terminal interactiva"
  umask 077; mkdir -p "$DEST"; chmod 700 "$DEST"; O="$DEST/recovery-private.protected.pem"
  [[ ! -e "$O" ]] || bad "ya existe $O; no se sobrescribe"
  grep -q ENCRYPTED "$SRC" && bad "la clave de origen ya está protegida"
  for try in 1 2 3; do
    IFS= read -r -s -p "NUEVA frase de paso (mín. 12 caracteres; no se muestra): " P1; echo; IFS= read -r -s -p "Repítela: " P2; echo
    [[ "$P1" == "$P2" && ${#P1} -ge 12 ]] && break; echo "No coinciden o tiene menos de 12 caracteres."; P1=""; P2=""
  done
  [[ -n "$P1" ]] || bad "no se obtuvo una frase válida"
  exec 4< <(printf '%s\n' "$P1"); unset P1 P2
  openssl pkcs8 -topk8 -v2 aes-256-cbc -iter 600000 -in "$SRC" -out "$O" -passout fd:4 2>/dev/null || { exec 4<&-; rm -f "$O"; bad "no se pudo cifrar la clave"; }
  exec 4<&-; chmod 600 "$O"; ok "copia protegida creada (AES-256-CBC, PBKDF2 600000 iteraciones, 0600). La frase NO se guardó en ningún sitio: anótala fuera de línea AHORA."
  grep -q 'BEGIN ENCRYPTED PRIVATE KEY' "$O" && ok "formato PKCS#8 cifrado" ;;
verify)
  [[ -n "$KEY" ]] || bad "uso: verify --key CLAVE_PROTEGIDA"
  args=(--decrypt-only --key "$KEY"); [[ -n "$CERT" ]] && args+=(--cert "$CERT"); [[ -n "${CERT_SHA:-}" ]] && args+=(--cert-sha256 "$CERT_SHA"); [[ -n "$STEM" ]] && args+=(--stem "$STEM"); [[ -n "$FROMDIR" ]] && args+=(--from-dir "$FROMDIR")
  bash "$HERE/c04-restore-local.sh" "${args[@]}" ;;
*) echo "Modos: check | copy | protect | verify" >&2; exit 2 ;;
esac
