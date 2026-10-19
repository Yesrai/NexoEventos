#!/usr/bin/env bash
# Crea el secreto compartido de V2 COPIANDO el backend.env de la EC2 de V1 con el rol de la propia instancia: el valor no sale de AWS ni se imprime.
# Se ejecutaría por Session Manager SOLO con autorización explícita. No sobrescribe un secreto existente. Imprime únicamente el ARN.
set -euo pipefail
SECRET_NAME="${1:-nexoeventos/academy/backend-env}"
REGION="${AWS_REGION:-us-east-1}"
SOURCE=/etc/nexoeventos/backend.env
[[ -r "$SOURCE" ]] || { echo "No se puede leer $SOURCE (¿ejecuta como root en la EC2 de V1?)." >&2; exit 1; }
for key in DATABASE_URL TICKET_ENCRYPTION_KEY SECURITY_HASH_KEY FRONTEND_ORIGINS; do
  grep -q "^$key=." "$SOURCE" || { echo "Falta $key en $SOURCE." >&2; exit 1; }
done
if aws secretsmanager describe-secret --region "$REGION" --secret-id "$SECRET_NAME" >/dev/null 2>&1; then
  echo "El secreto $SECRET_NAME ya existe; no se sobrescribe." >&2; exit 2
fi
aws secretsmanager create-secret --region "$REGION" --name "$SECRET_NAME" --description "backend.env compartido por las instancias de NexoEventos V2" \
  --secret-string "file://$SOURCE" --query ARN --output text
