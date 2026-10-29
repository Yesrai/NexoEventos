#!/usr/bin/env bash
# Control GO/NO-GO previo al apply de la VM de Azure. SOLO LECTURA: no crea, modifica ni destruye nada; no imprime IP, correo ni identificadores.
# Uso: scripts/observability/azure-window-preflight.sh [--plan work/terraform-plans/azure-vm-incremental.tfplan] [--max-plan-age-h 6]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PLAN="work/terraform-plans/azure-vm-incremental.tfplan"; MAXH=1; WINH=4; TFV="work/terraform-envs/azure-vm.tfvars"; KEY="$HOME/.ssh/nexoeventos_azure"; RG="rg-nexoeventos-observabilidad"
while [[ $# -gt 0 ]]; do case "$1" in --plan) PLAN="$2"; shift 2;; --max-plan-age-h) MAXH="$2"; shift 2;; --window-hours) WINH="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
GIT="$(for c in /usr/bin/git "$(command -v git || true)"; do [[ -x "$c" ]] && "$c" --version >/dev/null 2>&1 && { echo "$c"; break; }; done)"
fail=0; ok() { printf 'OK     %s\n' "$1"; }; ko() { printf 'FALLA  %s\n' "$1"; fail=1; }; warn() { printf 'AVISO  %s\n' "$1"; }
chk() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else ko "$1"; fi; }

for t in terraform az ansible-playbook ssh ssh-keygen ssh-keyscan; do chk "herramienta: $t" "command -v $t"; done
st="$(az account show --query state -o tsv 2>/dev/null)"; [[ "$st" == Enabled ]] && ok "suscripción de Azure habilitada ($(az account show --query name -o tsv))" || ko "sin sesión o suscripción no habilitada"
for p in Microsoft.Compute Microsoft.Network Microsoft.OperationalInsights Microsoft.Insights Microsoft.AlertsManagement Microsoft.DevTestLab; do
  s="$(az provider show -n $p --query registrationState -o tsv 2>/dev/null)"; [[ "$s" == Registered ]] && ok "proveedor $p registrado" || ko "proveedor $p: ${s:-?}"; done
n="$(az vm list -g $RG --query 'length(@)' -o tsv 2>/dev/null)"; [[ "$n" == 0 ]] && ok "aún no hay VM en el grupo de recursos (estado base)" || ko "VM existentes en el RG: ${n:-?}"
u="$(az vm list-usage -l centralus -o json 2>/dev/null | python3 -c "
import json,sys
d={x['name']['value']:(int(x['currentValue']),int(x['limit'])) for x in json.load(sys.stdin)}
f=d.get('standardDSv4Family',(0,0)); r=d.get('cores',(0,0)); print('%s/%s %s/%s'%(f+r))" 2>/dev/null)"
if [[ -n "$u" ]]; then set -- $u; fu=${1%/*}; fl=${1#*/}; ru=${2%/*}; rl=${2#*/}; (( fl-fu >= 2 && rl-ru >= 2 )) && ok "cuota vCPU: familia DSv4 $1, región $2 (necesita 2 libres)" || ko "cuota insuficiente: DSv4 $1, región $2"; else ko "no se pudo leer la cuota"; fi

if [[ -f "$PLAN" ]]; then
  age=$(( ( $(date +%s) - $(stat -f %m "$PLAN") ) / 60 )); (( age < MAXH*60 )) && ok "plan guardado de hace ${age} min" || ko "plan de hace ${age} min: regenere con azure-set-shutdown-window.sh justo antes del apply"
  python3 - "$PLAN" "$WINH" <<'P' && ok "plan: 7 originales + 1 apagado automático (8 a crear), 0 cambios, 0 destrucciones; base intacta; apagado en UTC dentro de la ventana; sin claves privadas" || ko "el plan NO cumple el contrato (7 + apagado automático)"
import json,subprocess,sys,collections,re,datetime
d=json.loads(subprocess.check_output(["terraform","-chdir=infra/azure","show","-json","../../"+sys.argv[1]]))
c=collections.Counter(tuple(r["change"]["actions"]) for r in d["resource_changes"])
esperado={"azurerm_dev_test_global_vm_shutdown_schedule","azurerm_public_ip","azurerm_network_interface","azurerm_linux_virtual_machine","azurerm_role_assignment","azurerm_monitor_metric_alert"}
crea=[r for r in d["resource_changes"] if r["change"]["actions"]==["create"]]
vm=[r for r in crea if r["type"]=="azurerm_linux_virtual_machine"][0]["change"]["after"]
assert c[("create",)]==8 and sum(v for k,v in c.items() if k not in (("create",),("no-op",)))==0 and c[("no-op",)]==9, dict(c)
assert {r["type"] for r in crea}==esperado and len(crea)==len([r for r in crea]) and sum(1 for r in crea if r["type"]=="azurerm_dev_test_global_vm_shutdown_schedule")==1
assert vm["size"]=="Standard_D2s_v4" and vm["allow_extension_operations"] is False and vm["disable_password_authentication"] is True and vm["boot_diagnostics"]
assert not re.search("PRIVATE KEY",json.dumps(d))
sc=[r for r in crea if r["type"]=="azurerm_dev_test_global_vm_shutdown_schedule"][0]["change"]["after"]
assert sc["enabled"] is True and sc["timezone"]=="UTC" and sc["notification_settings"][0]["enabled"] is False
hh=int(sc["daily_recurrence_time"][:2])*60+int(sc["daily_recurrence_time"][2:]); n=datetime.datetime.utcnow(); delta=(hh-(n.hour*60+n.minute))%1440; W=int(sys.argv[2])*60
assert W-40<=delta<=W+5, "hora de apagado fuera de la ventana: faltan %d min"%delta
P
  [[ -n "$GIT" ]] && "$GIT" check-ignore -q "$PLAN" && ok "el plan está ignorado por Git" || ko "el plan NO está ignorado por Git"
else ko "no existe $PLAN"; fi

[[ "$(stat -f %Lp "$TFV" 2>/dev/null)" == 600 ]] && ok "tfvars con permisos 0600" || ko "tfvars sin permisos 0600"
[[ -n "$GIT" ]] && "$GIT" check-ignore -q "$TFV" && ok "tfvars ignorado por Git" || ko "tfvars no ignorado por Git"
cidr="$(grep -oE '^admin_cidr *= *"[^"]+"' "$TFV" | cut -d'"' -f2)"; cur="$(curl -fsS --max-time 10 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]')"
[[ -n "$cur" && "$cidr" == "$cur/32" ]] && ok "la IP actual del operador coincide con admin_cidr del NSG (no mostrada)" || ko "la IP actual NO coincide con admin_cidr (o no se pudo consultar): regenerar tfvars/plan"
[[ -f "$KEY" && -f "$KEY.pub" ]] && ok "par de claves SSH presente" || ko "falta el par de claves SSH"
[[ "$(stat -f %Lp "$KEY" 2>/dev/null)" == 600 ]] && ok "clave privada con permisos 0600" || ko "clave privada sin permisos 0600"
if ssh-keygen -y -P "" -f "$KEY" >/dev/null 2>&1; then ko "la clave privada NO tiene frase de paso"; else ok "la clave privada está protegida con frase de paso"; fi
ssh-add -l >/dev/null 2>&1 && ok "ssh-agent tiene una identidad cargada" || warn "ssh-agent sin identidades: cárguela justo antes de Ansible (ssh-add -t 14400 ~/.ssh/nexoeventos_azure)"
(cd ansible && ansible-playbook -i localhost, playbooks/monitoring-azure.yml --syntax-check >/dev/null 2>&1) && ok "Ansible: sintaxis del playbook correcta" || ko "Ansible: error de sintaxis"
bash scripts/observability/azure-vm-watchdog.sh --check >/dev/null 2>&1; [[ -f work/operacion/azure-watchdog.log ]] && tail -1 work/operacion/azure-watchdog.log | grep -q "aún no existe" && ok "apagado automático: sesión OK (la VM aún no existe, esperado)" || warn "apagado automático: revise la comprobación --check"
rm -f work/operacion/azure-watchdog.log
echo; (( fail == 0 )) && echo "RESULTADO: GO técnico (esto NO sustituye la autorización explícita del operador para el apply)." || echo "RESULTADO: NO-GO — corrija las FALLAS."
exit $fail
