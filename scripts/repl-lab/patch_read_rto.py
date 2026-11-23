#!/usr/bin/env python3
"""Corrige la métrica de RTO de lectura: fl.Load registra instantes con time.monotonic() y el resto del laboratorio usa time.time(); se convierten a reloj de pared.
Además se conservan las líneas de tiempo crudas (lecturas y escrituras) de cada corrida como evidencia."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = '''    reads_bad = [r for r in load.rows if r[0] >= t_kill and r[1] != 200]
    last_rb = max((r[0] for r in reads_bad), default=None)
    first_ok_r = next((r[4] for r in sorted(load.rows) if last_rb is not None and r[0] > last_rb and r[1] == 200), None)'''
new = '''    off = time.time() - time.monotonic()      # fl.Load usa reloj monotónico; aquí todo va en reloj de pared
    rrows = sorted((r[0] + off, r[1], r[2], r[3], r[4] + off) for r in load.rows)
    reads_bad = [r for r in rrows if r[0] >= t_kill and r[1] != 200]
    last_rb = max((r[0] for r in reads_bad), default=None)
    first_bad_r = min((r[0] for r in reads_bad), default=None)
    first_ok_r = next((r[4] for r in rrows if last_rb is not None and r[0] > last_rb and r[1] == 200), None)
    (OUT / f"c1-{tag}-lineas-de-tiempo.json").write_text(json.dumps({"t_kill": t_kill,
        "lecturas": [{"t_s_desde_la_caida": round(r[0] - t_kill, 3), "http": r[1], "latencia_ms": round(r[2] * 1000, 1), "atendida_por_o_error": r[3]} for r in rrows],
        "escrituras": [{"t_s_desde_la_caida": round(t0 - t_kill, 3), "http_0_es_error_de_red": st, "fin_s": round(te - t_kill, 3)} for t0, st, te in sorted(att)]}) + "\\n")'''
assert old in s
s = s.replace(old, new)
old = '''        "RTO_lectura_s": None if first_ok_r is None else round(first_ok_r - t_kill, 2),'''
new = '''        "RTO_lectura_s": None if first_ok_r is None else round(first_ok_r - t_kill, 2),
        "lectura_primer_error_s": None if first_bad_r is None else round(first_bad_r - t_kill, 2),
        "lectura_ultimo_error_s": None if last_rb is None else round(last_rb - t_kill, 2),'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
