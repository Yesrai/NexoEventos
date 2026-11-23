#!/usr/bin/env bash
# Terraform simulado para probar `chain`: plan → copia el JSON de $FAKE_PLAN_JSON; show -json → lo muestra; apply → registra el plan EXACTO aplicado.
d="$FAKE_DIR"; echo "tf $*" >>"$d/tfcalls"; args=("$@"); sub=""; plan=""
for a in "${args[@]}"; do case "$a" in plan|show|apply) sub="$a";; -out=*) plan="${a#-out=}";; esac; plan_last="$a"; done
case "$sub" in
  plan) cp "$FAKE_PLAN_JSON" "$plan"; echo "Plan: fake";;
  show) cat "$plan_last";;
  apply) echo "apply $plan_last" >>"$d/applied"; [[ -n "${FAKE_APPLY_FAIL:-}" ]] && exit 1; printf '2\t2\t2\n' >"$d/asg"; echo 1 >"$d/alb"; printf 'i-aaa\ti-bbb\n' >"$d/healthy"; printf 'us-east-1a\tus-east-1b\n' >"$d/zones"; echo 2 >"$d/ec2";;
esac
exit 0
