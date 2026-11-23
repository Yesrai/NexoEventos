#!/usr/bin/env python3
"""Etapa D adaptada al arranque cerrado: el antiguo escritor reiniciado arranca CERRADO (no hace falta que el monitor lo aísle) y el monitor solo se pausa durante la promoción
(no durante el rescate de huérfanas ni la reconstrucción, para que siga renovando el lease del escritor vigente)."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()

a = s.index("    # D1: reinicio \"a mano\" de la antigua primaria")
b = s.index("    # D2: rescatar lo que solo existe en la antigua primaria")
d1 = '''    # D1: reinicio "a mano" de la antigua primaria (monitor en marcha, pero sin depender de él): arranca CERRADA y rechaza toda escritura real
    run("docker", "start", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    win = []
    for _ in range(20):
        okw, ew = L.app_connect("pg-aws", write=True)
        oko, eo = L.app_connect("pg-aws", write=True, override=True)
        win.append((okw, oko, ew[:100])); time.sleep(0.25)
    boot = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    hap = L.hap_state()
    check("D1 la antigua primaria reiniciada a mano arranca CERRADA (witness: otro escritor), no recibe tráfico de HAProxy-BD y rechaza 20 intentos de escritura real directa, también con anulación del solo-lectura",
          "modo fenced" in boot and not any(w[0] or w[1] for w in win) and not hap.get("pg-aws", "").startswith("UP"),
          {"arranque": boot, "intentos": len(win), "aceptados": sum(1 for w in win if w[0] or w[1]), "ejemplo_de_rechazo": win[0][2], "haproxy_db": hap, "witness": L.witness_state()})
'''
s = s[:a] + d1 + s[b:]
s = s.replace('''    with L.paused():
        summ = L.orphans("pg-aws", "pg-oci", str(OUT))''', '''    summ = L.orphans("pg-aws", "pg-oci", str(OUT))''')
s = s.replace('''    with L.paused():
        L.reseed("pg-aws", "pg-oci")''', '''    L.reseed("pg-aws", "pg-oci")''')
s = s.replace('''    with L.paused():
        summ2 = L.orphans("pg-oci", "pg-aws", str(OUT))
        L.reseed("pg-oci", "pg-aws")''', '''    summ2 = L.orphans("pg-oci", "pg-aws", str(OUT))
    L.reseed("pg-oci", "pg-aws")''')
p.write_text(s)
print("ok")
