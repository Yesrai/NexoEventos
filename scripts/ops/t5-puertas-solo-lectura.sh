#!/usr/bin/env bash
# T5 — puertas de entrada de SOLO LECTURA (runbook §0). NO crea, modifica ni detiene nada. Solo `aws … describe/get`. Sale 0 si TODAS pasan; escribe work/t5/medidas/puertas.json (0600) y no imprime la cuenta ni ARNs.
# Entrada: tfvars local (expected_account_id, ami_id, certificate_arn). Pruebas: AWS_BIN (sustituye a `aws`), T5_TFVARS, T5_OUT.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; AWS="${AWS_BIN:-aws}"; TFV="${T5_TFVARS:-$ROOT/work/terraform-envs/academy-v2.tfvars}"; OUT="${T5_OUT:-$ROOT/work/t5/medidas}"
export AWS_PAGER="" AWS_DEFAULT_REGION=us-east-1; umask 077; mkdir -p "$OUT"
val() { sed -n "s/^$1[[:space:]]*=[[:space:]]*\"\(.*\)\"/\1/p" "$TFV" | head -1; }
EXP="$(val expected_account_id)"; AMI="$(val ami_id)"; CERT="$(val certificate_arn)"; fail=0; rows=""
chk() { local ok=false; [[ "$2" == "$3" ]] && ok=true || fail=1; printf '%-46s %s\n' "$1" "$($ok && echo OK || echo FALLA)"; rows="$rows{\"puerta\":\"$1\",\"ok\":$ok},"; }
[[ -n "$EXP" && -n "$AMI" && -n "$CERT" ]] || { echo "faltan valores en $TFV" >&2; exit 2; }
ACC="$("$AWS" sts get-caller-identity --query Account --output text 2>/dev/null || echo SIN_CREDENCIALES)"
chk "cuenta = expected_account_id (sesión viva)" "$ACC" "$EXP"
[[ "$ACC" == "$EXP" ]] || { echo "Sin sesión válida de Academy: no se evalúan más puertas."; printf '{"ok":false,"motivo":"sin sesión o cuenta distinta","utc":"%s"}\n' "$(date -u +%FT%TZ)" > "$OUT/puertas.json"; exit 1; }
chk "región = us-east-1" "$("$AWS" configure get region 2>/dev/null || echo "$AWS_DEFAULT_REGION")" "us-east-1"
chk "RDS nexoeventos-academy-postgres existe y es Multi-AZ" "$("$AWS" rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].MultiAZ' --output text 2>/dev/null)" "True"
RS="$("$AWS" rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null)"; echo "   (estado actual de la RDS: $RS; si está 'stopped' hay que iniciarla ≈ 15 min dentro de la ventana)"; rows="$rows{\"puerta\":\"estado RDS: $RS\",\"ok\":true},"
chk "ASG nexoeventos-academy-v2-asg a 0/0 (apagado)" "$("$AWS" autoscaling describe-auto-scaling-groups --auto-scaling-group-names nexoeventos-academy-v2-asg --query 'AutoScalingGroups[0].[MinSize,DesiredCapacity]' --output text 2>/dev/null | tr '\t' ' ')" "0 0"
chk "sin EC2 de V2 en ejecución" "$("$AWS" ec2 describe-instances --filters Name=tag:Name,Values=nexoeventos-academy-v2-app Name=instance-state-name,Values=pending,running --query 'length(Reservations)' --output text 2>/dev/null)" "0"
chk "AMI disponible" "$("$AWS" ec2 describe-images --image-ids "$AMI" --query 'Images[0].State' --output text 2>/dev/null)" "available"
chk "certificado ACM emitido/importado" "$("$AWS" acm describe-certificate --certificate-arn "$CERT" --query Certificate.Status --output text 2>/dev/null)" "ISSUED"
chk "secreto de la aplicación presente" "$("$AWS" secretsmanager describe-secret --secret-id nexoeventos/academy/backend-env --query Name --output text 2>/dev/null)" "nexoeventos/academy/backend-env"
printf '{"ok":%s,"puertas":[%s],"utc":"%s"}\n' "$([[ $fail == 0 ]] && echo true || echo false)" "${rows%,}" "$(date -u +%FT%TZ)" > "$OUT/puertas.json"
[[ $fail == 0 ]] && echo "TODAS las puertas de solo lectura pasan" || echo "HAY puertas que fallan: NO se enciende AWS"; exit $fail
