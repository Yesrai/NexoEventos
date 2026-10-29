#!/usr/bin/env bash
# Verifica la huella SSH de la VM de Azure por un canal DISTINTO al de SSH antes de aceptarla (nada de StrictHostKeyChecking=no / accept-new):
#   1) lee del registro de arranque (consola serie, autenticado por Azure CLI) las huellas PÚBLICAS que imprimió cloud-init;
#   2) obtiene las claves por red con ssh-keyscan y calcula sus huellas;
#   3) solo si COINCIDEN (ED25519 obligatoria; cualquier otro tipo presente en ambos lados debe coincidir) escribe un known_hosts dedicado (0600).
# Si falta la huella, hay diferencia o se agota el tiempo, sale con error y NO escribe nada. No imprime IP ni correo.
# Uso: scripts/observability/azure-verify-hostkey.sh [--known-hosts work/ssh/azure_known_hosts] [--wait-seconds 600] [--interval 15]
# Pruebas: AZ_BIN, KEYSCAN_BIN, KEYGEN_BIN, NEXO_HOST, NEXO_FQDN permiten sustituir herramientas y destino.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RG="rg-nexoeventos-observabilidad"; VM="vm-nexoeventos-obs"; KH="$ROOT/work/ssh/azure_known_hosts"; WAIT=600; INT=15
AZ="${AZ_BIN:-az}"; KS="${KEYSCAN_BIN:-ssh-keyscan}"; KG="${KEYGEN_BIN:-ssh-keygen}"
while [[ $# -gt 0 ]]; do case "$1" in --known-hosts) KH="$2"; shift 2;; --wait-seconds) WAIT="$2"; shift 2;; --interval) INT="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
HOST="${NEXO_HOST:-$(terraform -chdir="$ROOT/infra/azure" output -raw monitoring_vm_public_ip 2>/dev/null || true)}"
FQDN="${NEXO_FQDN:-$(terraform -chdir="$ROOT/infra/azure" output -raw monitoring_vm_fqdn 2>/dev/null || true)}"
[[ "$HOST" =~ ^[0-9.]+$ && -n "$FQDN" ]] || { echo "La VM aún no existe (terraform output vacío)." >&2; exit 1; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT; umask 077

# 1) Huellas desde la consola serie (canal de Azure). Se reintenta hasta que cloud-init las haya impreso.
fp_get() { case "$1" in ED25519) echo "${FP_ED25519:-}";; ECDSA) echo "${FP_ECDSA:-}";; RSA) echo "${FP_RSA:-}";; esac; }   # bash 3.2 (macOS): sin arrays asociativos
deadline=$((SECONDS+WAIT)); ESC=$'\x1b'
while :; do
  # `az` entrega el registro como UNA cadena JSON con \r\n escapados: se decodifica antes de leerlo por líneas (si ya viene en texto plano, se usa tal cual).
  "$AZ" vm boot-diagnostics get-boot-log -g "$RG" -n "$VM" 2>/dev/null | python3 -c 'import sys,json
t=sys.stdin.read().strip()
try: t=json.loads(t) if t.startswith(chr(34)) else t
except Exception: pass
sys.stdout.write(t.replace(chr(13),chr(10)))' | sed "s/${ESC}\[[0-9;]*[A-Za-z]//g" > "$T/boot.log" || true
  FP_ED25519=""; FP_ECDSA=""; FP_RSA=""
  while read -r _ _ fp _ ty; do
    [[ "$fp" =~ ^SHA256:[A-Za-z0-9+/]{43}$ ]] || continue
    case "$ty" in "(ED25519)") FP_ED25519="$fp";; "(ECDSA)") FP_ECDSA="$fp";; "(RSA)") FP_RSA="$fp";; esac
  done < <(command grep -a 'NEXO-HOSTKEY' "$T/boot.log" | sed 's/.*NEXO-HOSTKEY/NEXO-HOSTKEY/' || true)
  [[ -n "$FP_ED25519" ]] && break
  (( SECONDS >= deadline )) && { echo "ERROR: el registro de arranque no contiene la huella ED25519 tras ${WAIT}s. NO se acepta ninguna clave; no se escribió known_hosts." >&2; exit 1; }
  sleep "$INT"
done

# 2) Claves por red y sus huellas
"$KS" -T 10 -t ed25519,ecdsa,rsa "$HOST" 2>/dev/null | command grep -a -v '^#' > "$T/scan.txt" || true
[[ -s "$T/scan.txt" ]] || { echo "ERROR: ssh-keyscan no devolvió claves (¿NSG/IP del operador?). No se escribió known_hosts." >&2; exit 1; }
: > "$T/verified.txt"; bad=0; ok_types=""
while read -r _ ktype kdata _; do
  case "$ktype" in ssh-ed25519) ty=ED25519;; ecdsa-sha2-nistp256) ty=ECDSA;; ssh-rsa) ty=RSA;; *) continue;; esac
  fp="$("$KG" -lf <(echo "x $ktype $kdata") 2>/dev/null | awk '{print $2}')"
  [[ -n "$fp" ]] || continue
  want="$(fp_get "$ty")"; [[ -n "$want" ]] || continue                       # tipo que Azure no declaró: no se confía ni se guarda
  if [[ "$fp" == "$want" ]]; then echo "$HOST,$FQDN $ktype $kdata" >> "$T/verified.txt"; ok_types+="$ty "
  else echo "ERROR: la huella $ty de la red DIFERENTE de la del registro de arranque (posible intermediario o VM equivocada)." >&2; bad=1; fi
done < "$T/scan.txt"
(( bad == 0 )) || { echo "No se escribió known_hosts." >&2; exit 1; }
[[ " $ok_types " == *" ED25519 "* ]] || { echo "ERROR: la clave ED25519 de la red no pudo verificarse. No se escribió known_hosts." >&2; exit 1; }

# 3) known_hosts dedicado, solo con claves verificadas
mkdir -p "$(dirname "$KH")"; chmod 700 "$(dirname "$KH")"; cp "$T/verified.txt" "$KH.tmp"; chmod 600 "$KH.tmp"; mv "$KH.tmp" "$KH"
echo "Huella verificada por dos canales (consola serie de Azure = red). Tipos aceptados: ${ok_types}"
echo "ED25519 (pública): $FP_ED25519"
echo "known_hosts escrito en ${KH#$ROOT/} (0600). Conéctese solo con: -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<ese archivo>"
