#!/usr/bin/env bash
# Verificación de SOLO LECTURA de lo que Azure podría seguir facturando. Se ejecuta después de destruir o desasignar y deja la salida como evidencia.
#   --expect none   tras destruir TODO: no debe existir el grupo de recursos ni ningún recurso facturable suyo
#   --expect base   tras destruir la VM: solo recursos de la base (sin VM, discos, IP pública ni NIC)
#   --expect vm-off tras desasignar: la VM debe estar «deallocated» (los discos y la IP siguen facturándose y se listan)
set -euo pipefail
EXPECT="${1:---expect}"; [[ "$EXPECT" == --expect ]] && EXPECT="${2:-none}"; [[ "$EXPECT" == --expect=* ]] && EXPECT="${EXPECT#--expect=}"
RG=rg-nexoeventos-observabilidad; fail=0
say() { printf '%-46s %s\n' "$1" "$2"; }
rg_exists="$(az group exists -n "$RG")"; say "Grupo de recursos $RG" "$rg_exists"
count() { az "$@" --query 'length(@)' -o tsv 2>/dev/null || echo 0; }
if [[ "$rg_exists" == true ]]; then
  vms="$(count vm list -g "$RG")"; disks="$(count disk list -g "$RG")"; pips="$(count network public-ip list -g "$RG")"; nics="$(count network nic list -g "$RG")"
  say "Máquinas virtuales" "$vms"; say "Discos administrados (facturan aunque la VM esté apagada)" "$disks"; say "IP públicas (facturan mientras existan)" "$pips"; say "Interfaces de red" "$nics"
  say "Espacios de trabajo de Log Analytics" "$(count monitor log-analytics workspace list -g "$RG")"
  az vm list -g "$RG" -d --query '[].{vm:name,estado:powerState,tamaño:hardwareProfile.vmSize}' -o table 2>/dev/null || true
fi
# Conteos en TODA la suscripción por tipo de recurso (si una consulta falla, el resultado es «?» y la verificación no se da por buena).
sub_count() { az resource list --resource-type "$1" --query 'length(@)' -o tsv 2>/dev/null || echo '?'; }
orph_d="$(sub_count Microsoft.Compute/disks)"; orph_ip="$(sub_count Microsoft.Network/publicIPAddresses)"; sub_vm="$(sub_count Microsoft.Compute/virtualMachines)"; sub_nic="$(sub_count Microsoft.Network/networkInterfaces)"
say "Discos administrados en la suscripción" "$orph_d"; say "IP públicas en la suscripción" "$orph_ip"; say "Máquinas virtuales en la suscripción" "$sub_vm"; say "Interfaces de red en la suscripción" "$sub_nic"
bud="$(az consumption budget list --query "[?name=='presupuesto-nexoeventos'] | length(@)" -o tsv 2>/dev/null || echo 0)"
diag="$(az monitor diagnostic-settings subscription list --query "value[?name=='actividad-suscripcion'] | length(@)" -o tsv 2>/dev/null || echo 0)"
say "Presupuesto «presupuesto-nexoeventos» (alcance de suscripción)" "$bud"; say "Ajuste de diagnóstico «actividad-suscripcion» (suscripción)" "$diag"
total_sub="$(az resource list --query 'length(@)' -o tsv 2>/dev/null || echo ?)"; say "Recursos totales en la suscripción" "$total_sub"
case "$EXPECT" in
  none)   [[ "$rg_exists" == false && "$orph_d" == 0 && "$orph_ip" == 0 && "$sub_vm" == 0 && "$sub_nic" == 0 && "$bud" == 0 && "$diag" == 0 ]] || fail=1;;
  base)   [[ "$rg_exists" == true && "$bud" == 1 && "$diag" == 1 && "${vms:-1}" == 0 && "${disks:-1}" == 0 && "${pips:-1}" == 0 && "${nics:-1}" == 0 && "$orph_d" == 0 && "$orph_ip" == 0 && "$sub_vm" == 0 && "$sub_nic" == 0 ]] || fail=1;;
  vm-off) [[ "$rg_exists" == true ]] && az vm list -g "$RG" -d --query "[?powerState!='VM deallocated'] | length(@)" -o tsv 2>/dev/null | grep -qx 0 || fail=1;;
  *) echo "Uso: azure-verify-clean.sh --expect none|base|vm-off" >&2; exit 2;;
esac
[[ $fail == 0 ]] && echo "RESULTADO: correcto para --expect $EXPECT" || { echo "RESULTADO: HAY RECURSOS QUE NO COINCIDEN con --expect $EXPECT (revisar facturación)"; exit 1; }
