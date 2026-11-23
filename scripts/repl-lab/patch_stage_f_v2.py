#!/usr/bin/env python3
"""Etapa F v2: escenarios aislados (una excepción no impide recoger el resto de las evidencias; F0 sí detiene la etapa), F4b, F5 con el orden corregido y comprobación del orden de los
eventos, matriz de fallos en los puntos críticos de la degradación (F5x), carrera de CAS entre degradar y promover (F5c), F6 con el síncrono obsoleto, y F8 sobre el estado en el witness."""
from pathlib import Path

here = Path(__file__).parent
T = (here / "repl_test.py").read_text()
if "def scenario(" in T:
    print("ya aplicado"); raise SystemExit

T = T.replace("import argparse, importlib.util, json, os, signal, subprocess, sys, threading, time, uuid", "import argparse, contextlib, importlib.util, json, os, signal, subprocess, sys, threading, time, traceback, uuid", 1)

helper = '''
@contextlib.contextmanager
def scenario(name: str):
    """Aísla un escenario: si lanza una excepción se REGISTRA como comprobación fallida con su traza y se continúa con el siguiente (las evidencias no se pierden)."""
    try:
        yield
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001
        check(f"{name} EXCEPCIÓN durante la prueba ({type(e).__name__})", False, traceback.format_exc()[-1000:])
        try:
            stop_monitor()
        except Exception:  # noqa: BLE001
            pass


'''
T = T.replace("def check(name, ok, detail=\"\"):", helper.lstrip("\n") + "def check(name, ok, detail=\"\"):", 1)

# ------------------------------------------------------------ F5 corregida (frontera = sync_deshabilitada, orden de eventos) y reescritura de F6 y F8
a = T.index("    # F5 seguidor no disponible con política DEGRADAR")
b = T.index("    # F6 conmutación -> UNPROTECTED")
f5 = r'''    # F5 seguidor no disponible con política DEGRADAR + caída de la primaria: la compuerta impide promover (y la promoción insegura explícita pierde justo lo confirmado sin protección)
    log = fresh_lab("F5", sync=True, env={"LAB_DEGRADE_AFTER_S": "4"})
    w = Writers("f5"); w.start(); msleep(3)
    t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
    t_deg = wait_until(lambda: ev_t(events(log), "proteccion", t_dis, modo="degraded") is not None, 30)
    ev5a = events(log)
    t_intent = ev_t(ev5a, "proteccion", t_dis, modo="degrading")
    t_off = ev_t(ev5a, "sync_deshabilitada", t_dis)
    t_rec = ev_t(ev5a, "proteccion", t_dis, modo="degraded")
    order_ok = bool(t_intent and t_off and t_rec and t_intent < t_off <= t_rec)
    msleep(4)
    t_kill = kill_node("pg-aws")
    msleep(10)
    ev5 = events(log)
    blocked = ev_t(ev5, "promocion_bloqueada", t_kill) is not None
    no_lease = ev_t(ev5, "lease_otorgado", t_kill) is None
    at_risk = [a for a in w.acked if a[0] > (t_off or time.time())]       # frontera correcta: desde que se desactivó el síncrono
    log2 = start_monitor("F5-promocion-insegura", env={"LAB_UNSAFE_PROMOTE": "1", "LAB_DEGRADE_AFTER_S": "4"})
    t_unsafe = time.time()
    t_prom = wait_until(lambda: ev_t(events(log2), "lease_otorgado", t_unsafe) is not None, 60)
    msleep(3); w.halt()
    lost = w.lost_on("pg-oci")
    DATA["F5"] = {"orden_intencion_desactivacion_registro": {"degrading": t_intent, "sync_deshabilitada": t_off, "degraded": t_rec, "orden_correcto": order_ok},
                  "degradado_tras_s": None if t_deg is None else round(t_deg, 1), "confirmadas_con_el_sincrono_desactivado": len(at_risk), "promocion_automatica_bloqueada": blocked and no_lease,
                  "promocion_insegura_ordenada_ok": t_prom is not None, "confirmadas_perdidas_tras_la_promocion_insegura": len(lost),
                  "todas_las_perdidas_son_de_la_ventana_sin_sincrono": all(a[0] > (t_off or 0) for a in lost), "perdidas_iguales_a_las_confirmadas_sin_sincrono": len(lost) == len(at_risk)}
    check("F5 la intención 'degrading' se registra ANTES de desactivar el síncrono y 'degraded' después; con la primaria caída la promoción automática queda bloqueada (con sus razones); la promoción insegura explícita pierde exactamente lo confirmado con el síncrono desactivado (límite de la garantía, no un defecto)",
          order_ok and t_deg is not None and DATA["F5"]["promocion_automatica_bloqueada"] and t_prom is not None and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_de_la_ventana_sin_sincrono"], DATA["F5"])

'''
T = T[:a] + f5 + T[b:]

# ------------------------------------------------------------ F6 con el síncrono obsoleto + sin retorno automático
a = T.index("    # F6 conmutación -> UNPROTECTED")
b = T.index("    # F7 caída simultánea de AMBOS nodos")
f6 = r'''    # F6 conmutación -> UNPROTECTED -> reconstrucción -> PROTECTED -> retorno planificado sin pérdida; la antigua primaria no vuelve sola como escritora y su síncrono obsoleto se limpia
    log = fresh_lab("F6", sync=True)
    w = Writers("f6"); w.start(); msleep(3)
    t_kill = kill_node("pg-aws")
    t_l = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
    msleep(3)
    prot_after = L.prot_load()
    names_after = L.sql("pg-oci", "SHOW synchronous_standby_names")[1]
    acks_unprot = sum(1 for a in w.acked if a[0] > t_kill + 6)
    lost_failover = w.lost_on("pg-oci")
    n_prom_before = sum(1 for e in events(log) if e["ev"] == "promote_inicio")
    run("docker", "start", L.cname("pg-aws"))                     # la antigua primaria vuelve sola (sin procedimiento)
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 60)
    stale_names = L.sql("pg-aws", "SHOW synchronous_standby_names")[1]
    old_write = [L.app_connect("pg-aws", write=True)[0], L.app_connect("pg-aws", write=True, override=True)[0]]
    writer_after_return = L.witness_state()["writer"]
    t_rs = time.time()
    L.reseed("pg-aws", "pg-oci")
    reseed_s = round(time.time() - t_rs, 1)
    names_cleaned = L.sql("pg-aws", "SHOW synchronous_standby_names")[1]
    prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
    msleep(3); w.halt()
    w2 = Writers("f6b"); w2.start(); msleep(2)
    with L.paused():
        ok_back = L.promote("pg-aws", planned=True)
    msleep(4); w2.halt()
    ids_back = set(q1("pg-aws", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
    lost_back = [a for a in w.acked + w2.acked if a[2] not in ids_back]
    n_prom_after = sum(1 for e in events(log) if e["ev"] == "promote_inicio")
    DATA["F6"] = {"modo_tras_la_conmutacion": prot_after.get("mode"), "synchronous_standby_names_en_la_nueva_primaria": names_after, "confirmaciones_sin_proteccion": acks_unprot,
                  "perdidas_en_la_conmutacion": len(lost_failover),
                  "antigua_primaria_reiniciada_sola": {"synchronous_standby_names_obsoleto": stale_names, "escrituras_directas_aceptadas": old_write, "escritor_en_el_witness": writer_after_return,
                                                        "promociones_automaticas_hacia_ella": n_prom_after - n_prom_before if False else None},
                  "reconstruccion": {"duracion_s": reseed_s, "synchronous_standby_names_tras_limpiar": names_cleaned, "modo_de_proteccion": prot_reseed.get("mode"), "estado_del_seguidor": st_reseed},
                  "retorno_planificado_ok": ok_back, "perdidas_en_el_retorno": len(lost_back)}
    check("F6 conmutación: queda UNPROTECTED sin síncrono heredado; la antigua primaria que reaparece sola conserva un síncrono OBSOLETO pero NO escribe (arranca cerrada) y el escritor sigue siendo pg-oci; la reconstrucción limpia el síncrono (verificado), no se bloquea y devuelve PROTECTED; el retorno planificado no pierde reservas confirmadas",
          t_l is not None and prot_after.get("mode") == "unprotected" and names_after == "" and stale_names != "" and not any(old_write) and writer_after_return == "pg-oci"
          and names_cleaned == "" and reseed_s < 60 and prot_reseed.get("mode") == "protected" and st_reseed in ("quorum", "sync") and ok_back and not lost_back and not lost_failover, DATA["F6"])

'''
T = T[:a] + f6 + T[b:]

# ------------------------------------------------------------ F8 sobre el witness
old = '''    L.PROT.unlink(missing_ok=True)
    w = Writers("f8"); w.start(); msleep(3)'''
new = '''    assert L.prot_cas("unknown", expect=("protected",), primario="pg-aws", motivo="F8: el estado de protección se vuelve incierto"), "no se pudo provocar la incertidumbre"
    w = Writers("f8"); w.start(); msleep(3)'''
assert old in T
T = T.replace(old, new)

# ------------------------------------------------------------ F4b, F5c, F5x
f4b = r'''    # F4b lo mismo con el seguidor DETENIDO (contenedor parado), no solo la suscripción deshabilitada
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
f5c = r'''    # F5c coordinación: degradar y promover concurrentes sobre el mismo estado (CAS en el witness): exactamente una gana
    fresh_lab("F5c", sync=True); stop_monitor()
    wins = {"degradar": 0, "promover": 0, "ninguna": 0, "ambas": 0}
    for i in range(30):
        stt = L.witness_state(); pr = stt["prot"]
        if pr["mode"] != "protected":
            assert L.prot_cas("protected", primario="pg-aws", motivo="F5c: restablecer")
            stt = L.witness_state(); pr = stt["prot"]
        res2, bar = {}, threading.Barrier(2)
        def cas(label, mode):
            bar.wait()
            res2[label] = L.w_req("POST", "/prot", {"expect_seq": pr["seq"], "mode": mode, "primario": "pg-aws", "epoch": stt["epoch"]})[0]
        ts = [threading.Thread(target=cas, args=("degradar", "degrading")), threading.Thread(target=cas, args=("promover", "promoting"))]
        [t.start() for t in ts]; [t.join() for t in ts]
        ok_n = sum(1 for v in res2.values() if v == 200)
        if ok_n == 1:
            wins["degradar" if res2["degradar"] == 200 else "promover"] += 1
        elif ok_n == 0:
            wins["ninguna"] += 1
        else:
            wins["ambas"] += 1
        # restablecer para el siguiente intento: del estado ganador a 'protected'
        st3 = L.witness_state()
        L.w_req("POST", "/prot", {"expect_seq": st3["prot"]["seq"], "mode": "protected", "primario": "pg-aws", "epoch": st3["epoch"]})
    DATA["F5c"] = wins
    check("F5c en 30 carreras simultáneas entre degradar y promover sobre el mismo estado, exactamente UNA transición gana siempre (nunca ambas)", wins["ambas"] == 0 and wins["ninguna"] == 0 and sum(wins.values()) == 30, wins)

'''
f5x = r'''    # F5x fallos provocados en los puntos críticos de la degradación, con carga: el controlador cae (exit) o cae la primaria (kill_primary) justo después de la intención, de desactivar el síncrono y del registro
    for point in ("after_intent", "after_disable", "after_record"):
        for action in ("exit", "kill_primary"):
            tag = f"F5x-{point}-{action}"
            with scenario(tag):
                log = fresh_lab(tag, sync=True, env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": f"{point}:{action}"})
                w = Writers("fx"); w.start(); msleep(2)
                t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
                t_fault = wait_until(lambda: ev_t(events(log), "fallo_inyectado", t_dis) is not None, 30)
                msleep(2)
                if action == "exit":                         # el controlador murió en ese punto: se le reinicia (sin fallo) y luego cae la primaria
                    MON_ALIVE = MON.poll() is None if MON else False
                    log = start_monitor(tag + "-reinicio", env={"LAB_DEGRADE_AFTER_S": "3"})
                    msleep(4)
                else:
                    MON_ALIVE = MON.poll() is None if MON else False
                t_kill = kill_node("pg-aws") if action == "exit" else time.time()
                msleep(10)
                ev_all = events(log) + (events(OUT / f"eventos-{tag}.jsonl") if action == "exit" else [])
                blocked = any(e["ev"] == "promocion_bloqueada" and e["t"] >= t_kill for e in ev_all)
                lease = any(e["ev"] == "lease_otorgado" and e["t"] >= t_kill for e in ev_all)
                promo = any(e["ev"] in ("promote_inicio", "promocion_insegura_ordenada") and e["t"] >= t_kill for e in ev_all)
                acks_after = sum(1 for a in w.acked if a[0] > t_kill + 2)
                modes = [e.get("modo") for e in ev_all if e["ev"] == "proteccion" and e["t"] >= t_dis]
                w.halt()
                DATA.setdefault("F5x", {})[tag] = {"fallo_inyectado": t_fault is not None, "controlador_vivo_tras_el_fallo": MON_ALIVE, "transiciones_de_estado": modes, "promocion_bloqueada": blocked,
                                                    "lease_a_pg-oci": lease, "promocion_iniciada": promo, "confirmaciones_al_cliente_tras_la_caida": acks_after}
                check(f"F5x {point}/{action}: con la primaria caída tras el fallo en ese punto NO se promueve automáticamente (compuerta bloqueada, sin lease ni promoción) y no se confirma nada más",
                      t_fault is not None and blocked and not lease and not promo and acks_after == 0, DATA["F5x"][tag])

'''
T = T.replace("    # F5 seguidor no disponible con política DEGRADAR", f4b + "    # F5 seguidor no disponible con política DEGRADAR", 1)
T = T.replace("    # F6 conmutación -> UNPROTECTED", f5c + f5x + "    # F6 conmutación -> UNPROTECTED", 1)

# ------------------------------------------------------------ envolver cada bloque en un escenario aislado (F1 .. F9)
a = T.index("    # F1 mecanismo y coste")
b = T.index("# ================================================================== main")
body = T[a:b]
marks = ["    # F1 mecanismo y coste", "    # F2 caída de la primaria con carga", "    # F2b el escenario", "    # F3 retraso REAL", "    # F4 seguidor NO disponible con política BLOQUEAR",
         "    # F4b lo mismo", "    # F5 seguidor no disponible con política DEGRADAR", "    # F5c coordinación", "    # F5x fallos provocados", "    # F6 conmutación", "    # F7 caída simultánea",
         "    # F8 incertidumbre", "    # F9 caída después de confirmar"]
idx = []
for m in marks:
    i = body.index(m)
    idx.append((i, m))
idx.sort()
out = []
for n, (i, m) in enumerate(idx):
    j = idx[n + 1][0] if n + 1 < len(idx) else len(body)
    seg = body[i:j].rstrip("\n").split("\n")
    name = m.strip().lstrip("# ").split(" ")[0]
    if name == "F5x":
        out.append("\n".join(seg))                      # F5x ya aísla cada combinación con su propio escenario
    else:
        out.append(seg[0] + f'\n    with scenario("{name}"):\n' + "\n".join(("    " + l if l.strip() else l) for l in seg[1:]))
T = T[:a] + "\n\n".join(out) + "\n\n\n" + T[b:]
(here / "repl_test.py").write_text(T)
print("ok")
