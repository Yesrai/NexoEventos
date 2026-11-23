"""Traduce la salida JSON de `oci_par_probe.py` a los valores de los criterios de T1, SIN transcripción manual. Lo que el probe no midió queda en None (⇒ SIN_MEDIR ⇒ PARCIAL):
nunca se infiere un valor favorable. Solo lee el archivo; no llama a ninguna nube."""
from __future__ import annotations

import json
from pathlib import Path


def _g(d, *ks):
    for k in ks:
        if not isinstance(d, dict) or k not in d: return None
        d = d[k]
    return d


def t1_values(probe: dict) -> dict:
    t = probe.get("tests") or {}; cont = probe.get("contendientes") or {}; race = probe.get("lease_race"); urls = probe.get("estado_url_tras_revocar") or {}
    v: dict = {}
    activos = probe.get("par_activos_tras_revocar")
    v["par_creados_y_revocados"] = None if activos is None or not urls else bool(activos == 0 and all(s is not None and s != 200 for s in urls.values()) and not probe.get("revocacion_errores"))
    if t.get("par_create_if_none_match") is not None and t.get("par_recreate_if_none_match") is not None:
        v["create_duplicado_rechazado"] = bool(t["par_create_if_none_match"] == 200 and t["par_recreate_if_none_match"] == 412)
    if all(t.get(k) is not None for k in ("par_if_match_vigente", "par_if_match_obsoleto", "par_contenido_intacto_tras_412")):
        v["cas_etag_viejo_rechazado"] = bool(t["par_if_match_vigente"] == 200 and t["par_if_match_obsoleto"] == 412 and t["par_contenido_intacto_tras_412"] is True)
    if cont:
        n, ok = cont.get("rondas_ejecutadas"), cont.get("siempre_exactamente_uno")
        if isinstance(n, int):
            v["cas_rondas_con_un_solo_ganador"] = n if ok else max(n - 1, 0)       # el probe se detiene en la primera anomalía
            if ok: v["cas_rondas_con_mas_de_un_ganador"] = 0                       # si no, no se distingue «0 ganadores» de «varios»: SIN_MEDIR
    if isinstance(race, dict) and isinstance(race.get("rondas_aprobadas"), int):
        v["lease_adquisicion_rondas_exclusivas"] = race["rondas_aprobadas"]
        v["lease_adquisicion_violaciones"] = int(race.get("rondas_con_mas_de_un_ganador", 0)) + int(race.get("rondas_con_validos_simultaneos", 0)) + int(race.get("inconclusos", 0)) + int(race.get("rondas_sin_ganador", 0))
    p95 = _g(probe, "latencias_put_exitosos", "p95_s")
    if isinstance(p95, (int, float)): v["p95_put_exitoso_s"] = p95
    sk = probe.get("skew_reloj_s")
    if isinstance(sk, (int, float)): v["reloj_desfase_s"] = sk
    v["ejecucion_sin_interrupcion"] = not (probe.get("detenido") or probe.get("interrumpido"))
    if isinstance(probe.get("limpio"), bool): v["sin_residuos"] = probe["limpio"]
    if isinstance(probe.get("inventario_previo_intacto"), bool): v["inventario_previo_intacto"] = probe["inventario_previo_intacto"]   # lo calcula ejecutar-t1.sh comparando la lectura previa y la posterior
    return {k: x for k, x in v.items() if x is not None}


def apply(run, probe_path) -> dict:
    p = json.loads(Path(probe_path).read_text()); vals = t1_values(p)
    for k, x in vals.items(): run.value(k, x, "automático desde la salida del probe")
    return vals
