#!/usr/bin/env python3
"""Escribe `recovery-run.json` (0600, reemplazo atómico) en OPS_FAILOVER_DIR para el panel Operación: estado REAL y tiempos por etapa de una recuperación (aislada o de la aplicación).
Solo campos de una lista blanca, sin secretos ni rutas. No es un failover: el panel lo etiqueta como tiempo observado de recuperación.
Uso: recovery_status.py --dir DIR --respaldo nexoeventos-rds-... --origen local|simulado|cloud_verificado --resultado OK|FALLO [--etapa-fallida X] --etapa descarga=4.6 --etapa verificacion=0.2 ..."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

STAGE_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


def write(dir_: str, *, respaldo: str, origen: str, resultado: str, etapas: dict, etapa_fallida: str | None = None, total_s: float | None = None) -> Path:
    if origen not in ("local", "simulado", "cloud_verificado"):
        raise ValueError("origen inválido")
    if resultado not in ("OK", "FALLO"):
        raise ValueError("resultado inválido")
    if not re.match(r"^[A-Za-z0-9._-]{1,64}$", respaldo):
        raise ValueError("identificador de respaldo inválido")
    clean = {}
    for k, v in etapas.items():
        if not STAGE_RE.match(k) or isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError("etapa inválida")
        clean[k] = round(float(v), 3)
    data = {"respaldo": respaldo, "origen": origen, "resultado": resultado, "etapas": clean, "total_s": round(float(total_s if total_s is not None else sum(clean.values())), 3)}
    if etapa_fallida:
        if not STAGE_RE.match(etapa_fallida):
            raise ValueError("etapa fallida inválida")
        data["etapa_fallida"] = etapa_fallida
    d = Path(dir_); d.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = d / "recovery-run.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, d / "recovery-run.json")
    return d / "recovery-run.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True); ap.add_argument("--respaldo", required=True); ap.add_argument("--origen", required=True); ap.add_argument("--resultado", required=True)
    ap.add_argument("--etapa-fallida", default=None); ap.add_argument("--total", type=float, default=None); ap.add_argument("--etapa", action="append", default=[], help="nombre=segundos")
    a = ap.parse_args(argv)
    try:
        et = {k: float(v) for k, v in (x.split("=", 1) for x in a.etapa)}
        write(a.dir, respaldo=a.respaldo, origen=a.origen, resultado=a.resultado, etapas=et, etapa_fallida=a.etapa_fallida, total_s=a.total)
    except (ValueError, OSError) as e:
        print(f"recovery_status: {e}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
