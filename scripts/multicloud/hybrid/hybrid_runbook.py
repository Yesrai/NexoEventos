#!/usr/bin/env python3
"""Cuaderno de ejecución POR ETAPA de la prueba híbrida (solo texto: no ejecuta nada). Para cada etapa A–E: precondición (etapa anterior pasada en hybrid_gate), frase de confirmación exacta, pasos con su alcance
(AWS real / aislado / local), comandos, cambios, reversión, verificación, autorización específica que hay que dar, criterios de parada y los BLOQUEOS vigentes.
Uso: hybrid_runbook.py [A|B|C|D|E|all]"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid_gate as G  # noqa: E402
import hybrid_plan as HP  # noqa: E402

PARADA = ["cualquier error de identidad, región o cuenta distinta de la esperada", "un paso con resultado distinto del esperado: NO continuar, pasar a la etapa E (reversión)",
          "gasto estimado > 0,5 USD o crédito del panel < 10 USD", "cualquier cambio que toque una tabla de negocio o la base de negocio (fence_admin.py lo rechaza fuera de nexo_fence_lab*)",
          "un PAR, objeto o clave fuera del alcance acordado"]


def render(stage: str) -> str:
    name, ids = HP.ETAPAS[stage]; steps = {p["id"]: p for p in HP.PLAN}
    prev = G.ORDER[G.ORDER.index(stage) - 1] if stage != "A" else None
    out = [f"# Etapa {stage} — {name}", f"- Precondición: {'etapa ' + prev + ' registrada como PASADA en hybrid_gate (en E: se puede pedir aunque otra haya fallado)' if prev else 'ninguna'}",
           f"- Frase de confirmación exacta: `{G.FRASES[stage]}`  (hybrid_gate.py start --stage {stage} --confirm …)", "- Criterios de parada: " + "; ".join(PARADA), ""]
    for i in ids:
        p = steps[i]
        out += [f"## {i} · {p['titulo']}", f"- Alcance: {HP.ALCANCE[i]}", "- Comandos:"] + [f"  - `{c}`" for c in p["accion"]]
        out += [f"- Cambia: {p['cambia'] or 'nada'}", f"- Reversión: {p['revierte'] or 'no aplica'}", f"- Verifica: {p['verifica']}", f"- Autorización específica a solicitar: {p['autoriza'] or 'ninguna (solo lectura/local)'}", ""]
    out += ["## Bloqueos vigentes (el failover automático NO se activa mientras existan)"] + [f"- {b}" for b in HP.BLOQUEOS]
    return "\n".join(out)


def main(argv=None) -> int:
    a = (sys.argv[1:] if argv is None else argv) or ["all"]
    stages = G.ORDER if a[0] == "all" else [a[0].upper()]
    if any(s not in HP.ETAPAS for s in stages):
        print("etapa desconocida", file=sys.stderr); return 2
    print("\n\n".join(render(s) for s in stages)); return 0


if __name__ == "__main__":
    sys.exit(main())
