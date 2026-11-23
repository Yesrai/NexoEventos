#!/usr/bin/env python3
"""Análisis de los registros de las sondas de escritor de los DOS lados: ¿hubo instantes en que ambos confirmaron escrituras a la vez? Entradas: JSONL de writer_probe.py (uno por lado).
Solo cuenta las ACEPTADAS. Dos confirmaciones «simultáneas» son las que difieren menos de `tolerance_s` (el desfase de reloj entre máquinas: medirlo antes con NTP; por defecto 0,5 s).
Veredicto SEGURO solo si: no hay solapamientos, ambos lados escribieron en algún momento (la prueba tuvo efecto) y el escritor anterior (--hold) fue rechazado."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def load(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def verdict(a: list[dict], b: list[dict], tolerance_s: float = 0.5) -> dict:
    acc_a = sorted(ts(r["t_end"]) for r in a if r.get("accepted"))
    acc_b = sorted(ts(r["t_end"]) for r in b if r.get("accepted"))
    overlaps = [(x, y) for x in acc_a for y in acc_b if abs(x - y) < tolerance_s]
    holds = [r for r in a + b if r.get("mode") == "hold"]
    stale_rejected = all(not r.get("accepted") for r in holds) if holds else None
    last_a, first_b = (acc_a[-1] if acc_a else None), (acc_b[0] if acc_b else None)
    gap = round(first_b - last_a, 3) if (last_a and first_b) else None
    safe = (not overlaps) and bool(acc_a) and bool(acc_b) and stale_rejected is not False
    return {"seguro": safe, "solapamientos": len(overlaps), "confirmaciones": {"lado_a": len(acc_a), "lado_b": len(acc_b)},
            "escritor_anterior_rechazado": stale_rejected, "hueco_entre_el_ultimo_commit_de_A_y_el_primero_de_B_s": gap,
            "tolerancia_s": tolerance_s, "nota": "sin escrituras de ambos lados la prueba NO tuvo efecto" if not (acc_a and acc_b) else ""}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("uso: analyze.py LADO_A.jsonl LADO_B.jsonl [tolerancia_s]", file=sys.stderr); return 2
    v = verdict(load(argv[0]), load(argv[1]), float(argv[2]) if len(argv) > 2 else 0.5)
    print(json.dumps(v, indent=1, ensure_ascii=False)); return 0 if v["seguro"] else 1


if __name__ == "__main__":
    sys.exit(main())
