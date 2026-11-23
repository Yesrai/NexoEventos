#!/usr/bin/env python3
"""Compuerta de ETAPAS A–E de la prueba híbrida. Una etapa solo puede ejecutarse si la anterior está registrada como PASADA y si se da la frase de confirmación EXACTA de esa etapa;
si una etapa FALLA, las siguientes quedan bloqueadas (solo se permite E, la reversión). Nunca se autoriza sola la siguiente. El estado vive en un archivo 0600 (--state-file) y no guarda secretos.
Uso: hybrid_gate.py status|start|pass|fail --state-file F [--stage A..E] [--confirm FRASE] [--note TEXTO]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ORDER = ["A", "B", "C", "D", "E"]
# Autorizaciones INDEPENDIENTES y limitadas: no desbloquean ninguna etapa A–E. A12 = pasos A1/A2 (PAR y objetos de laboratorio en OCI; no tocan AWS). Requieren la etapa A pasada.
SUBPASOS = {"A12": "A", "B1": "A", "B2": "A", "B3": "A", "F0": "A"}                       # B1 = SOLO encender la RDS (la EC2 ya encendida se reutiliza) y apagar todo al terminar; NO desbloquea B2, B3, B4 ni la etapa B
FRASES = {"F0": "EJECUTAR F0 LABORATORIO SEAL OCI", "B3": "EJECUTAR PASO B3 VALLADO FUERTE EN NEXO_FENCE_LAB", "B2": "EJECUTAR PASO B2 PRECHECK DE SOLO LECTURA", "A12": "EJECUTAR PASO A1 A2 PAR DE LABORATORIO", "B1": "EJECUTAR PASO B1 ENCENDER RDS", "A": "EJECUTAR ETAPA A SOLO LECTURA", "B": "EJECUTAR ETAPA B PREPARACION REVERSIBLE", "C": "EJECUTAR ETAPA C VALLADO AISLADO", "D": "EJECUTAR ETAPA D PARTICION", "E": "EJECUTAR ETAPA E REVERSION"}


class GateError(Exception):
    pass


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"stages": {k: {"estado": "pendiente"} for k in ORDER}}
    if p.stat().st_mode & 0o077:
        raise GateError("el archivo de estado debe tener permisos 0600")
    return json.loads(p.read_text())


def save(path: str, st: dict) -> None:
    tmp = f"{path}.tmp"; fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


REQUIERE = {"B2": ("B1", ("en curso", "pasada")), "B3": ("B2", ("pasada",))}      # B2 necesita la RDS encendida por B1 (B1 en curso o pasado)


def can_start(st: dict, stage: str) -> tuple[bool, str]:
    s = st["stages"]
    s.setdefault(stage, {"estado": "pendiente"})
    if stage in SUBPASOS:
        if s[stage]["estado"] in ("en curso", "pasada"):
            return False, f"el paso {stage} ya está {s[stage]['estado']}"
        if stage in REQUIERE and s.get(REQUIERE[stage][0], {}).get("estado") not in REQUIERE[stage][1]:
            return False, f"el paso {stage} exige {REQUIERE[stage][0]} en curso o pasado"
        return (True, "ok") if s[SUBPASOS[stage]]["estado"] == "pasada" else (False, f"el paso {stage} exige la etapa {SUBPASOS[stage]} pasada")
    if s[stage]["estado"] in ("en curso", "pasada"):
        return False, f"la etapa {stage} ya está {s[stage]['estado']}"
    if stage == "E":                                                                  # la reversión siempre se puede pedir (aunque algo haya fallado) salvo que ya esté hecha
        return (False, "hay otra etapa en curso: termínala o márcala como fallida") if any(v["estado"] == "en curso" for v in s.values()) else (True, "ok")
    for prev in ORDER[:ORDER.index(stage)]:
        if s[prev]["estado"] == "fallida":
            return False, f"BLOQUEADA: la etapa {prev} falló; solo se permite la etapa E (reversión)"
        if s[prev]["estado"] != "pasada":
            return False, f"la etapa {prev} aún no ha pasado"
    return True, "ok"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["status", "start", "pass", "fail"]); ap.add_argument("--state-file", required=True)
    ap.add_argument("--stage", choices=ORDER + list(SUBPASOS)); ap.add_argument("--confirm", default=""); ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    try:
        st = load(a.state_file)
        if a.cmd == "status":
            print(json.dumps(st, indent=1, ensure_ascii=False)); return 0
        if not a.stage:
            print("falta --stage", file=sys.stderr); return 2
        if a.cmd == "start":
            ok, why = can_start(st, a.stage)
            if not ok:
                print(f"RECHAZADO: {why}", file=sys.stderr); return 3
            if a.confirm != FRASES[a.stage]:
                print(f"RECHAZADO: falta la frase de confirmación exacta de la etapa {a.stage}", file=sys.stderr); return 3
            st["stages"][a.stage] = {"estado": "en curso", "inicio": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        else:
            if st["stages"].get(a.stage, {}).get("estado") != "en curso":
                print("RECHAZADO: la etapa no está en curso", file=sys.stderr); return 3
            st["stages"][a.stage].update({"estado": "pasada" if a.cmd == "pass" else "fallida", "fin": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "nota": a.note[:300]})
        save(a.state_file, st); print(f"OK    etapa {a.stage}: {st['stages'][a.stage]['estado']}"); return 0
    except (GateError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
