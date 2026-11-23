#!/usr/bin/env bash
# Filtro de saneamiento (stdin → stdout) compatible con sed de macOS (BSD) y de Linux: no usa `\b`, que BSD sed no admite y por eso dejó pasar IP públicas.
# Enmascara: IDs de cuenta de 12 dígitos, ARN, IDs de recursos, IPv4, correos y el usuario de sesión de Academy. Uso: comando | scripts/cloud/mask.sh
sed -E \
  -e 's/arn:aws[A-Za-z-]*:[^"[:space:],]*/<arn>/g' \
  -e 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<id>\2/g' -e 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<id>\2/g' \
  -e 's/i-[0-9a-f]{8,17}/<i-id>/g' \
  -e 's/(vpc|subnet|sg|ami|snap|vol|eni|rtb|igw|lt|nat)-[0-9a-f]{8,17}/<\1>/g' \
  -e 's/(^|[^0-9.])[0-9]{1,3}(\.[0-9]{1,3}){3}([^0-9.]|$)/\1<ip>\3/g' -e 's/(^|[^0-9.])[0-9]{1,3}(\.[0-9]{1,3}){3}([^0-9.]|$)/\1<ip>\3/g' \
  -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<correo>/g' \
  -e 's/user[0-9]+=[A-Za-z_]+/<usuario>/g'
