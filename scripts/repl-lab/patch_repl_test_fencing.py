#!/usr/bin/env python3
"""Actualiza repl_test.py: el regreso del antiguo escritor se prueba SIN monitor (el arranque cerrado debe bastar), con escrituras reales directas
(conexión nueva y con intento de anular el solo-lectura); nuevos escenarios B4 (solo-lectura por GUC no es fencing) y B5 (arranque cerrado con witness caído)."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()

# ---- B2: ventana de regreso del antiguo escritor, sin monitor
a = s.index("        run(\"docker\", \"network\", \"connect\", \"--alias\", \"pg-aws\", NET, L.cname(\"pg-aws\"))\n        run(\"docker\", \"start\", L.cname(\"pg-aws\"))\n        t_back = time.time(); window = []")
b = s.index("        d = {\"rto_bd_hasta_lease_s\"")
new_back = '''        # REGRESO del antiguo escritor SIN monitor: el arranque cerrado (witness != yo => pg_hba que rechaza todo) debe bastar por sí solo
        stop_monitor()
        run("docker", "network", "connect", "--alias", "pg-aws", NET, L.cname("pg-aws"))
        run("docker", "start", L.cname("pg-aws"))
        t_back = time.time(); window = []
        wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
        for _ in range(25):
            okw, ew = L.app_connect("pg-aws", write=True)
            oko, eo = L.app_connect("pg-aws", write=True, override=True)
            window.append({"t_s": round(time.time() - t_back, 2), "escritura_nueva_conexion_aceptada": okw, "escritura_con_anulacion_aceptada": oko, "error": ew[:110]})
            time.sleep(0.25)
        boot_log = run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr
        boot_line = next((l for l in reversed(boot_log.splitlines()) if "[lab-entry]" in l), "")
        accepted = [w for w in window if w["escritura_nueva_conexion_aceptada"] or w["escritura_con_anulacion_aceptada"]]
        log = start_monitor("B2-tras-regreso")
'''
s = s[:a] + new_back + s[b:]
s = s.replace('''             "antiguo_escritor_reiniciado_tras_sanar_la_red": {"muestras_de_escritura_real": window, "escrituras_aceptadas_mientras_estuvo_expuesto": len(accepted),
                                                            "primer_rechazo_s": next((w[0] for w in window if not w[1]), None)},''','''             "antiguo_escritor_reiniciado_tras_sanar_la_red_SIN_monitor": {"arranque": boot_line, "intentos_de_escritura_real": len(window), "aceptadas": len(accepted),
                                                                           "primeras_muestras": window[:3], "ultima_muestra": window[-1]},''')
a = s.index('    ex = d["antiguo_escritor_reiniciado_tras_sanar_la_red"]')
b = s.index("    # B3: el aislamiento NO se puede confirmar")
s = s[:a] + '''    ex = d["antiguo_escritor_reiniciado_tras_sanar_la_red_SIN_monitor"]
    check("B2 el antiguo escritor que REAPARECE (contenedor reiniciado y red restablecida, con el monitor detenido) arranca cerrado y rechaza TODA escritura real directa, también con intento de anular el solo-lectura",
          "modo fenced" in ex["arranque"] and ex["aceptadas"] == 0 and ex["intentos_de_escritura_real"] >= 20, ex)
    fl_ev = [e for e in events(log2) if e["ev"] == "fence_en_linea"] if (log2 := OUT / "eventos-B2.jsonl") else []
    fe = fl_ev[0] if fl_ev else {}
    check("B2 el aislamiento EN LÍNEA del escritor particionado se verificó por efecto (pg_hba nuevo, sesiones terminadas, escritura real y escritura con anulación rechazadas) antes de detenerlo",
          bool(fe) and fe.get("verificado") is True and fe.get("escritura_real_conexion_nueva_aceptada") is False and fe.get("escritura_real_con_anulacion_aceptada") is False, {k: fe.get(k) for k in ("verificado", "modo_cerrado", "solo_lectura_global", "sesiones_app_terminadas", "rechazo_conexion_nueva", "rechazo_con_anulacion")})

''' + s[b:]
s = s.replace('''and d["escritura_real_por_pasarela_de_BD_de_app-aws_llega_a"]["atendida_por_pg-oci"],''','''and d["escritura_real_por_pasarela_de_BD_de_app-aws_llega_a"]["atendida_por_pg-oci"],''')

# ---- B4 y B5 al final de stage_b
marker = "# ================================================================== ETAPA C"
extra = '''    # B4: default_transaction_read_only NO es fencing: la propia aplicación puede anularlo; el pg_hba cerrado sí lo impide
    fresh_lab("B4")
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

    # B5: arranque cerrado ante la duda: el escritor legítimo reinicia con el witness caído y NO abre el acceso (se sacrifica disponibilidad, no seguridad)
    fresh_lab("B5")
    run("docker", "stop", "-t", "1", L.cname("witness"))
    stop_monitor()
    run("docker", "restart", "-t", "1", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    ok5, e5 = L.app_connect("pg-aws", write=True)
    line5 = next((l for l in reversed(run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    run("docker", "start", L.cname("witness"))
    wait_until(lambda: L.w_req("GET", "/state")[0] == 200, 30)
    run("docker", "restart", "-t", "1", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    ok5b, e5b = L.app_connect("pg-aws", write=True)
    line5b = next((l for l in reversed(run("docker", "logs", "--tail", "40", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    DATA["B5"] = {"con_witness_caido": {"arranque": line5, "escritura_real_aceptada": ok5, "error": e5}, "con_witness_vivo_y_me_declara_escritor": {"arranque": line5b, "escritura_real_aceptada": ok5b}}
    check("B5 el escritor legítimo que reinicia con el witness caído arranca CERRADO (falla cerrada: sin escrituras); con el witness disponible y declarándolo escritor, abre",
          "modo fenced" in line5 and not ok5 and "modo open" in line5b and ok5b, DATA["B5"])


'''
s = s.replace(marker, extra + marker, 1) if extra.strip() not in s else s
p.write_text(s)
print("repl_test.py actualizado")
