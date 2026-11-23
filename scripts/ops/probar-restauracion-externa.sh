#!/usr/bin/env bash
# Prueba de restauración DESDE LA COPIA EXTERNA (solo lectura sobre la copia; escribe únicamente en un temporal 0700 que se borra).
#   probar-restauracion-externa.sh --dir RUTA_DE_LA_COPIA --key RUTA_CLAVE_PROTEGIDA [--expect-head SHA_CORTO]
# RUTA_DE_LA_COPIA contiene el .tar.cms y su .tar.cms.sha256. La frase de paso la pide OpenSSL en el terminal (sin eco);
# nunca va en argumentos. No imprime claves ni contenido. No toca AWS ni ningún servicio.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"; umask 077
DIR=""; KEY=""; EXPECT_HEAD=""
while [[ $# -gt 0 ]]; do case "$1" in --dir) DIR="$2"; shift 2;; --key) KEY="$2"; shift 2;; --expect-head) EXPECT_HEAD="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -d "$DIR" && -f "$KEY" ]] || { echo "Uso: $0 --dir <copia externa> --key <clave protegida>" >&2; exit 2; }
CMS="$(ls "$DIR"/nexoeventos-reconstruccion-*.tar.cms | tail -1)"; [[ -f "$CMS.sha256" ]] || { echo "Falta $(basename "$CMS").sha256" >&2; exit 1; }
TMP="$(mktemp -d)"; chmod 700 "$TMP"; # Los packs de git se extraen en solo lectura (0444): sin `chmod u+w`, `rm -r` en un terminal interactivo PREGUNTA «override?» por cada uno
# y, con stderr silenciado, parece colgado (ocurrió el 22-nov-2026). Se hacen escribibles primero y `rm` no puede preguntar (</dev/null).
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -r "$TMP" </dev/null || echo "AVISO: no se pudo borrar el temporal $TMP (contiene el paquete descifrado): bórrelo a mano" >&2' EXIT
ok() { echo "OK    $*"; }; ko() { echo "FALLO $*"; exit 1; }
( cd "$DIR" && shasum -a 256 -c "$(basename "$CMS").sha256" >/dev/null 2>&1 ) && ok "SHA-256 de la copia externa correcto" || ko "el SHA-256 no coincide (copia dañada)"
openssl cms -decrypt -binary -inform DER -in "$CMS" -inkey "$KEY" -out "$TMP/paquete.tar" 2>/dev/null && ok "descifrado con la clave protegida (la frase se pidió en el terminal)" || ko "no se pudo descifrar (¿frase incorrecta?)"
( cd "$TMP" && tar xf paquete.tar && shasum -a 256 -c PARTES.sha256 >/dev/null 2>&1 ) && ok "partes del paquete íntegras" || ko "partes dañadas"
git bundle verify "$TMP/repositorio.bundle" >/dev/null 2>&1 && ok "git bundle válido" || ko "git bundle inválido"
git clone -q "$TMP/repositorio.bundle" "$TMP/clon" 2>/dev/null && ok "repositorio clonado ($(git -C "$TMP/clon" rev-list --count HEAD) commits, HEAD $(git -C "$TMP/clon" rev-parse --short HEAD))" || ko "no se pudo clonar"
if [[ -n "$EXPECT_HEAD" ]]; then [[ "$(git -C "$TMP/clon" rev-parse HEAD)" == "$EXPECT_HEAD"* ]] && ok "HEAD del clon = $EXPECT_HEAD" || ko "HEAD del clon distinto del esperado ($EXPECT_HEAD)"; fi
mkdir "$TMP/su" "$TMP/we"; tar xzf "$TMP/sin-publicar.tar.gz" -C "$TMP/su"; tar xzf "$TMP/work-esencial.tar.gz" -C "$TMP/we"
( cd "$TMP/su" && grep '  sin-publicar/' ../MANIFIESTO.sha256 | sed 's#  sin-publicar/#  #' | shasum -a 256 -c >/dev/null 2>&1 ) && ok "archivos sin publicar coinciden con el manifiesto" || ko "archivos sin publicar dañados"
( cd "$TMP/we" && grep '  work-esencial/' ../MANIFIESTO.sha256 | sed 's#  work-esencial/#  #' | shasum -a 256 -c >/dev/null 2>&1 ) && ok "archivos de work/ coinciden con el manifiesto" || ko "archivos de work/ dañados"
echo "PRUEBA COMPLETA: la copia externa permite reconstruir. Temporal borrado al salir."
