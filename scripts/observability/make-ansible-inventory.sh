#!/usr/bin/env bash
# Genera ansible/monitoring-inventory.yml (0600, ignorado por Git) a partir de `terraform output` y del tfvars local, SIN imprimir IP, correo ni identificadores.
# Requiere la VM creada. Uso: scripts/observability/make-ansible-inventory.sh [--key ~/.ssh/nexoeventos_azure] [--out ansible/monitoring-inventory.yml]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; KEY="$HOME/.ssh/nexoeventos_azure"; OUT="$ROOT/ansible/monitoring-inventory.yml"; TFV="$ROOT/work/terraform-envs/azure-vm.tfvars"
while [[ $# -gt 0 ]]; do case "$1" in --key) KEY="$2"; shift 2;; --out) OUT="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
GIT="$(for c in /usr/bin/git "$(command -v git || true)"; do [[ -x "$c" ]] && "$c" --version >/dev/null 2>&1 && { echo "$c"; break; }; done)"; [[ -n "$GIT" ]] || { echo "Ningún Git ejecutable." >&2; exit 3; }
rc=0; "$GIT" -C "$ROOT" check-ignore -q "$OUT" 2>/dev/null || rc=$?; [[ $rc == 0 ]] || { echo "ERROR: $OUT no está ignorado por Git o Git falló (código $rc); no se escribe." >&2; exit 1; }
IP="$(terraform -chdir="$ROOT/infra/azure" output -raw monitoring_vm_public_ip 2>/dev/null || true)"; FQDN="$(terraform -chdir="$ROOT/infra/azure" output -raw monitoring_vm_fqdn 2>/dev/null || true)"
[[ "$IP" =~ ^[0-9.]+$ && -n "$FQDN" ]] || { echo "La VM aún no existe (terraform output vacío). Cree la VM con el plan autorizado primero." >&2; exit 1; }
CIDR="$(grep -oE '^admin_cidr *= *"[^"]+"' "$TFV" | cut -d'"' -f2)"; SUB="$(grep -oE '^subscription_id *= *"[^"]+"' "$TFV" | cut -d'"' -f2)"
KH="$ROOT/work/ssh/azure_known_hosts"
[[ -s "$KH" ]] || { echo "Falta $KH: verifique primero la huella con scripts/observability/azure-verify-hostkey.sh (no se acepta ninguna huella sin verificar)." >&2; exit 1; }
[[ "$CIDR" == */32 && -n "$SUB" ]] || { echo "No se pudieron leer admin_cidr y subscription_id de $TFV" >&2; exit 1; }
umask 077; cat > "$OUT" <<EOF
---
# Generado por make-ansible-inventory.sh (0600, ignorado por Git). Contiene la IP de la VM y la del operador.
all:
  children:
    monitoring:
      hosts:
        azure-obs:
          ansible_host: "$IP"
          ansible_user: nexoadmin
          ansible_ssh_private_key_file: "$KEY"
          # Huella verificada ANTES por otro canal (azure-verify-hostkey.sh); solo se acepta esa clave. Nada de StrictHostKeyChecking=no / accept-new.
          ansible_ssh_common_args: "-o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KH -o GlobalKnownHostsFile=/dev/null -o HashKnownHosts=no -o IdentitiesOnly=yes"
      vars:
        monitoring_fqdn: "$FQDN"
        monitoring_admin_cidr: "$CIDR"
        grafana_azure_subscription_id: "$SUB"
        nexo_probe_host: "nexoeventos-demo.duckdns.org"
EOF
chmod 600 "$OUT"; echo "Inventario escrito en ${OUT#$ROOT/} (0600, ignorado por Git); datos no mostrados."
