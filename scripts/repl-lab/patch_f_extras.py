#!/usr/bin/env python3
"""Añade a la etapa F: F0 (demostración de que el COMMIT espera la durabilidad en el 2.º nodo, vista desde la primaria; si falla se detiene la etapa), F2b (el escenario de 3 s que
perdió 328 reservas), F4b (seguidor detenido), F8 (promoción con incertidumbre), F9 (caída tras confirmar con replicación síncrona), métricas de latencia/reintentos, y
una compuerta de promoción más estricta (el registro de protección debe corresponder al escritor que cae)."""
from pathlib import Path

here = Path(__file__).parent
L = (here / "labctl.py").read_text()
old = '''                mode = prot_load().get("mode")
                if mode == "protected" or UNSAFE_PROMOTE or not sync_on():
                    if mode != "protected":
                        log("promocion_insegura_ordenada", modo=mode, aviso="las escrituras confirmadas sin protección pueden perderse")'''
new = '''                prot = prot_load()
                mode = prot.get("mode")
                consistent = mode == "protected" and prot.get("primario") == w      # registro ausente, desconocido o de otro nodo = incertidumbre => no se promueve
                if consistent or UNSAFE_PROMOTE or not sync_on():
                    if not consistent and sync_on():
                        log("promocion_insegura_ordenada", modo=mode, aviso="las escrituras confirmadas sin protección pueden perderse")'''
if old in L:
    L = L.replace(old, new)
    old2 = '''log("promocion_bloqueada", modo=mode, desde=prot_load().get("since"), motivo="hubo escrituras confirmadas sin seguidor síncrono: promover podría perderlas; se requiere decisión explícita (LAB_UNSAFE_PROMOTE=1)")'''
    new2 = '''log("promocion_bloqueada", modo=mode, primario_registrado=prot.get("primario"), escritor_que_cae=w, desde=prot.get("since"), motivo="no se puede comprobar que lo confirmado tenga copia síncrona (modo no protegido, registro ausente o que no corresponde al escritor): promover podría perder reservas; se requiere decisión explícita (LAB_UNSAFE_PROMOTE=1)")'''
    assert old2 in L
    L = L.replace(old2, new2)
    (here / "labctl.py").write_text(L)

T = (here / "repl_test.py").read_text()
if "def f0_precheck()" in T:
    print("ya aplicado"); raise SystemExit

# métricas de latencia y reintentos en crash_under_load
old = '''        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),
        "confirmaciones_al_cliente_durante_el_bloqueo_inducido"'''
new = '''        "latencia_de_confirmacion_ms_p50_antes_de_la_caida": _pct([te - t0 for t0, st, te in att if 200 <= st < 300 and t0 < t_kill], 0.5),
        "latencia_de_confirmacion_ms_p95_antes_de_la_caida": _pct([te - t0 for t0, st, te in att if 200 <= st < 300 and t0 < t_kill], 0.95),
        "intentos_no_exitosos_(reintentos_con_la_misma_clave)": sum(1 for t0, st, te in att if not 200 <= st < 300),
        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),
        "confirmaciones_al_cliente_durante_el_bloqueo_inducido"'''
assert old in T
T = T.replace(old, new, 1)

# after_commit con modo síncrono
old = "def after_commit(tag: str, induce: bool) -> dict:"
assert old in T
T = T.replace(old, "def after_commit(tag: str, induce: bool, sync: bool = False) -> dict:", 1)
T = T.replace('''    log = fresh_lab(tag)
    L.dc("up", "-d", "cut-proxy")''', '''    log = fresh_lab(tag, sync=sync)
    L.dc("up", "-d", "cut-proxy")''', 1)

f0 = r'''
def f0_precheck():
    """F0 · ¿es la replicación realmente síncrona desde la perspectiva de la primaria? Se demuestra con una transacción real: con el seguidor retenido por un bloqueo de tabla, el COMMIT
    debe esperar (wait_event SyncRep), y al volver debe existir la fila en el seguidor con flush_lsn >= LSN de la transacción; el control asíncrono NO espera. Si falla, se detiene la etapa."""
    fresh_lab("F0", sync=True)
    r = {}
    r["synchronous_standby_names"] = q1("pg-aws", "SHOW synchronous_standby_names")
    r["synchronous_commit_de_la_primaria"] = q1("pg-aws", "SHOW synchronous_commit")
    r["fsync_primaria_y_seguidor"] = [q1("pg-aws", "SHOW fsync"), q1("pg-oci", "SHOW fsync")]
    r["suscripcion"] = q1("pg-oci", "SELECT subname||' synchronous_commit='||subsynccommit||' habilitada='||subenabled FROM pg_subscription")
    r["pg_stat_replication"] = q1("pg-aws", "SELECT application_name||' | '||state||' | '||sync_state||' | sent='||sent_lsn||' write='||write_lsn||' flush='||flush_lsn||' replay='||replay_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")
    r["monitor_y_proteccion"] = L.prot_load().get("mode")
    script = ("BEGIN;\nINSERT INTO lab_bulk(payload) VALUES ('{p}') RETURNING id;\nSELECT 'LSN0='||pg_current_wal_insert_lsn();\nCOMMIT;\n")

    def trial(label):
        holder = subprocess.Popen(["docker", "exec", "-i", L.cname("pg-oci"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                                   "BEGIN; LOCK TABLE lab_bulk IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        box = {}
        def run_tx():
            t0 = time.time()
            rc, out, err = L.sql("pg-aws", script.format(p=label), stdin=script.format(p=label), timeout=30)
            box.update(rc=rc, out=out, dur=time.time() - t0)
        th = threading.Thread(target=run_tx); th.start()
        time.sleep(2.0)
        mid = {"commit_sigue_esperando": th.is_alive(),
               "wait_event_en_pg_stat_activity": q1("pg-aws", "SELECT coalesce(string_agg(wait_event_type||'/'||wait_event, ','),'(ninguno)') FROM pg_stat_activity WHERE wait_event='SyncRep'"),
               "fila_en_el_seguidor_mientras_espera": q1("pg-oci", f"SELECT count(*) FROM lab_bulk WHERE payload='{label}'") if False else "no consultable (tabla bloqueada)"}
        th.join(30); holder.wait(30)
        t_ret = time.time()
        lsn0 = next((l.split("=")[1] for l in box.get("out", "").splitlines() if l.startswith("LSN0=")), None)
        row = q1("pg-oci", f"SELECT count(*) FROM lab_bulk WHERE payload='{label}'")
        flush = q1("pg-aws", "SELECT flush_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")
        ok_lsn = q1("pg-aws", f"SELECT '{flush}'::pg_lsn >= '{lsn0}'::pg_lsn") if lsn0 and flush else None
        return {"duracion_del_commit_s": round(box.get("dur", 0), 2), "durante_la_espera": mid, "fila_en_el_seguidor_al_volver_el_commit": row, "LSN_de_la_transaccion": lsn0,
                "flush_lsn_confirmado_por_el_seguidor": flush, "flush_lsn_mayor_o_igual_que_el_LSN_de_la_transaccion": ok_lsn}

    r["COMMIT_SINCRONO_con_el_seguidor_retenido"] = trial("f0_sync")
    L.sync_names("pg-aws", "")
    r["CONTROL_ASINCRONO_con_el_seguidor_retenido"] = trial("f0_async")
    L.enable_sync("pg-aws")
    DATA["F0"] = r
    s, a = r["COMMIT_SINCRONO_con_el_seguidor_retenido"], r["CONTROL_ASINCRONO_con_el_seguidor_retenido"]
    ok = (r["synchronous_standby_names"] == "ANY 1 (sub_oci)" and r["synchronous_commit_de_la_primaria"] == "on" and "quorum" in r["pg_stat_replication"] and "synchronous_commit=on" in r["suscripcion"]
          and s["duracion_del_commit_s"] >= 2.5 and s["durante_la_espera"]["commit_sigue_esperando"] and "SyncRep" in s["durante_la_espera"]["wait_event_en_pg_stat_activity"]
          and s["fila_en_el_seguidor_al_volver_el_commit"] == "1" and s["flush_lsn_mayor_o_igual_que_el_LSN_de_la_transaccion"] == "t"
          and a["duracion_del_commit_s"] < 1.0 and a["fila_en_el_seguidor_al_volver_el_commit"] == "0")
    check("F0 la replicación es síncrona desde la primaria: ajustes y pg_stat_replication en quorum; con el seguidor retenido el COMMIT espera (SyncRep) hasta que la fila está en el seguidor con flush_lsn >= LSN de la transacción; el control asíncrono NO espera y la fila queda ausente",
          ok, r)
    if not ok:
        raise RuntimeError("F0 falló: la propiedad síncrona NO está demostrada; se detiene la etapa F (ver DATA['F0'])")

'''
T = T.replace("def stage_f():\n", f0 + "\ndef stage_f():\n", 1)
T = T.replace('    print("== F estrategia síncrona: protección de reservas confirmadas", flush=True)\n    # F1 mecanismo y coste\n    fresh_lab("F1", sync=True)',
              '    print("== F estrategia síncrona: protección de reservas confirmadas", flush=True)\n    f0_precheck()\n    # F1 mecanismo y coste\n    fresh_lab("F1", sync=True)', 1)

extras = r'''
    # F2b el escenario de 3 s de retraso que con replicación asíncrona perdió 328 reservas confirmadas
    d = crash_under_load("F2b-retraso-de-3s", induce_s=3.0, sync=True)
    DATA["F2b_comparacion"] = {"asincrona_corrida_final_C": "328 reservas confirmadas perdidas (ventana 3,0 s)", "sincrona_ahora": d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"],
                               "confirmaciones_durante_los_3_s": d["confirmaciones_al_cliente_durante_el_bloqueo_inducido"]}
    check("F2b el mismo escenario de 3 s (seguidor desconectado y caída de la primaria) con replicación síncrona: 0 reservas confirmadas ausentes (con asíncrona fueron 328)",
          d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["huerfanas_confirmadas_al_cliente_(perdidas)"] == 0, {k: d[k] for k in ("RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "errores_http_escritura", "RTO_escritura_s_desde_la_orden_de_caida")})
'''
T = T.replace("    # F3 retraso REAL de aplicación en el seguidor", extras.lstrip("\n") + "\n    # F3 retraso REAL de aplicación en el seguidor", 1)

f4b = r'''
    # F4b lo mismo con el seguidor DETENIDO (contenedor parado), no solo la suscripción deshabilitada
    log = fresh_lab("F4b", sync=True)
    w = Writers("f4b"); w.start(); msleep(3)
    t_st = time.time(); run("docker", "stop", "-t", "1", L.cname("pg-oci"))
    msleep(8)
    waiters_b = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
    acks_b = sum(1 for a in w.acked if a[0] > t_st + 0.7)
    promoted_b = ev_t(events(log), "promote_inicio", t_st)
    run("docker", "start", L.cname("pg-oci")); t_up = time.time()
    wait_until(lambda: L.sql("pg-oci", "SELECT 1")[0] == 0, 40)
    wait_until(lambda: L.standby_state("pg-aws") in ("quorum", "sync"), 40)
    msleep(5); w.halt()
    resumed_b = sum(1 for a in w.acked if a[0] > t_up + 5)
    DATA["F4b"] = {"commits_esperando_en_SyncRep": waiters_b, "confirmaciones_al_cliente_con_el_seguidor_detenido": acks_b, "promociones": promoted_b is not None,
                   "confirmaciones_tras_reiniciar_el_seguidor": resumed_b, "perdidas": len(w.lost_on("pg-aws")), "modo": L.prot_load().get("mode")}
    check("F4b con el seguidor detenido: los COMMIT esperan, 0 confirmaciones sin copia, no se promueve (la primaria vive), y al reiniciar el seguidor se reanuda sin pérdidas",
          int(waiters_b) > 0 and acks_b == 0 and promoted_b is None and resumed_b > 0 and DATA["F4b"]["perdidas"] == 0, DATA["F4b"])
'''
T = T.replace("    # F5 seguidor NO disponible con política DEGRADAR", f4b.lstrip("\n") + "\n    # F5 seguidor NO disponible con política DEGRADAR", 1)

f89 = r'''
    # F8 incertidumbre sobre la durabilidad (el controlador pierde su registro de protección) y cae la primaria: NO se promueve
    log = fresh_lab("F8", sync=True)
    L.PROT.unlink(missing_ok=True)
    w = Writers("f8"); w.start(); msleep(3)
    t_kill = kill_node("pg-aws")
    msleep(10)
    ev8 = events(log)
    blocked8 = ev_t(ev8, "promocion_bloqueada", t_kill) is not None
    lease8 = ev_t(ev8, "lease_otorgado", t_kill)
    acks_after = sum(1 for a in w.acked if a[0] > t_kill + 1.5)
    w.halt()
    DATA["F8"] = {"promocion_bloqueada": blocked8, "lease_otorgado": lease8 is not None, "confirmaciones_al_cliente_tras_la_caida": acks_after,
                  "motivo": next((e.get("motivo") for e in ev8 if e["ev"] == "promocion_bloqueada"), None)}
    check("F8 con incertidumbre sobre si lo confirmado tiene copia (registro de protección ausente) y la primaria caída: no se promueve, se registra el motivo y no se confirma nada más (falla segura)",
          blocked8 and lease8 is None and acks_after == 0, DATA["F8"])

    # F9 caída después de confirmar y antes de responder, con replicación síncrona
    d9 = after_commit("F9a-sync-tras-confirmar", induce=False, sync=True)
    check("F9a con replicación síncrona, la respuesta HTTP solo existe si la reserva ya está en el seguidor: tras la caída, el reintento con la misma clave devuelve la MISMA reserva (200) y no hay duplicado",
          d9["replicada_antes_de_caer"] and d9["estado_final"] == 200 and d9["misma_reserva"] and d9["reservas_con_esa_clave_en_la_nueva_primaria"] == "1", d9)
    log = fresh_lab("F9b", sync=True)
    L.dc("up", "-d", "cut-proxy")
    wait_until(lambda: fl.req(("127.0.0.1", 18091), "GET", "/held", timeout=2)[0] == 200, 30)
    ub = new_user("cb", addr=("127.0.0.1", 18090))
    Kb = uuid.uuid4().hex
    sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
    outb = {}
    def send_b():
        try:
            outb["r"] = ub._do("POST", f"/api/events/{EV_GENERAL}/reservations", {"quantity": 1}, {"Idempotency-Key": Kb}, ("127.0.0.1", 18090), timeout=40)
        except Exception as e:
            outb["exc"] = type(e).__name__
    thb = threading.Thread(target=send_b); thb.start()
    waiting = wait_until(lambda: int(L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]) >= 1, 20)
    t_kill = kill_node("pg-aws")
    thb.join(45)
    ub.addr = ("127.0.0.1", 18080)
    finalb, triesb = None, []
    for _ in range(80):
        try:
            stb, jsb, _s = ub.reserve(EV_GENERAL, {"quantity": 1}, Kb, timeout=3)
            triesb.append(stb)
            if stb < 500:
                finalb = (stb, jsb); break
        except Exception as e:
            triesb.append(type(e).__name__)
        time.sleep(0.25)
    wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
    sumb = L.orphans("pg-aws", "pg-oci", str(OUT / "huerfanas-F9b"))
    DATA["F9b"] = {"commit_esperando_al_seguidor_cuando_cayo_la_primaria": waiting is not None, "cliente_recibio_respuesta_original": "r" in outb and outb["r"][0] < 500,
                   "reintento_con_la_misma_clave": None if not finalb else finalb[0], "reintento_replayed": None if not finalb else finalb[1].get("replayed"),
                   "huerfanas_en_la_antigua_primaria": sumb["tablas_con_huerfanas"], "duplicados_logicos": sumb["duplicados_logicos_por_idempotency_key"], "Idempotency_Key": Kb}
    check("F9b caída con el COMMIT esperando al seguidor: el cliente NO recibió confirmación; el reintento crea la reserva en la nueva primaria (201); la fila de la antigua es una transacción INCIERTA (huérfana, duplicado lógico detectado), nunca una confirmación perdida",
          waiting is not None and not DATA["F9b"]["cliente_recibio_respuesta_original"] and finalb and finalb[0] == 201 and any(x["idempotency_key"] == Kb for x in sumb["duplicados_logicos_por_idempotency_key"]), DATA["F9b"])
'''
T = T.replace("\n    # F6 conmutación -> UNPROTECTED", f89.rstrip("\n") + "\n\n    # F6 conmutación -> UNPROTECTED", 1) if False else T
# F8/F9 al final de stage_f (tras F7)
T = T.rstrip("\n") + "\n"
marker = '    check("F7 caída simultánea de ambos nodos'
idx = T.index(marker)
end = T.index("\n", T.index("len(lost7) == 0 and len(w.acked) > 0, DATA[\"F7\"])", idx)) + 1
T = T[:end] + f89.lstrip("\n") + T[end:]
(here / "repl_test.py").write_text(T)
print("ok")
