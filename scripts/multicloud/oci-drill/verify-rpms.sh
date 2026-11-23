#!/usr/bin/env bash
# Verifica los RPM de PostgreSQL contra la lista fijada (SHA-256 verificados el 23-oct-2026, ver docs/multicloud/07-simulacro-oci.md). Se usa en la estación local (antes de copiar)
# y en la VM (antes de instalar): una copia dañada o sustituida se detecta en ambos extremos. Portátil: shasum (macOS) o sha256sum (Linux).
# Uso: verify-rpms.sh <directorio-con-rpms> [lista.sha256]    Salida: 0 todos coinciden y no sobra ningún .rpm no listado · 1 hay diferencias · 2 uso/archivos ausentes
set -euo pipefail
DIR="${1:?directorio con los RPM}"; SUMS="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/rpm-checksums.sha256}"
[[ -d "$DIR" ]] || { echo "ERROR: no existe $DIR" >&2; exit 2; }; [[ -f "$SUMS" ]] || { echo "ERROR: no existe la lista $SUMS" >&2; exit 2; }
if command -v sha256sum >/dev/null; then H=(sha256sum); else H=(shasum -a 256); fi
bad=0
while read -r want name; do
  [[ -z "$want" ]] && continue
  [[ -f "$DIR/$name" ]] || { echo "FALTA  $name" >&2; bad=1; continue; }
  got="$("${H[@]}" "$DIR/$name" | cut -d' ' -f1)"
  if [[ "$got" == "$want" ]]; then echo "OK     $name"; else echo "DIFIERE $name (esperado ${want:0:12}…, obtenido ${got:0:12}…)" >&2; bad=1; fi
done < "$SUMS"
for f in "$DIR"/*.rpm; do [[ -e "$f" ]] || continue; grep -q " $(basename "$f")\$" "$SUMS" || { echo "SOBRA  $(basename "$f") (no está en la lista fijada)" >&2; bad=1; }; done
[[ $bad -eq 0 ]] && echo "OK    RPM verificados contra la lista fijada" || exit 1
