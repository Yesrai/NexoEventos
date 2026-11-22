#!/usr/bin/env bash
# Biblioteca (se "importa" con `source`) compartida por run-from-mac.sh y app-recovery.sh: identidad del certificado/clave en modo C-04, verificación de paquetes firmados y
# tiempos REALES por etapa (→ etapas.json y, con OPS_FAILOVER_DIR, recovery-run.json del panel Operación). No imprime claves ni frases. Compatible con bash 3.2 (macOS).
# Requiere antes: HERE (scripts/multicloud), OUT (carpeta de la ejecución), BUNDLE; fail() definida por el script que la importa.

NOWF() { python3 -c 'import time;print(f"{time.time():.3f}")'; }
fp_of_cert() { openssl x509 -in "$1" -outform DER 2>/dev/null | openssl sha256 | awk '{print $NF}'; }
norm_fp() { printf %s "${1:-}" | tr -d : | tr A-F a-f; }

# Comprobaciones LOCALES (antes de usar red o pedir frases): el certificado tiene la huella fijada y, si la clave no tiene frase, es la suya.
c04_preflight() {   # $1 clave $2 certificado $3 huella esperada $4 clave pública de firma
  [[ -r "$2" && -r "$4" ]] || fail "no se puede leer el certificado o la clave pública de firma"
  [[ "$(fp_of_cert "$2")" == "$3" ]] || fail "el certificado NO tiene la huella SHA-256 esperada (identidad distinta de la fijada)" 10
  if ! grep -q -E 'ENCRYPTED' "$1"; then
    [[ "$(openssl pkey -in "$1" -pubout 2>/dev/null | openssl sha256 | awk '{print $NF}')" == "$(openssl x509 -in "$2" -noout -pubkey | openssl sha256 | awk '{print $NF}')" ]] || fail "la clave privada NO corresponde al certificado indicado" 10
  fi
}

# Verifica un paquete C-04 YA DESCARGADO (antes de descifrar): firma del manifiesto, SHA-256/tamaño del cifrado, destinatario del CMS y huella declarada.
c04_verify_bundle() {   # $1 manifiesto $2 cms $3 firma $4 clave pública de firma $5 certificado $6 huella esperada $7 nombre esperado ("" = no comprobar)
  openssl dgst -sha256 -verify "$4" -signature "$3" "$1" >/dev/null 2>&1 || fail "la firma del manifiesto NO es válida: no se restaura" 9
  python3 - "$1" "$2" "$7" <<'PY' || fail "el cifrado no coincide con su manifiesto (SHA-256/tamaño/nombre): no se restaura" 3
import hashlib, json, sys
m = json.load(open(sys.argv[1])); b = open(sys.argv[2], "rb").read()
want_sha = m.get("oci_cms_sha256") or m.get("cms_sha256"); want_len = m.get("oci_cms_bytes") or m.get("cms_bytes")
ok = hashlib.sha256(b).hexdigest() == want_sha and len(b) == want_len and (not sys.argv[3] or m.get("name") == sys.argv[3])
sys.exit(0 if ok else 1)
PY
  local cs rs
  cs="$(openssl x509 -in "$5" -noout -serial | cut -d= -f2 | tr a-f A-F)"
  rs="$(openssl cms -cmsout -print -inform DER -in "$2" 2>/dev/null | sed -n 's/^ *serialNumber: 0x//p' | head -1 | tr a-f A-F)"
  [[ -n "$cs" && "$cs" == "$rs" ]] || fail "el respaldo NO está cifrado para el certificado fijado (destinatario distinto): no se restaura" 10
  python3 - "$1" "$6" <<'PY' || fail "el manifiesto declara otro certificado destinatario: no se restaura" 10
import json, sys
got = str(json.load(open(sys.argv[1])).get("recipient_cert_sha256") or "").replace(":", "").lower()
sys.exit(0 if got in ("", sys.argv[2]) else 1)
PY
}

# --- tiempos por etapa (acumulativos: una reanudación añade a etapas.tsv)
# RECOVERY_T0 (epoch con decimales, tomado JUSTO ANTES de `terraform apply`) define el T0 de la recuperación completa: el tiempo hasta que arranca este orquestador se registra como etapa
# «aprovisionamiento» (apply de VM/Bastion, sesión y túneles) y el total la incluye. Sin RECOVERY_T0, T0 = inicio del orquestador (VM ya creada): NO es una recuperación completa.
stages_init() {
  STAGE_NAME="inicio"; STAGE_T0="$(NOWF)"; RUN_T0="${RUN_T0:-$STAGE_T0}"
  if [[ -n "${RECOVERY_T0:-}" ]]; then
    [[ "$RECOVERY_T0" =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "RECOVERY_T0 debe ser un epoch en segundos (p. ej. python3 -c 'import time;print(time.time())')"
    RUN_T0="$RECOVERY_T0"
    if [[ ! -s "$OUT/etapas.tsv" ]]; then printf 'aprovisionamiento\t%s\n' "$(python3 -c "print(round($STAGE_T0-$RECOVERY_T0,3))")" >"$OUT/etapas.tsv"; fi
  fi
  [[ -e "$OUT/etapas.tsv" ]] || : >"$OUT/etapas.tsv"; trap finish_status EXIT
}
stage_begin() { STAGE_NAME="$1"; STAGE_T0="$(NOWF)"; }
stage_end() { printf '%s\t%s\n' "$STAGE_NAME" "$(python3 -c "print(round($(NOWF)-$STAGE_T0,3))")" >>"$OUT/etapas.tsv"; STAGE_NAME="(entre etapas)"; }
finish_status() {
  local rc=$?; trap - EXIT
  local res=OK; [[ $rc -eq 0 ]] || res=FALLO
  local total; total="$(python3 -c "print(round($(NOWF)-$RUN_T0,3))")"
  python3 - "$OUT" "$BUNDLE" "$res" "$STAGE_NAME" "$total" <<'PY' 2>/dev/null || true
import json, os, sys
out, bundle, res, stage, total = sys.argv[1:6]
et = {}
for l in open(os.path.join(out, "etapas.tsv")):
    k, v = l.rstrip("\n").split("\t"); et[k] = round(et.get(k, 0) + float(v), 3)
json.dump({"respaldo": bundle, "resultado": res, "etapas": et, "total_s": float(total), "etapa_fallida": stage if res == "FALLO" else None,
           "tipo": "tiempo observado de recuperación (NO es el RTO de un failover AWS–OCI)"}, open(os.path.join(out, "etapas.json"), "w"), indent=1)
PY
  if [[ -n "${OPS_FAILOVER_DIR:-}" ]]; then
    local args=(--dir "$OPS_FAILOVER_DIR" --respaldo "$BUNDLE" --origen "${RECOVERY_ORIGIN:-cloud_verificado}" --resultado "$res" --total "$total")
    [[ "$res" == FALLO ]] && args+=(--etapa-fallida "$(printf %s "$STAGE_NAME" | tr -c 'a-z0-9_' _ | cut -c1-24)")
    local k v
    while IFS=$'\t' read -r k v; do [[ "$k" =~ ^[a-z][a-z0-9_]*$ ]] && args+=(--etapa "$k=$v"); done < <(python3 -c "
import json;[print(k+'\t'+str(v)) for k,v in json.load(open('$OUT/etapas.json'))['etapas'].items()]" 2>/dev/null)
    python3 "$HERE/recovery_status.py" "${args[@]}" || echo "AVISO: no se pudo escribir recovery-run.json" >&2
  fi
  exit $rc
}

# AWS no debe poder escribir mientras se prueba OCI (doble escritor): EC2 de V1 y RDS en estado detenido. Con REQUIRE_AWS_STOPPED=1 (y AWS_PROFILE/REGION del entorno) se comprueba por API;
# cualquier estado distinto de «stopped», o no poder comprobarlo, detiene la prueba (falla cerrada).
aws_writers_quiet() {   # $1 etiqueta para el mensaje
  [[ "${REQUIRE_AWS_STOPPED:-0}" == 1 ]] || return 0
  local ec2 rds
  ec2="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=nexoeventos-academy-app" --query 'Reservations[].Instances[].State.Name' --output text 2>/dev/null || echo ?)"
  rds="$(aws rds describe-db-instances --query 'DBInstances[].DBInstanceStatus' --output text 2>/dev/null || echo ?)"
  [[ -n "$ec2" && -n "$rds" && "$ec2" =~ ^(stopped[[:space:]]*)+$ && "$rds" =~ ^(stopped[[:space:]]*)+$ ]] || fail "AWS NO está en reposo ($1): EC2=[$ec2] RDS=[$rds]; se detiene para evitar doble escritor" 13
  echo "OK    AWS en reposo ($1): EC2 V1 y RDS detenidas (sin escritor en AWS)"
}
