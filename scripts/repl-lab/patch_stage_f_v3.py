#!/usr/bin/env python3
"""Ajustes de F v2: (1) las caídas del controlador PROVOCADAS en F5x no deben ser tratadas por la prueba como 'monitor muerto inesperadamente'; (2) F6 cuenta de verdad las promociones
automáticas hacia la antigua primaria."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = '''def mon_check():
    """Las pruebas fallan de inmediato si el monitor terminó de forma inesperada (nunca se continúa con un monitor muerto)."""
    if MON is not None and MON.poll() is not None:'''
new = '''FLAGS = {"mon_death_ok": False}      # True solo mientras una prueba PROVOCA la caída del controlador (inyección de fallos)


def mon_check():
    """Las pruebas fallan de inmediato si el monitor terminó de forma inesperada (nunca se continúa con un monitor muerto)."""
    if FLAGS["mon_death_ok"]:
        return
    if MON is not None and MON.poll() is not None:'''
assert old in s
s = s.replace(old, new)
old = '''                log = fresh_lab(tag, sync=True, env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": f"{point}:{action}"})'''
new = '''                FLAGS["mon_death_ok"] = action == "exit"
                log = fresh_lab(tag, sync=True, env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": f"{point}:{action}"})'''
assert old in s
s = s.replace(old, new)
old = '''                    MON_ALIVE = MON.poll() is None if MON else False
                    log = start_monitor(tag + "-reinicio", env={"LAB_DEGRADE_AFTER_S": "3"})
                    msleep(4)'''
new = '''                    MON_ALIVE = MON.poll() is None if MON else False
                    FLAGS["mon_death_ok"] = False
                    log = start_monitor(tag + "-reinicio", env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": ""})
                    msleep(4)'''
assert old in s
s = s.replace(old, new)
old = '''                w.halt()
                DATA.setdefault("F5x", {})[tag]'''
new = '''                w.halt()
                FLAGS["mon_death_ok"] = False
                DATA.setdefault("F5x", {})[tag]'''
assert old in s
s = s.replace(old, new)
old = '''"promociones_automaticas_hacia_ella": n_prom_after - n_prom_before if False else None},'''
new = '''"promociones_automaticas_hacia_ella": n_prom_after - n_prom_before},'''
assert old in s
s = s.replace(old, new)
old = '''and writer_after_return == "pg-oci"
              and names_cleaned'''
new = '''and writer_after_return == "pg-oci" and n_prom_after == n_prom_before
              and names_cleaned'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
