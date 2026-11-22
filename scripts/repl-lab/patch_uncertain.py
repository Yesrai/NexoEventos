#!/usr/bin/env python3
"""C1: cuantifica las transacciones INCIERTAS. Tras la conmutación se arranca la antigua primaria (cerrada, solo lectura), se exportan sus filas ausentes en la nueva primaria
y se clasifican las reservas huérfanas: confirmadas al cliente y perdidas (RPO observado) frente a NO confirmadas al cliente (inciertas: el commit existió, el cliente no recibió
respuesta y la fila no llegó a replicarse; el cliente reintentó con la misma clave y obtuvo otra reserva => duplicado lógico potencial)."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = '''    lost = [a for a in acked if a[2] not in ids]
    acked_ids = {a[2] for a in acked}'''
new = '''    lost = [a for a in acked if a[2] not in ids]
    acked_ids = {a[2] for a in acked}
    orf_dir = OUT / f"huerfanas-{tag}"
    orf_summary = L.orphans("pg-aws", "pg-oci", str(orf_dir))
    orf_file = sorted(orf_dir.glob("huerfanas-pg-aws-*.json"))[-1]
    orf_rows = json.loads(orf_file.read_text())["filas"].get("reservations", [])
    orf_ids = {r["id"] for r in orf_rows}
    orf_confirmed = orf_ids & acked_ids
    orf_uncertain = orf_ids - acked_ids
    orf_dups = orf_summary["duplicados_logicos_por_idempotency_key"]'''
assert old in s
s = s.replace(old, new)
old = '''        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),'''
new = '''        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),
        "huerfanas_en_la_antigua_primaria_reservas": len(orf_ids),
        "huerfanas_confirmadas_al_cliente_(perdidas)": len(orf_confirmed),
        "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)": len(orf_uncertain),
        "huerfanas_con_clave_repetida_en_la_nueva_primaria_(duplicado_logico)": len(orf_dups),
        "perdidas_confirmadas_coinciden_con_las_huerfanas_confirmadas": {a[2] for a in lost} == orf_confirmed,'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
