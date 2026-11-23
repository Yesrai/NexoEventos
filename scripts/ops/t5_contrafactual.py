#!/usr/bin/env python3
"""T5 — cálculo CONTRAFACTUAL con las muestras reales de un intento (NO es una medición ni una demostración): cuántos fallos admite el 99 % y qué disponibilidad resultaría SI el ALB hubiera dejado de enrutar a la
víctima D segundos después del primer error, con N destinos (cada destino recibe 1/N de las solicitudes; los fallos observados con N=2 se escalan por (1/N)/(1/2)). Reproducible: python3 scripts/ops/t5_contrafactual.py solicitudes.json
Marca TODA cifra derivada como estimación; la única medida real es la de D=detección observada con N=2."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def analyze(reqs, destinos=(2, 3, 4, 6, 8), detecciones=(None, 12, 10, 8, 5), observados_n=2):
    health = [r for r in reqs if r["path"] in ("/healthz", "/livez")]
    errs = [r for r in reqs if r["status"] != 200]
    if not errs:
        return {"errores": 0}
    e0, e1 = min(r["t"] for r in errs), max(r["t"] for r in errs); obs_d = e1 - e0
    out = {"solicitudes": len(reqs), "health": len(health), "errores": len(errs), "errores_health": sum(1 for r in errs if r["path"] in ("/healthz", "/livez")), "primer_error": e0, "ultimo_error": e1, "ventana_errores_s": round(obs_d, 2),
           "maximo_errores_99_health": math.floor(0.01 * len(health)), "maximo_errores_99_todas": math.floor(0.01 * len(reqs)), "disponibilidad_health_observada": round(100 * (1 - sum(1 for r in errs if r["path"] in ("/healthz", "/livez")) / len(health)), 2), "tabla": []}
    for n in destinos:
        for d in detecciones:
            corte = e0 + (d if d is not None else obs_d + 1e-9)
            eh = sum(1 for r in errs if r["path"] in ("/healthz", "/livez") and r["t"] <= corte)
            est = eh * (1 / n) / (1 / observados_n)
            out["tabla"].append({"destinos": n, "deteccion_s": d if d is not None else round(obs_d, 1), "fallos_health_estimados": round(est, 1), "disponibilidad_health_estimada": round(100 * (1 - est / len(health)), 2), "cumple_99": est <= out["maximo_errores_99_health"]})
    # detección máxima que admite el 99 % para cada N
    out["deteccion_maxima_para_99"] = {}
    for n in destinos:
        best = None
        for d10 in range(0, 400):
            d = d10 / 10; eh = sum(1 for r in errs if r["path"] in ("/healthz", "/livez") and r["t"] <= e0 + d)
            if eh * (1 / n) / (1 / observados_n) > out["maximo_errores_99_health"]:
                best = d; break
        out["deteccion_maxima_para_99"][n] = best if best is not None else f">{round(obs_d, 1)}"
    return out


if __name__ == "__main__":
    r = analyze(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps(r, indent=1, ensure_ascii=False))
