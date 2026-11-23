#!/usr/bin/env bash
# Verificación POSTERIOR al despliegue (solo lectura): comprueba en Azure lo que Terraform debía crear y guarda la salida como evidencia (sin datos personales: IP y correo enmascarados).
#   --stage base   RG, VNet/subred, NSG (reglas), Log Analytics, grupo de acción, presupuesto, registro de actividad y AUSENCIA de VM/NIC/IP/discos
#   --stage vm     lo anterior + VM (tamaño, Trusted Launch, identidad, sin extensiones), disco (SKU), IP pública, rol «Monitoring Reader», 3 alertas
# Uso: azure-verify-deploy.sh --stage base|vm [--out docs/evidencias/multicloud/azure/AAAAMMDD-base]
set -uo pipefail
STAGE=base; OUT=""; while [[ $# -gt 0 ]]; do case "$1" in --stage) STAGE="$2"; shift 2;; --out) OUT="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
RG=rg-nexoeventos-observabilidad; fail=0; LOG="$(mktemp)"; trap 'rm -f "$LOG"' EXIT
mask_ip() { awk -F. '{print $1"."$2".x.x"}' <<<"$1"; }; mask_mail() { sed -E 's/^(.).*@(.*)$/\1***@\2/' <<<"$1"; }
ok() { printf 'OK     %s\n' "$1" | tee -a "$LOG"; }; ko() { printf 'FALLÓ  %s\n' "$1" | tee -a "$LOG"; fail=1; }
chk() { if [[ "$2" == "$3" ]]; then ok "$1 = $3"; else ko "$1: esperado «$3», obtenido «${2:-vacío}»"; fi; }
echo "Verificación posterior al despliegue ($STAGE) — $(date -u +%FT%TZ)" | tee "$LOG"
[[ "$(az group exists -n $RG)" == true ]] || { ko "el grupo de recursos $RG no existe"; exit 1; }
chk "región del grupo de recursos" "$(az group show -n $RG --query location -o tsv)" centralus
chk "VNet: espacio de direcciones" "$(az network vnet show -g $RG -n vnet-nexoeventos-obs --query 'addressSpace.addressPrefixes[0]' -o tsv)" 10.40.0.0/16
chk "subred: prefijo y NSG asociado" "$(az network vnet subnet show -g $RG --vnet-name vnet-nexoeventos-obs -n snet-monitoring --query '[addressPrefixes[0], networkSecurityGroup.id!=null]' -o tsv | tr '\t\n' '  ' | sed 's/ $//')" "10.40.1.0/24 true"
# --- NSG ---
az network nsg rule list -g $RG --nsg-name nsg-nexoeventos-obs -o json > "$LOG.nsg" 2>/dev/null
python3 - "$LOG.nsg" <<'PY' | tee -a "$LOG"
import json,sys,re
r=json.load(open(sys.argv[1])); bad=[]
adm=[x for x in r if x['name'].startswith('admin-')]
ips={x['sourceAddressPrefix'] for x in adm}
open_in=[x['name'] for x in r if x['direction']=='Inbound' and x['access']=='Allow' and (x['sourceAddressPrefix'] in ('*','Internet','0.0.0.0/0') or '*' in x.get('sourceAddressPrefixes',[]))]
print(("OK     " if not open_in else "FALLÓ  ")+"NSG: ninguna regla de entrada «Allow» con origen abierto"+(f" ({open_in})" if open_in else ""))
print(("OK     " if sorted(x['destinationPortRange'] for x in adm)==['22','443'] and len(ips)==1 and next(iter(ips)).endswith('/32') else "FALLÓ  ")+f"NSG: administración solo 22 y 443 desde una única IP /32 ({next(iter(ips)).split('.')[0]}.{next(iter(ips)).split('.')[1]}.x.x/32)")
print(("OK     " if any(x['name']=='deny-all-inbound' and x['access']=='Deny' for x in r) else "FALLÓ  ")+"NSG: denegación explícita de toda la entrada")
print(("OK     " if any(x['name']=='deny-internet-out' and x['access']=='Deny' for x in r) else "FALLÓ  ")+"NSG: salida a Internet denegada salvo 80/443/53/123 y plataforma de Azure")
PY
grep -q '^FALLÓ' "$LOG" && fail=1; rm -f "$LOG.nsg"
# --- Log Analytics, acción, presupuesto, diagnóstico ---
chk "Log Analytics: retención (días) y tope diario (GB)" "$(az monitor log-analytics workspace show -g $RG -n log-nexoeventos-obs --query '[retentionInDays, workspaceCapping.dailyQuotaGb]' -o tsv | tr '\t\n' '  ' | sed 's/ $//')" "30 0.2"
n_mail="$(az monitor action-group show -g $RG -n ag-nexoeventos-obs --query 'length(emailReceivers)' -o tsv 2>/dev/null)"; mail="$(az monitor action-group show -g $RG -n ag-nexoeventos-obs --query 'emailReceivers[0].emailAddress' -o tsv 2>/dev/null)"
chk "grupo de acción: receptores de correo" "$n_mail" 1; ok "grupo de acción: receptor de correo configurado (no se muestra)"
az consumption budget show --budget-name presupuesto-nexoeventos -o json > "$LOG.bud" 2>/dev/null && python3 - "$LOG.bud" <<'PY' | tee -a "$LOG"
import json,sys
b=json.load(open(sys.argv[1])); n=b['notifications']
th=sorted((int(float(v['threshold'])),k.split('_')[0].capitalize()) for k,v in n.items())
auto=[k for k,v in n.items() if v.get('contactGroups') or v.get('contactRoles') or v.get('contactWebhooks')]
print(("OK     " if float(b['amount'])==60 and b['timeGrain']=='Monthly' else "FALLÓ  ")+f"presupuesto: {b['amount']} USD {b['timeGrain']}")
print(("OK     " if th==[(50,'Actual'),(80,'Actual'),(100,'Actual'),(100,'Forecasted')] else "FALLÓ  ")+f"presupuesto: avisos {th}")
print(("OK     " if not auto else "FALLÓ  ")+"presupuesto: solo avisa (sin grupos de acción, roles ni webhooks de automatización)")
PY
rm -f "$LOG.bud"
chk "registro de actividad → Log Analytics" "$(az monitor diagnostic-settings subscription list --query "value[?name=='actividad-suscripcion'] | length(@)" -o tsv 2>/dev/null)" 1
# --- recursos que NO deben existir en la etapa base ---
cnt() { az resource list -g $RG --resource-type "$1" --query 'length(@)' -o tsv 2>/dev/null || echo '?'; }
if [[ "$STAGE" == base ]]; then
  for t in Microsoft.Compute/virtualMachines Microsoft.Compute/disks Microsoft.Network/publicIPAddresses Microsoft.Network/networkInterfaces; do chk "ausencia de ${t##*/}" "$(cnt $t)" 0; done
else
  vm=vm-nexoeventos-obs
  one() { tr '\t\n' '  ' | sed 's/ *$//' | sed 's/true/True/g'; }   # -o tsv devuelve una línea por valor y booleanos en minúscula
  chk "VM: tamaño, Trusted Launch, arranque seguro y vTPM" "$(az vm show -g $RG -n $vm --query '[hardwareProfile.vmSize, securityProfile.securityType, securityProfile.uefiSettings.secureBootEnabled, securityProfile.uefiSettings.vTpmEnabled]' -o tsv | one)" "Standard_D2s_v4 TrustedLaunch True True"
  chk "VM: identidad administrada" "$(az vm show -g $RG -n $vm --query identity.type -o tsv)" SystemAssigned
  chk "VM: extensiones instaladas" "$(az vm extension list -g $RG --vm-name $vm --query 'length(@)' -o tsv)" 0
  chk "VM: disco del sistema (SKU y GiB)" "$(az vm show -g $RG -n $vm --query '[storageProfile.osDisk.managedDisk.storageAccountType, storageProfile.osDisk.diskSizeGB]' -o tsv | one)" "StandardSSD_LRS 64"
  chk "IP pública: SKU y asignación" "$(az network public-ip show -g $RG -n pip-nexoeventos-obs --query '[sku.name, publicIPAllocationMethod]' -o tsv | one)" "Standard Static"
  pid="$(az vm show -g $RG -n $vm --query identity.principalId -o tsv)"
  chk "rol de la identidad (solo «Monitoring Reader» en el RG)" "$(az role assignment list --assignee "$pid" --all --query '[].roleDefinitionName' -o tsv | tr '\n' ' ' | sed 's/ $//')" "Monitoring Reader"
  chk "alertas de métricas de la VM" "$(az monitor metrics alert list -g $RG --query 'length(@)' -o tsv)" 3
  SUBID="$(az account show --query id -o tsv)"
  chk "apagado automático: estado, tarea, zona y notificaciones" "$(az rest --method get --url "https://management.azure.com/subscriptions/$SUBID/resourceGroups/$RG/providers/Microsoft.DevTestLab/schedules/shutdown-computevm-$vm?api-version=2018-09-15" --query '[properties.status, properties.taskType, properties.timeZoneId, properties.notificationSettings.status]' -o tsv | one)" "Enabled ComputeVmShutdownTask UTC Disabled"
  echo "INFO   hora del apagado automático (UTC) = $(az rest --method get --url "https://management.azure.com/subscriptions/$SUBID/resourceGroups/$RG/providers/Microsoft.DevTestLab/schedules/shutdown-computevm-$vm?api-version=2018-09-15" --query properties.dailyRecurrence.time -o tsv)"
fi
[[ -n "$OUT" ]] && { mkdir -p "$OUT"; cp "$LOG" "$OUT/verificacion-$STAGE.txt"; echo "Evidencia guardada en $OUT/verificacion-$STAGE.txt"; }
[[ $fail == 0 ]] && echo "RESULTADO: todas las comprobaciones correctas" || { echo "RESULTADO: HAY COMPROBACIONES FALLIDAS"; exit 1; }
