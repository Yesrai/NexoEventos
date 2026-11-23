#!/usr/bin/env bash
# T1 — lease real por PAR en OCI. UN solo punto de entrada, determinista.
#   Sin --autorizo: modo PLAN (SOLO LECTURA): ejecuta `oci_par_probe.py --plan-only`, muestra qué haría T1 y la frase exacta de autorización. No crea nada.
#   Con --autorizo "<frase exacta>": registra evidencia, lectura previa (aborta si no es LISTO), ejecuta el probe (crea y revoca 3 PAR), lectura posterior, compara inventarios, veredicto.
set -uo pipefail
umask 077   # todos los archivos de evidencia nacen 0600/0700
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
FRASE="AUTORIZO T1 EN OCI: oci_par_probe.py, bucket nexoeventos-recovery, perfil DEFAULT, 3 PAR temporales"
PROBE_PY="${NEXO_PROBE_PY:-/opt/homebrew/Cellar/oci-cli/3.95.0/libexec/bin/python}"; PROBE="${NEXO_PROBE:-scripts/multicloud/hybrid/oci_par_probe.py}"
OPS_PY="${NEXO_OPS_PY:-$ROOT/backend/.venv/bin/python}"; EVROOT="${NEXO_EVIDENCE_ROOT:-work/evidencias}"; WORK="${NEXO_T1_WORKDIR:-work/hybrid/par-probe}"
BUCKET="nexoeventos-recovery"; PROFILE="DEFAULT"; PREFIX="hybrid-test/par-probe-$(date -u +%Y%m%d)/"; AUTH=""
while [[ $# -gt 0 ]]; do case "$1" in --autorizo) AUTH="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
export SUPPRESS_LABEL_WARNING=True
probe() { "$PROBE_PY" "$PROBE" --admin-profile "$PROFILE" --bucket "$BUCKET" --prefix "$PREFIX" --workdir "$WORK" "$@"; }
if [[ "$AUTH" != "$FRASE" ]]; then
  echo "MODO PLAN (solo lectura). Para ejecutar T1 hay que pasar EXACTAMENTE:"; echo "  --autorizo \"$FRASE\""; echo
  probe --plan-only 2>&1 | grep -v '^Warning'; exit "${PIPESTATUS[0]}"
fi
OPS() { "$OPS_PY" -m ops_center "$@"; }
RUN="$(OPS evidence-start T1 --root "$EVROOT")" || { echo "no se pudo iniciar la evidencia" >&2; exit 2; }
echo "evidencia: $RUN"; OPS evidence-event "$RUN" "autorizacion_recibida" >/dev/null
trap 'echo "INTERRUMPIDO: ejecute  $PROBE_PY $PROBE --admin-profile $PROFILE --bucket $BUCKET --prefix $PREFIX --workdir $WORK --cleanup-only  (revoca y limpia) y revise $RUN" >&2' INT TERM
PRE="$RUN/lectura-previa.json"; probe --plan-only 2>&1 | grep -v '^Warning' > "$PRE"; RC=${PIPESTATUS[0]}
OPS evidence-attach "$RUN" "$PRE" --redacted >/dev/null
if [[ $RC -ne 0 ]]; then echo "ABORTA: la lectura previa NO es LISTO (código $RC). No se creó nada."; OPS evidence-event "$RUN" "abortado_lectura_previa" >/dev/null; OPS evidence-finish "$RUN" || true; exit 2; fi
OPS evidence-mark "$RUN" inicio_probe >/dev/null
OUT="$RUN/probe-salida.json"; probe --rounds 20 --contenders 8 --lease-race-rounds 20 --max-minutes 20 > "$OUT" 2> "$RUN/probe-stderr.txt"; PRC=$?
OPS evidence-mark "$RUN" fin_probe >/dev/null; OPS evidence-event "$RUN" "probe_terminado" >/dev/null
POST="$RUN/lectura-posterior.json"; probe --plan-only 2>&1 | grep -v '^Warning' > "$POST"; QRC=${PIPESTATUS[0]}
OPS evidence-attach "$RUN" "$POST" --redacted >/dev/null; OPS evidence-attach "$RUN" "$OUT" --redacted >/dev/null
# inventario previo intacto: mismos objetos y bytes, 0 PAR, y la lectura posterior vuelve a dar LISTO
"$OPS_PY" - "$PRE" "$POST" "$OUT" "$QRC" <<'PY'
import json, sys
pre, post, out, qrc = (sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
try:
    a = json.load(open(pre)); b = json.load(open(post)); o = json.load(open(out))
    o["inventario_previo_intacto"] = bool(qrc == 0 and a.get("objetos_vigentes") == b.get("objetos_vigentes") and a.get("bytes_vigentes") == b.get("bytes_vigentes") and b.get("par_activos_en_el_bucket") == 0)
    json.dump(o, open(out, "w"))
except Exception as e:   # salida del probe ilegible: no se infiere nada; el veredicto quedará PARCIAL/FAIL
    print("no se pudo fusionar el inventario:", type(e).__name__, file=sys.stderr)
PY
OPS evidence-t1 "$RUN" --probe "$OUT"; VERD="$(OPS evidence-finish "$RUN")"; OPS evidence-verify "$RUN" >/dev/null && MAN="manifiesto íntegro" || MAN="MANIFIESTO ALTERADO"
echo "veredicto T1: $VERD · probe exit=$PRC · lectura posterior exit=$QRC · $MAN"; echo "evidencia: $RUN"
[[ "$VERD" == "PASS" && $PRC -eq 0 && $QRC -eq 0 ]] && exit 0 || { echo "T1 NO está en PASS: no registre T1 como aprobada; revise $RUN/resultado.md" >&2; exit 1; }
