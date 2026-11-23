#!/usr/bin/env bash
# v2-status — SOLO LECTURA. Muestra el estado de V2 (ASG, instancias, ALB, destinos), de la RDS y de la EC2 de V1.
# Uso: ./v2-status.sh        Código de salida: 0 si pudo consultar; distinto de 0 si hubo error.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
need_tools; check_identity; find_asg; load_asg; load_alb
print_status; verdict
