#!/usr/bin/env bash
# Suscribe un correo al tema SNS de alarmas de NexoEventos SIN que la dirección pase por Terraform, por el estado, por un plan guardado, por la línea
# de comandos (visible con `ps`), por el historial de la terminal ni por ningún archivo. La dirección se pide con entrada OCULTA, se confirma tecleándola
# dos veces y viaja a Python por la entrada estándar (printf es interno del shell); la CLI lee un JSON temporal privado. Nunca se imprime.
# Uso (en TU terminal, con las credenciales de Academy cargadas):   scripts/cloud/suscribir-correo-alarmas.sh [--dry-run]
# --dry-run: valida la entrada y la estructura del JSON (también con el analizador de la CLI, sin AWS) y termina. Requiere que el tema ya exista (creado por Terraform con enable_alarms = true).
set -euo pipefail
umask 077
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
TOPIC_NAME="${NEXO_ALARM_TOPIC_NAME:-nexoeventos-academy-alarmas}"
valid() { [[ ${#1} -le 254 && "$1" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ && ! "$1" =~ \.invalid$ ]]; }

if (( ! DRY )); then
  command -v aws >/dev/null || { echo "Falta la CLI de AWS." >&2; exit 2; }
  : "${AWS_PROFILE:?Define AWS_PROFILE (p. ej. nexoeventos-lab)}"
  aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 || { echo "Sesión de AWS no válida: renueva las credenciales del laboratorio." >&2; exit 1; }
  TOPIC="$(aws sns list-topics --query "Topics[?ends_with(TopicArn, ':${TOPIC_NAME}')].TopicArn | [0]" --output text 2>/dev/null || true)"
  [[ -n "$TOPIC" && "$TOPIC" != "None" ]] || { echo "No existe el tema '${TOPIC_NAME}': primero aplica Terraform (enable_alarms = true)." >&2; exit 1; }
  EXISTING="$(aws sns list-subscriptions-by-topic --topic-arn "$TOPIC" --query 'length(Subscriptions)' --output text)"
  [[ "$EXISTING" == "0" ]] || { echo "El tema ya tiene $EXISTING suscripción(es); no se crea otra." >&2; exit 1; }
fi

read -r -s -p "Correo para las alarmas de NexoEventos (no se mostrará): " EMAIL; echo >&2
read -r -s -p "Repite el correo (no se mostrará): " EMAIL2; echo >&2
[[ "$EMAIL" == "$EMAIL2" ]] || { echo "Las dos entradas no coinciden." >&2; unset EMAIL EMAIL2; exit 1; }
unset EMAIL2
valid "$EMAIL" || { echo "Dirección no válida (se rechazan formatos erróneos y el dominio .invalid)." >&2; unset EMAIL; exit 1; }

# Causa del fallo anterior: la CLI v2 lee el archivo de --cli-input-json DOS veces; con una tubería (file:///dev/stdin) la segunda lectura llega vacía
# y da "Invalid JSON received". Ahora el JSON se escribe (con json.dumps, que escapa cualquier carácter especial) en un directorio temporal privado
# (0700, fuera del repositorio), se pasa como file://<ruta> y se borra siempre al salir (trap). El correo viaja a Python por la entrada estándar
# (printf es interno del shell), nunca por argumentos del proceso.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/nexo-sns.XXXXXX")"
cleanup() { rm -rf "$WORK"; unset EMAIL TOPIC; }
trap cleanup EXIT
build_json() {  # $1 = ARN del tema; el correo entra por stdin; escribe $WORK/in.json
  printf '%s' "$EMAIL" | python3 -I -c 'import json,sys; t=sys.argv[1]; e=sys.stdin.read(); open(sys.argv[2],"w").write(json.dumps({"TopicArn":t,"Protocol":"email","Endpoint":e,"ReturnSubscriptionArn":True}))' "$1" "$WORK/in.json"
}
check_json() {  # valida estructura y que el correo vaya intacto; no imprime nada
  printf '%s' "$EMAIL" | python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); e=sys.stdin.read(); assert set(d)=={"TopicArn","Protocol","Endpoint","ReturnSubscriptionArn"} and d["Protocol"]=="email" and d["ReturnSubscriptionArn"] is True and d["Endpoint"]==e and d["TopicArn"].startswith("arn:aws:sns:")' "$WORK/in.json"
}

if (( DRY )); then
  build_json "arn:aws:sns:us-east-1:000000000000:prueba" && check_json || { echo "El JSON que se enviaría no es válido." >&2; exit 1; }
  # Comprobación del analizador real de la CLI SIN AWS: credenciales ficticias, punto final local inalcanzable; solo se mira si rechaza el JSON.
  if command -v aws >/dev/null; then
    OUT="$(env -i PATH="$PATH" HOME=/nonexistent AWS_ACCESS_KEY_ID=x AWS_SECRET_ACCESS_KEY=x AWS_DEFAULT_REGION=us-east-1 AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
      aws sns subscribe --cli-input-json "file://$WORK/in.json" --endpoint-url http://127.0.0.1:9 --no-sign-request --cli-connect-timeout 1 --cli-read-timeout 1 2>&1 || true)"
    if grep -q -E "Invalid JSON|ParamValidation" <<<"$OUT"; then echo "La CLI de AWS rechaza el JSON (no se muestra el contenido)." >&2; exit 1; fi
  fi
  echo "Entrada válida; estructura JSON verificada (modo prueba: no se llamó a AWS, no se creó ninguna suscripción)." >&2; exit 0
fi
build_json "$TOPIC"; check_json || { echo "El JSON generado no es válido." >&2; exit 1; }
aws sns subscribe --cli-input-json "file://$WORK/in.json" --query SubscriptionArn --output text >/dev/null
echo "Suscripción solicitada. Abre tu bandeja (y spam), confirma el mensaje de AWS y avísame; no se muestra la dirección." >&2
