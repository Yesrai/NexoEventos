#!/usr/bin/env python3
"""Reescribe el aislamiento (fencing) de labctl.py en capas verificables. Cada operación se ejecuta por separado y se comprueba su efecto real."""
from pathlib import Path

p = Path(__file__).with_name("labctl.py")
s = p.read_text()

# ---------------------------------------------------------------- nuevas utilidades + fence en capas
a = s.index("def fence(node: str) -> bool:")
b = s.index("def promote(target: str, planned=False) -> bool:")
new_fence = '''HBA_PATH = "/var/lib/postgresql/lab-hba.conf"
HBA_TEXT = {"open": "local all all trust\\nhost all all 127.0.0.1/32 trust\\nhost all all ::1/128 trust\\nhost all all all scram-sha-256\\n",
            "fenced": "local all all trust\\nhost all all all reject\\n"}


def app_connect(node: str, *, write=False, override=False, origin: str | None = None) -> tuple[bool, str]:
    """Conexión NUEVA por TCP con el rol de la aplicación. write=True intenta una escritura real; override=True intenta además anular el solo-lectura
    desde la propia sesión (PGOPTIONS, SET y BEGIN READ WRITE), que es lo que podría hacer una aplicación con permisos normales."""
    o = origin or (other(node) if running(cname(other(node))) else node)
    ins = f"INSERT INTO lab_probe(node) VALUES ('{node}')"
    if override:
        q = f"SET default_transaction_read_only = off; BEGIN READ WRITE; {ins}; COMMIT"
    elif write:
        q = ins
    else:
        q = "SELECT 1"
    cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={APP_PW}", "-e", "PGCONNECT_TIMEOUT=2"]
    if override:
        cmd += ["-e", "PGOPTIONS=-c default_transaction_read_only=off"]
    cmd += [cname(o), "psql", "-X", "-q", "-U", "nexoeventos_app", "-d", "nexoeventos", "-h", node, "-tA", "-v", "ON_ERROR_STOP=1", "-c", q]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1][:200]
    except subprocess.TimeoutExpired:
        return False, "tiempo de espera agotado"


def set_mode(node: str, mode: str) -> dict:
    """Cambia el pg_hba del nodo (archivo en su volumen: sobrevive a reinicios) y COMPRUEBA el efecto con una conexión nueva de la aplicación."""
    steps: dict = {"modo": mode}
    try:
        r = subprocess.run(["docker", "exec", "-i", "-u", "postgres", cname(node), "sh", "-c", f"cat > {HBA_PATH}"], input=HBA_TEXT[mode], capture_output=True, text=True, timeout=10)
        steps["escribir_hba"] = r.returncode == 0
    except Exception as e:  # noqa: BLE001 - se registra, no se oculta
        steps["escribir_hba"] = False; steps["error"] = type(e).__name__
    rc, out, err = sql(node, "SELECT pg_reload_conf()")
    steps["recargar"] = rc == 0 and out == "t"
    want_reject = mode == "fenced"
    eff, msg = False, ""
    for _ in range(12):
        ok, msg = app_connect(node, origin=node)
        if (want_reject and not ok and "pg_hba.conf rejects" in msg) or (not want_reject and ok):
            eff = True; break
        time.sleep(0.25)
    steps["efecto_en_conexion_nueva"] = eff
    steps["mensaje_de_la_conexion_nueva"] = msg
    return steps


def set_readonly_global(node: str, on: bool) -> bool:
    """ALTER SYSTEM, recarga y comprobación del valor efectivo, como tres operaciones separadas (ALTER SYSTEM no admite bloque de transacción)."""
    want = "on" if on else "off"
    rc1, _, e1 = sql(node, f"ALTER SYSTEM SET default_transaction_read_only = {want}")
    rc2, out2, e2 = sql(node, "SELECT pg_reload_conf()")
    if rc1 != 0 or rc2 != 0:
        log("operacion_fallida", donde="set_readonly_global", nodo=node, alter_system=e1[-120:], reload=e2[-120:])
        return False
    for _ in range(12):
        if sql(node, "SHOW default_transaction_read_only")[1] == want:
            return True
        time.sleep(0.25)
    return False


def terminate_app_sessions(node: str) -> bool:
    rc, _, err = sql(node, "SELECT count(*) FROM (SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='nexoeventos_app') x")
    if rc != 0:
        log("operacion_fallida", donde="terminate_app_sessions", nodo=node, error=err[-120:]); return False
    for _ in range(12):
        rc, left, _ = sql(node, "SELECT count(*) FROM pg_stat_activity WHERE usename='nexoeventos_app'")
        if rc == 0 and left == "0":
            return True
        time.sleep(0.25)
    return False


def fence(node: str) -> bool:
    """Aísla `node` en capas y COMPRUEBA con intentos reales de escritura directa (conexión nueva, y con intento de anular el solo-lectura).
    Devuelve True solo si el nodo queda detenido o rechazando toda escritura; si no, el estado se registra como INSEGURO y no se promueve."""
    if os.environ.get("LAB_FENCE_FAIL") == "1":
        log("fence", nodo=node, resultado="inyectado: no se puede confirmar el aislamiento")
        return False
    if running(cname(node)):
        d = {"modo_cerrado": set_mode(node, "fenced"), "solo_lectura_global": set_readonly_global(node, True), "sesiones_app_terminadas": terminate_app_sessions(node)}
        w_ok, w_err = app_connect(node, write=True, origin=node)
        o_ok, o_err = app_connect(node, write=True, override=True, origin=node)
        d.update(escritura_real_conexion_nueva_aceptada=w_ok, escritura_real_con_anulacion_aceptada=o_ok, rechazo_conexion_nueva=w_err, rechazo_con_anulacion=o_err)
        verified = d["modo_cerrado"].get("efecto_en_conexion_nueva") and d["sesiones_app_terminadas"] and not w_ok and not o_ok
        log("fence_en_linea", nodo=node, verificado=bool(verified), **d)
        if not verified:
            log("estado_inseguro", nodo=node, motivo="el aislamiento en línea no se pudo verificar; se intenta detener el contenedor")
    subprocess.run(["docker", "stop", "-t", "1", cname(node)], capture_output=True, text=True)
    stopped = not running(cname(node))
    ok, err = app_connect(node, write=True)
    confirmed = stopped and not ok
    log("fence", nodo=node, detenido=stopped, escritura_real_aceptada=ok, escritura_real_error=err, resultado="confirmado" if confirmed else "NO confirmado")
    if not confirmed:
        log("estado_inseguro", nodo=node, motivo="el nodo sigue en ejecución o acepta escrituras: NO se promueve a otro escritor")
    return confirmed


'''
s = s[:a] + new_fence + s[b:]

# ---------------------------------------------------------------- promote: abrir el destino con comprobación de efecto
old = '''    sql(target, "ALTER ROLE nexoeventos_app RESET default_transaction_read_only; SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='nexoeventos_app'")
    ok, err = probe_write(target)                        # 5) escritura real en el destino ANTES de dar el lease'''
new = '''    rc_r, _, e_r = sql(target, "ALTER ROLE nexoeventos_app RESET default_transaction_read_only")
    ro_off = set_readonly_global(target, False)
    opened = set_mode(target, "open")
    terminate_app_sessions(target)
    log("destino_abierto", rol_sin_solo_lectura=rc_r == 0, solo_lectura_global_apagado=ro_off, modo_abierto=opened)
    if rc_r != 0 or not ro_off or not opened.get("efecto_en_conexion_nueva"):
        log("promote_abortada", motivo="no se pudo abrir el destino con efecto comprobado", epoca=epoch)
        return False
    ok, err = probe_write(target)                        # 5) escritura real en el destino ANTES de dar el lease'''
assert old in s
s = s.replace(old, new)

# ---------------------------------------------------------------- monitor: guardia secundaria con el mismo mecanismo
a = s.index("    w = st.get(\"writer\")\n    if w in NODES and running(cname(other(w))) and t - S[\"guard\"] > 1.5:")
b = s.index("    if w in NODES:\n        ok, err = probe_write(w)")
guard = '''    w = st.get("writer")
    if w in NODES and running(cname(other(w))) and t - S["guard"] > 1.5:
        S["guard"] = t       # defensa secundaria: el otro nodo está en marcha; si acepta conexiones de la aplicación, está EXPUESTO y se le aísla
        f = other(w)
        exp_ok, _ = app_connect(f, origin=f)
        if exp_ok:
            t_a = time.time()
            log("nodo_no_escritor_expuesto", nodo=f, accion="aislar en línea y verificar con escrituras reales")
            d = {"modo_cerrado": set_mode(f, "fenced"), "sesiones_app_terminadas": terminate_app_sessions(f)}
            w_ok, w_err = app_connect(f, write=True, origin=f)
            o_ok, _ = app_connect(f, write=True, override=True, origin=f)
            if w_ok or o_ok or not d["modo_cerrado"].get("efecto_en_conexion_nueva"):
                subprocess.run(["docker", "stop", "-t", "1", cname(f)], capture_output=True, text=True)
                log("estado_inseguro", nodo=f, motivo="el aislamiento en línea no funcionó; se detuvo el contenedor", detenido=not running(cname(f)))
            else:
                log("nodo_no_escritor_aislado", nodo=f, t_aislamiento_s=round(time.time() - t_a, 2), escritura_real_aceptada_despues=False, **d)
'''
s = s[:a] + guard + s[b:]

# ---------------------------------------------------------------- setup: el seguidor nace cerrado
old = '''    witness_set("pg-aws", st["epoch"])
    dc("up", "-d", "app-aws", "app-oci", "haproxy-db-aws", "haproxy-db-oci", "haproxy-edge")'''
new = '''    witness_set("pg-aws", st["epoch"])
    fm = set_mode("pg-oci", "fenced")
    om = set_mode("pg-aws", "open")
    log("setup", paso="modos de acceso", pg_oci=fm, pg_aws=om)
    assert fm["efecto_en_conexion_nueva"] and om["efecto_en_conexion_nueva"], "el modo de acceso inicial no tuvo efecto"
    dc("up", "-d", "app-aws", "app-oci", "haproxy-db-aws", "haproxy-db-oci", "haproxy-edge")'''
assert old in s
s = s.replace(old, new)

# ---------------------------------------------------------------- orphans / reseed: ALTER SYSTEM por separado y comprobado
old = '''    sql(old, "ALTER SYSTEM SET default_transaction_read_only = on; SELECT pg_reload_conf()")
    log("antigua_primaria_en_solo_lectura", nodo=old, escritura_real_aceptada=probe_write(old)[0])'''
new = '''    ro = set_readonly_global(old, True)
    w_ok, w_err = app_connect(old, write=True, origin=old)
    o_ok, _ = app_connect(old, write=True, override=True, origin=old)
    log("antigua_primaria_al_volver", nodo=old, solo_lectura_global=ro, escritura_real_aceptada=w_ok, escritura_real_con_anulacion_aceptada=o_ok, rechazo=w_err)'''
assert old in s
s = s.replace(old, new)
old = '''    sql(node, "ALTER SYSTEM RESET default_transaction_read_only; SELECT pg_reload_conf()")
    tabs = published_tables(src)'''
new = '''    assert set_readonly_global(node, False), "no se pudo quitar el solo-lectura global para reconstruir el nodo"
    tabs = published_tables(src)'''
assert old in s
s = s.replace(old, new)
old = '''    sql(node, "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='nexoeventos_app'")
    s = SHORT[node]'''
new = '''    terminate_app_sessions(node)
    log("reseed_modo", nodo=node, **set_mode(node, "fenced"))
    s = SHORT[node]'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("labctl.py actualizado")
