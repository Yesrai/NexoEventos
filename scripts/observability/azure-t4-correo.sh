#!/usr/bin/env bash
# T4 — lado AZURE del canal de correo (reutiliza el grupo de acción `ag-nexoeventos-obs` existente; sin SMTP ni secretos). Cambios REMOTOS, solo con --aplicar y su frase:
#   --rol     asigna «Monitoring Metrics Publisher» a la identidad administrada de la VM, acotado a ESA VM         (frase: "CONFIGURAR CORREO T4")
#   --regla   crea la regla de métricas `alerta-nexo-sonda` (NexoEventos.sondas_fallidas > 0, 5 min/1 min, sev. 2) → grupo de acción. Requiere que la métrica ya exista (primera muestra publicada)
#   --retirar borra la regla y el rol creados aquí (reversión)                                                  (frase: "RETIRAR CORREO T4")
#   --check   solo lectura: identidad, rol, regla y receptores del grupo de acción (correos enmascarados)
# Pruebas: AZ_BIN (sustituye a `az`). Etiqueta de limpieza: t4=temporal.
set -euo pipefail
AZ="${AZ_BIN:-az}"; RG="rg-nexoeventos-observabilidad"; VM="vm-nexoeventos-obs"; AG="ag-nexoeventos-obs"; RULE="alerta-nexo-sonda"; ROLE="Monitoring Metrics Publisher"
MODE=""; FRASE=""
while [[ $# -gt 0 ]]; do case "$1" in --rol) MODE=rol; shift;; --regla) MODE=regla; shift;; --retirar) MODE=retirar; shift;; --check) MODE=check; shift;; --aplicar) FRASE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -n "$MODE" ]] || { echo "Uso: --check | --rol | --regla | --retirar [--aplicar frase]" >&2; exit 2; }
SCOPE="$("$AZ" vm show -g "$RG" -n "$VM" --query id -o tsv)"; PID="$("$AZ" vm show -g "$RG" -n "$VM" --query identity.principalId -o tsv)"
[[ -n "$SCOPE" && -n "$PID" && "$PID" != "None" ]] || { echo "La VM no tiene identidad administrada" >&2; exit 3; }
need() { [[ "$FRASE" == "$1" ]] || { echo "Modo plan: no se cambió nada (frase requerida: $1)."; exit 0; }; }
case "$MODE" in
check)
  echo "identidad=$PID (administrada) alcance=VM"
  echo "rol_asignado=$("$AZ" role assignment list --assignee "$PID" --scope "$SCOPE" --query "[?roleDefinitionName=='$ROLE'] | length(@)" -o tsv)"
  echo "regla_existe=$("$AZ" monitor metrics alert list -g "$RG" --query "[?name=='$RULE'] | length(@)" -o tsv)"
  "$AZ" monitor action-group show -g "$RG" -n "$AG" --query "emailReceivers[].{n:name,estado:status}" -o tsv;;
rol)
  echo "Plan: asignar "${ROLE}" a la identidad de la VM, alcance = la VM (no el grupo ni la suscripcion)"; need "CONFIGURAR CORREO T4"
  "$AZ" role assignment create --assignee-object-id "$PID" --assignee-principal-type ServicePrincipal --role "$ROLE" --scope "$SCOPE" >/dev/null && echo "OK    rol asignado (la propagación puede tardar unos minutos)";;
regla)
  echo "Plan: crear la regla $RULE (total NexoEventos.sondas_fallidas > 0; ventana 5 min; evaluación 1 min; severidad 2) → $AG"; need "CONFIGURAR CORREO T4"
  "$AZ" monitor metrics alert create -n "$RULE" -g "$RG" --scopes "$SCOPE" --condition "total NexoEventos.sondas_fallidas > 0" --window-size 5m --evaluation-frequency 1m --severity 2 \
     --action "$AG" --description "T4: una sonda de NexoEventos falla (métrica publicada por Zabbix)" --tags t4=temporal >/dev/null && echo "OK    regla creada";;
retirar)
  echo "Plan: borrar la regla $RULE y el rol "${ROLE}" (alcance VM)"; need "RETIRAR CORREO T4"
  "$AZ" monitor metrics alert delete -n "$RULE" -g "$RG" >/dev/null 2>&1 || echo "(la regla no existía)"
  "$AZ" role assignment delete --assignee "$PID" --role "$ROLE" --scope "$SCOPE" >/dev/null 2>&1 || echo "(el rol no existía)"; echo "OK    retirado";;
esac
