#!/usr/bin/env python3
"""Ajustes de precisión en el informe 04 (conteos de comprobaciones y detalles que no estaban respaldados al pie de la letra)."""
from pathlib import Path

p = Path(__file__).resolve().parents[2] / "docs" / "entregable3" / "04-prueba-replicacion-failover-bd.md"
s = p.read_text()
reps = [
    ("Todas las comprobaciones finales pasaron: **A+E 8/8, B 13/13, C 10/10, D+C2b 15/15** (46 en total). Cada etapa se ejecutó en una corrida final; los fallos intermedios y sus causas están en §8.",
     "Todas las comprobaciones de las corridas finales pasaron: **A+E 8/8, B 13/13, C 10/10 y D 5/5** (C2b y D1–D4; la corrida de la que proceden también repitió C y pasó 15/15). Los fallos intermedios y sus causas están en §8."),
    ("(+ `cut-proxy` solo para la prueba de caída tras confirmar)", "(+ contenedores bajo demanda: `migrate`, `cut-proxy` para la prueba de caída tras confirmar y, solo en la etapa E, `app-stale` con su sidecar)"),
    ("**Nueve contenedores permanentes, no ocho** (más tres de perfil `fault`/`stale`/`tools` bajo demanda).", "**Ocho contenedores permanentes más el reparto del gateway de BD en dos sidecars, es decir nueve en total, no ocho.**"),
    ("el cliente no recibió respuesta; tras 6 reintentos 503, la misma clave devolvió **200 con la misma reserva** (`replayed: true`), 4,5 s después de la caída; 1 sola reserva.",
     "el cliente no recibió respuesta y reintentó con la misma clave; la respuesta válida fue **200 con la misma reserva** (`replayed: true`), 4,5 s después de la caída; 1 sola reserva."),
    ("# ~45 min", "# ~40 min"),
]
for a, b in reps:
    assert a in s, a[:60]
    s = s.replace(a, b)
p.write_text(s)
print("ok")
