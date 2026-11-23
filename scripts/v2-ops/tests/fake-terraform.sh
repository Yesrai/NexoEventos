#!/usr/bin/env bash
# terraform SIMULADO para probar v2-terraform.sh: no usa red, ni credenciales, ni estado real.
# plan  -> crea el archivo del plan (con el modo) | show -json -> imprime $MOCK_PLAN_JSON | apply -> registra y cambia el estado del aws simulado
D="${MOCK_DIR:?}"; echo "$*" >> "$D/tf-calls.log"
args=("$@"); sub=""; for a in "${args[@]}"; do case "$a" in -chdir=*) ;; plan|show|apply|destroy|init) sub="$a"; break;; esac; done
last="${args[${#args[@]}-1]}"
case "$sub" in
  plan) for a in "${args[@]}"; do [[ "$a" == -out=* ]] && out="${a#-out=}"; done
        for a in "${args[@]}"; do [[ "$a" == -var-file=*-on.tfvars ]] && echo on > "$out"; [[ "$a" == -var-file=*-off.tfvars ]] && echo off > "$out"; done; echo "Plan simulado";;
  show) cat "$MOCK_PLAN_JSON";;
  apply) m="$(cat "$last")"; [[ "$m" == on ]] && echo on > "$D/state" || echo off > "$D/state"; echo "Apply complete! Resources: 0 added, 1 changed, 0 destroyed.";;
  *) echo "LLAMADA TERRAFORM NO PREVISTA: $*" >&2; echo "UNEXPECTED-TF $*" >> "$D/tf-calls.log"; exit 9;;
esac
