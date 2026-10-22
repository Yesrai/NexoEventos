#!/usr/bin/env bash
# Genera el par de claves INDEPENDIENTE para la copia de recuperación en OCI (distinto del par usado en AWS). Se ejecuta SOLO por la usuaria cuando decida
# generar la clave real: la clave PRIVADA queda fuera del repositorio (por defecto ~/.nexoeventos/recovery-oci/, modo 0700/0600) y con frase de paso;
# solo el CERTIFICADO público se usa para cifrar. Se rechaza cualquier destino dentro del repositorio. No imprime la clave.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="${NEXO_OCI_KEYDIR:-$HOME/.nexoeventos/recovery-oci}"
case "$(cd "$(dirname "$DIR")" 2>/dev/null && pwd)/$(basename "$DIR")" in "$ROOT"/*) echo "Rechazado: el directorio de claves no puede estar dentro del repositorio." >&2; exit 1;; esac
[[ ! -e "$DIR/oci-recovery-private.pem" ]] || { echo "Ya existe una clave en $DIR; no se sobrescribe." >&2; exit 2; }
umask 077; mkdir -p "$DIR"
if [[ "${NEXO_TEST_NO_PASSPHRASE:-}" == 1 ]]; then   # solo pruebas locales con claves desechables
  openssl genrsa -out "$DIR/oci-recovery-private.pem" 3072 2>/dev/null
else
  openssl genrsa -aes256 -out "$DIR/oci-recovery-private.pem" 3072   # solicita la frase de paso
fi
openssl req -new -x509 -key "$DIR/oci-recovery-private.pem" -sha256 -days 1095 -subj "/CN=NexoEventos OCI recovery" -out "$DIR/oci-recovery-public.crt"

chmod 600 "$DIR/oci-recovery-private.pem"; chmod 644 "$DIR/oci-recovery-public.crt"
echo "Certificado público: $DIR/oci-recovery-public.crt  (huella: $(openssl x509 -in "$DIR/oci-recovery-public.crt" -noout -fingerprint -sha256 | cut -d= -f2))"
echo "Guarde la clave privada y su frase de paso fuera de línea; sin ellas el respaldo en OCI no se puede restaurar."
