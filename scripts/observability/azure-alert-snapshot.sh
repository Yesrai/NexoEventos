#!/usr/bin/env bash
# Instantánea SOLO LECTURA del estado de Azure para las observaciones 3, 5 y 6: VM, reglas de alerta, grupo de acciones (sin direcciones), alertas disparadas
# (Alerts Management) y coincidencia de la IP del operador con el NSG (sin mostrar IPs). No cambia nada. Salida saneada por stdout.
# Uso: scripts/observability/azure-alert-snapshot.sh [--rg rg-nexoeventos-observabilidad] [--vm vm-nexoeventos-obs]
set -euo pipefail
RG=rg-nexoeventos-observabilidad; VM=vm-nexoeventos-obs
while [[ $# -gt 0 ]]; do case "$1" in --rg) RG="$2"; shift 2;; --vm) VM="$2"; shift 2;; *) echo "Uso: $0 [--rg RG] [--vm VM]" >&2; exit 2;; esac; done
command -v az >/dev/null || { echo "Falta la CLI de Azure." >&2; exit 2; }
SUB="$(az account show --query id -o tsv)"
echo "# Instantánea Azure $(date -u +%Y-%m-%dT%H:%M:%SZ) (suscripción y direcciones ocultas)"
echo "## VM"; az vm get-instance-view -g "$RG" -n "$VM" --query '{estado:instanceView.statuses[?starts_with(code,`PowerState`)].displayStatus|[0],tamano:hardwareProfile.vmSize}' -o json | tr -d '\n '; echo
echo "## Reglas de alerta (nombre | habilitada | severidad | evaluación | ventana | métrica operador umbral)"
az monitor metrics alert list -g "$RG" -o json | python3 -c "
import json,sys
for a in json.load(sys.stdin):
    c=a['criteria']['allOf'][0]
    print(a['name'],'| habilitada',a['enabled'],'| sev',a['severity'],'| cada',a['evaluationFrequency'],'ventana',a['windowSize'],'|',c['metricName'],c['operator'],c['threshold'])"
echo "## Grupo de acciones (receptores de correo: estado; sin direcciones)"
az monitor action-group list -g "$RG" --query '[].[name,enabled,emailReceivers[].status|join(`,`,@)]' -o tsv | tr '\t' ' '
echo "## Alertas de los últimos 30 días (regla | severidad | condición | disparada | resuelta)"
az rest --method get --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.AlertsManagement/alerts?api-version=2019-05-05-preview&timeRange=30d" \
  --query 'value[].properties.essentials.[alertRule,severity,monitorCondition,startDateTime,monitorConditionResolvedDateTime]' -o tsv | sed -E 's#^.*/metricAlerts/##' | tr '\t' ' '
echo "## NSG: ¿la IP pública actual del operador coincide con la regla admin-https? (sin mostrar IPs)"
MY="$(curl -s --max-time 8 https://api.ipify.org || true)"; SRC="$(az network nsg rule show -g "$RG" --nsg-name nsg-nexoeventos-obs -n admin-https --query sourceAddressPrefix -o tsv)"
[[ -n "$MY" && "$MY/32" == "$SRC" ]] && echo "coincide: SÍ" || echo "coincide: NO (hay que actualizar la regla antes de usar Grafana por 443)"
