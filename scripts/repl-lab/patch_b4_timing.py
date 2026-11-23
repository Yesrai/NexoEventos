#!/usr/bin/env python3
"""B4: el instante de referencia se toma ANTES de arrancar el monitor (la guardia actuó dentro de los 1,5 s de espera de start_monitor y el evento quedaba anterior a t_g)."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = '''    L.set_mode("pg-oci", "open")
    log4 = start_monitor("B4-guardia")
    t_g = time.time()
'''
new = '''    L.set_mode("pg-oci", "open")
    t_g = time.time()
    log4 = start_monitor("B4-guardia")
'''
assert old in s
p.write_text(s.replace(old, new))
print("ok")
