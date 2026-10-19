#!/usr/bin/env bash
# Importa en ACM el certificado Let's Encrypt de V1 para el listener HTTPS del ALB. Se ejecuta EN la EC2 de V1 (root) con su rol: la clave privada
# no sale de AWS ni se imprime; solo se muestra el ARN. ACM no puede validar un subdominio DuckDNS (exige CNAME), por eso se importa.
# El certificado importado NO se renueva solo: repetir con --reimport (misma ARN) tras cada renovación de Let's Encrypt (vence el 1-ene-2027).
set -euo pipefail
DOMAIN="${1:-nexoeventos-demo.duckdns.org}"
REGION="${AWS_REGION:-us-east-1}"
LIVE="/etc/letsencrypt/live/$DOMAIN"
for file in cert.pem privkey.pem chain.pem; do [[ -r "$LIVE/$file" ]] || { echo "Falta $LIVE/$file." >&2; exit 1; }; done
EXISTING="${2:-}"
args=(--region "$REGION" --certificate "fileb://$LIVE/cert.pem" --private-key "fileb://$LIVE/privkey.pem" --certificate-chain "fileb://$LIVE/chain.pem")
[[ -n "$EXISTING" ]] && args+=(--certificate-arn "$EXISTING") || args+=(--tags "Key=Name,Value=nexoeventos-v2-$DOMAIN")
aws acm import-certificate "${args[@]}" --query CertificateArn --output text
