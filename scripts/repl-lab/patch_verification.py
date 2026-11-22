#!/usr/bin/env python3
"""Corrige defectos de la VERIFICACIÓN (no del aislamiento) detectados en la corrida 4 de B:
1) en una partición el nombre DNS del nodo no resuelve desde su propio contenedor: una 'conexión rechazada' por DNS no prueba nada; se verifica por loopback y se exige el
   mensaje de rechazo de pg_hba ('pg_hba.conf rejects') para dar por buena una negativa;
2) la línea [lab-entry] del arranque quedaba fuera de `docker logs --tail 40` (los rechazos de pg_hba llenan el log): se busca en todo el log;
3) B4 competía con el monitor (que correctamente volvía a cerrar el nodo expuesto): el baseline se hace con el monitor detenido y la guardia se prueba aparte;
4) se restablece la comprobación de 'nunca dos escritores' de B2 que se había perdido en un parche anterior."""
from pathlib import Path

here = Path(__file__).parent
L = (here / "labctl.py").read_text()

# 1) loopback cuando el origen es el propio nodo; negativa válida solo si es rechazo de pg_hba
old = '''    cmd += [cname(o), "psql", "-X", "-q", "-U", "nexoeventos_app", "-d", "nexoeventos", "-h", node, "-tA", "-v", "ON_ERROR_STOP=1", "-c", q]'''
new = '''    host = "127.0.0.1" if o == node else node     # desde su propio contenedor: loopback (el nombre DNS no resuelve si el nodo está particionado)
    cmd += [cname(o), "psql", "-X", "-q", "-U", "nexoeventos_app", "-d", "nexoeventos", "-h", host, "-tA", "-v", "ON_ERROR_STOP=1", "-c", q]'''
assert old in L
L = L.replace(old, new)
old = '''        verified = d["modo_cerrado"].get("efecto_en_conexion_nueva") and d["sesiones_app_terminadas"] and not w_ok and not o_ok'''
new = '''        hba_w, hba_o = "pg_hba.conf rejects" in w_err, "pg_hba.conf rejects" in o_err   # una negativa por DNS o por tiempo agotado NO cuenta como aislamiento verificado
        d.update(rechazo_atribuible_a_pg_hba=hba_w and hba_o)
        verified = d["modo_cerrado"].get("efecto_en_conexion_nueva") and d["sesiones_app_terminadas"] and not w_ok and not o_ok and hba_w and hba_o'''
assert old in L
L = L.replace(old, new)
(here / "labctl.py").write_text(L)

T = (here / "repl_test.py").read_text()
# 2) línea de arranque en todo el log
old = '''        boot_log = run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr'''
new = '''        boot_log = run("docker", "logs", L.cname("pg-aws")).stderr'''
assert old in T
T = T.replace(old, new)
T = T.replace('''line5 = next((l for l in reversed(run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")''',
              '''line5 = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")''')
T = T.replace('''line5b = next((l for l in reversed(run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")''',
              '''line5b = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")''')

# 4) comprobación perdida de B2
old = '''    fl_ev = [e for e in events(log2) if e["ev"] == "fence_en_linea"] if (log2 := OUT / "eventos-B2.jsonl") else []'''
new = '''    check("B2 muestreo con escrituras reales (~3 por segundo y nodo) durante toda la conmutación y el regreso: ninguna muestra con dos escritores (NO demuestra la ausencia de split-brain: solo no se observó)",
          d["sondeo"]["con_dos_escritores"] == 0, d["sondeo"])
    fl_ev = [e for e in events(OUT / "eventos-B2.jsonl") if e["ev"] == "fence_en_linea"]'''
assert old in T
T = T.replace(old, new)

# 3) B4 con el monitor detenido + prueba de la guardia
a = T.index("    # B4: default_transaction_read_only NO es fencing")
b = T.index("    # B5: arranque cerrado ante la duda")
b4 = '''    # B4: default_transaction_read_only NO es fencing: la propia aplicación puede anularlo; el pg_hba cerrado sí lo impide
    fresh_lab("B4")
    stop_monitor()                               # baseline sin monitor: el monitor (correctamente) volvería a cerrar el nodo expuesto
    pre = L.set_mode("pg-oci", "open")           # simula un seguidor protegido solo por el ajuste de solo-lectura
    ok_ro, e_ro = L.app_connect("pg-oci", write=True, origin="pg-oci")
    ok_ov, e_ov = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    post = L.set_mode("pg-oci", "fenced")
    ok_ro2, e_ro2 = L.app_connect("pg-oci", write=True, origin="pg-oci")
    ok_ov2, e_ov2 = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    DATA["B4"] = {"solo_lectura_por_GUC_escritura_directa": [ok_ro, e_ro], "solo_lectura_por_GUC_con_anulacion_desde_la_sesion": [ok_ov, e_ov],
                  "con_pg_hba_cerrado_escritura_directa": [ok_ro2, e_ro2], "con_pg_hba_cerrado_con_anulacion": [ok_ov2, e_ov2]}
    check("B4 solo default_transaction_read_only NO basta: la aplicación lo anula desde su propia sesión y escribe; con el pg_hba cerrado la misma conexión nueva es rechazada",
          not ok_ro and ok_ov and not ok_ro2 and not ok_ov2 and "pg_hba.conf rejects" in e_ov2, DATA["B4"])
    # guardia secundaria: un nodo no escritor que quede ABIERTO es detectado y cerrado por el monitor
    L.set_mode("pg-oci", "open")
    log4 = start_monitor("B4-guardia")
    t_g = time.time()
    t_iso = wait_until(lambda: ev_t(events(log4), "nodo_no_escritor_aislado", t_g) is not None, 30)
    ok_g, e_g = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    DATA["B4"]["guardia_del_monitor"] = {"aislado_tras_s": None if t_iso is None else round(t_iso, 1), "escritura_con_anulacion_despues": [ok_g, e_g]}
    check("B4 la guardia del monitor detecta un nodo no escritor ABIERTO, lo cierra y una escritura real con anulación posterior es rechazada por pg_hba",
          t_iso is not None and not ok_g and "pg_hba.conf rejects" in e_g, DATA["B4"]["guardia_del_monitor"])

'''
T = T[:a] + b4 + T[b:]
(here / "repl_test.py").write_text(T)
print("ok")
