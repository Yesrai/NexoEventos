#!/usr/bin/env bash
# Firma un manifiesto con la clave de FIRMA que vive en la EC2 (la misma que firma los ciclos C-04 y cuya clave pública está fijada en deploy/backup/signers/), SIN que ningún secreto ni el
# manifiesto salgan de la Mac: a la EC2 solo viaja el SHA-256 del manifiesto (32 bytes) por SSM y vuelve la firma. La firma se comprueba aquí con la clave pública fijada; si no verifica, no se deja.
# Uso: sign-manifest-remote.sh --manifest M.json --signer-pub PUB [--key-path /etc/nexoeventos/c04/backup-sign.pem]   (requiere la EC2 encendida y SSM Online; AWS_PROFILE/REGION del entorno)
# Pruebas locales: NEXO_LOCAL_SIGN_KEY=<clave ficticia> firma localmente con el mismo procedimiento (sin AWS).
set -euo pipefail
KP=/etc/nexoeventos/c04/backup-sign.pem; M=""; PUB=""
while [[ $# -gt 0 ]]; do case "$1" in --manifest) M="$2"; shift 2;; --signer-pub) PUB="$2"; shift 2;; --key-path) KP="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -f "$M" && -r "$PUB" ]] || { echo "Faltan --manifest o --signer-pub." >&2; exit 2; }
HEX="$(openssl dgst -sha256 -binary "$M" | od -An -vtx1 | tr -d ' \n')"; [[ "$HEX" =~ ^[0-9a-f]{64}$ ]] || { echo "Digest inválido." >&2; exit 2; }
REMOTE='python3 -c "import sys,binascii;sys.stdout.buffer.write(binascii.unhexlify(sys.argv[1]))" '"$HEX"' | openssl pkeyutl -sign -inkey '"$KP"' -pkeyopt digest:sha256 | base64 | tr -d "\n"'
if [[ -n "${NEXO_LOCAL_SIGN_KEY:-}" ]]; then
  B64="$(bash -c "${REMOTE//$KP/$NEXO_LOCAL_SIGN_KEY}")"
else
  export AWS_PAGER=""
  IID="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=nexoeventos-academy-app" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].InstanceId' --output text)"
  [[ "$IID" == i-* ]] || { echo "La EC2 de V1 no está en ejecución." >&2; exit 3; }
  PARAMS="$(python3 -c 'import json,sys;print(json.dumps({"commands":[sys.argv[1]]}))' "$REMOTE")"
  CID="$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript --comment "C-04 firma de manifiesto (solo digest)" --timeout-seconds 60 --parameters "$PARAMS" --query Command.CommandId --output text)"
  ST=""; for _ in $(seq 1 40); do sleep 2; ST="$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --query Status --output text 2>/dev/null || true)"; case "$ST" in Success|Failed|Cancelled|TimedOut) break;; esac; done
  [[ "$ST" == Success ]] || { echo "La firma remota falló (estado $ST)." >&2; exit 4; }
  B64="$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --query StandardOutputContent --output text | tr -d ' \n')"
fi
umask 077; TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
printf '%s' "$B64" | base64 -d > "$TMP" 2>/dev/null || { echo "Respuesta de firma ilegible." >&2; exit 4; }
if openssl dgst -sha256 -verify "$PUB" -signature "$TMP" "$M" >/dev/null 2>&1; then cp "$TMP" "$M.sig"; chmod 600 "$M.sig"; echo "OK    manifiesto firmado y verificado con la clave pública fijada ($(wc -c <"$M.sig" | tr -d ' ') bytes)"
else echo "FALLÓ: la firma recibida NO verifica con la clave pública fijada; no se escribió ninguna firma." >&2; exit 5; fi
