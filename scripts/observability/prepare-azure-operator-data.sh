#!/usr/bin/env bash
# Prepara work/terraform-envs/azure.tfvars (0600, ignorado por Git) con tus datos de operador, SIN imprimirlos completos ni dejarlos en logs o en el historial:
#   · IP pública /32 (se consulta a un servicio de «¿cuál es mi IP?» y solo se muestra enmascarada)
#   · correo de alertas (se lee con `read`; no se pasa por argumentos de línea de comandos)
#   · clave PÚBLICA SSH (la privada nunca se toca; se comprueba que esté protegida con frase de paso)
#   · etiqueta DNS gratuita (se comprueba su disponibilidad en Azure, solo lectura)
# Uso: scripts/observability/prepare-azure-operator-data.sh [--ssh-pub ~/.ssh/nexoeventos_azure.pub] [--dns-label etiqueta] [--out ruta] [--dry-run] [--force]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; OUT="$ROOT/work/terraform-envs/azure.tfvars"; PUB="$HOME/.ssh/nexoeventos_azure.pub"; LABEL=""; DRY=0; FORCE=0
while [[ $# -gt 0 ]]; do case "$1" in --ssh-pub) PUB="$2"; shift 2;; --dns-label) LABEL="$2"; shift 2;; --out) OUT="$2"; shift 2;; --dry-run) DRY=1; shift;; --force) FORCE=1; shift;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
# --- Git: se usa el primero que se EJECUTE (en algunos Mac /usr/local/bin/git es un binario Intel sin Rosetta: «Bad CPU type in executable») ---
pick_git() {
  local c
  for c in "${NEXO_GIT:-}" "$(command -v git 2>/dev/null || true)" /usr/bin/git /Library/Developer/CommandLineTools/usr/bin/git /opt/homebrew/bin/git; do
    [[ -n "$c" && -x "$c" ]] && "$c" --version >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  return 1
}
GIT="$(pick_git)" || { echo "ERROR: ningún Git se puede ejecutar en este equipo (¿Bad CPU type?). No se escribió nada. Revise su PATH o use /usr/bin/git (Apple Git)." >&2; exit 3; }
# Comprueba que una ruta esté ignorada: 0 = ignorada; 1 = NO ignorada; otro código = Git falló (nunca se interpreta como «no ignorada»).
assert_ignored() {
  local rc=0; "$GIT" -C "$ROOT" check-ignore -q "$1" 2>/dev/null || rc=$?
  case "$rc" in
    0) return 0;;
    1) echo "ERROR: $1 NO está ignorado por Git; no se escribe." >&2; return 1;;
    *) echo "ERROR: Git no pudo verificar si $1 está ignorado (código $rc, Git: $GIT). No se escribe nada." >&2; return 3;;
  esac
}
case "$OUT" in "$ROOT"/work/*) ;; *) echo "Rechazado: la salida debe estar en work/ (ignorado por Git)." >&2; exit 1;; esac
assert_ignored "$OUT" || exit $?
[[ ! -e "$OUT" || $FORCE == 1 || $DRY == 1 ]] || { echo "Ya existe $OUT (use --force para reescribirlo)." >&2; exit 1; }
mask_ip() { awk -F. '{print $1"."$2".x.x"}' <<<"$1"; }
mask_mail() { sed -E 's/^(.).*@(.*)$/\1***@\2/' <<<"$1"; }
# --- IP /32 ---
IP="${NEXO_ADMIN_IP:-$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')}"
[[ "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo "No se pudo obtener una IPv4 válida." >&2; exit 1; }
# --- correo ---
if [[ -n "${NEXO_ALERT_EMAIL:-}" ]]; then MAIL="$NEXO_ALERT_EMAIL"; else read -r -p "Correo para alertas y presupuesto de Azure: " MAIL; fi
[[ "$MAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || { echo "Correo no válido." >&2; exit 1; }
# --- clave pública SSH ---
[[ -f "$PUB" ]] || { echo "No existe $PUB. Genere la clave con: ssh-keygen -t ed25519 -a 100 -f ~/.ssh/nexoeventos_azure (con frase de paso)." >&2; exit 1; }
PUBTXT="$(cat "$PUB")"; [[ "$PUBTXT" == ssh-ed25519\ * ]] || { echo "La clave pública debe ser ed25519." >&2; exit 1; }
PRIV="${PUB%.pub}"
if [[ -f "$PRIV" ]]; then
  if ssh-keygen -y -P "" -f "$PRIV" >/dev/null 2>&1; then echo "AVISO: la clave privada NO tiene frase de paso; regenérela con una." >&2; exit 1; fi
  echo "Clave privada: protegida con frase de paso (no se leyó su contenido)."
fi
# --- etiqueta DNS (disponibilidad en centralus; solo lectura) ---
[[ -n "$LABEL" ]] || LABEL="nexoeventos-obs-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
SUB="$(az account show --query id -o tsv)"
AV="$(az rest --method get --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.Network/locations/centralus/CheckDnsNameAvailability?domainNameLabel=$LABEL&api-version=2023-09-01" --query available -o tsv 2>/dev/null || echo desconocido)"
[[ "$AV" == "true" ]] || { echo "La etiqueta DNS '$LABEL' no está disponible ($AV)." >&2; exit 1; }
echo "Resumen (enmascarado): IP $(mask_ip "$IP")/32 · correo $(mask_mail "$MAIL") · clave ${PUBTXT%% *} · etiqueta DNS $LABEL · región centralus · VM Standard_D2s_v4"
[[ $DRY == 1 ]] && { echo "[dry-run] no se escribió nada."; exit 0; }
umask 077; mkdir -p "$(dirname "$OUT")"
cat > "$OUT" <<EOF
# Generado por prepare-azure-operator-data.sh (datos del operador; NO subir a Git: work/ y *.tfvars están ignorados)
subscription_id      = "$SUB"
azure_region         = "centralus"
vm_size              = "Standard_D2s_v4"
create_monitoring_vm = false          # pasar a true SOLO para el plan/apply de la VM (ventana autorizada)
admin_cidr           = "$IP/32"
ssh_public_key       = "$PUBTXT"
alert_emails         = ["$MAIL"]
dns_label            = "$LABEL"
EOF
chmod 600 "$OUT"
rc=0; assert_ignored "$OUT" || rc=$?
if [[ $rc == 1 ]]; then rm -f "$OUT"; echo "Archivo eliminado por no estar ignorado." >&2; exit 1; fi
[[ $rc == 0 ]] || { echo "AVISO: el archivo se conserva en work/ (la comprobación previa fue correcta) pero no se pudo reverificar: revise Git antes de continuar." >&2; exit $rc; }
echo "Escrito en $OUT (0600, ignorado por Git: verificado con $GIT)."
