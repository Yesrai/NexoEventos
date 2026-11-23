#!/usr/bin/env python3
"""Prepara (SIN ejecutar) las pruebas de la estrategia síncrona: etapa F. Las etapas A-E siguen ejecutándose en modo asíncrono (LAB_SYNC=0) para que sus resultados sigan
siendo comparables; solo F usa sync=True."""
from pathlib import Path

here = Path(__file__).parent

# ------------------------------------------------------------------ labctl: la estrategia se aplica solo si LAB_SYNC=1 (se lee en cada llamada)
L = (here / "labctl.py").read_text()
if "def sync_on()" not in L:
    L = L.replace("def prot_load() -> dict:", 'def sync_on() -> bool:\n    return os.environ.get("LAB_SYNC", "1") == "1"\n\n\ndef prot_load() -> dict:', 1)
    L = L.replace('    if os.environ.get("LAB_SYNC", "1") == "1":\n        assert enable_sync("pg-aws")', "    if sync_on():\n        assert enable_sync(\"pg-aws\")")
    L = L.replace('    if os.environ.get("LAB_SYNC", "1") == "1":\n        if not reprotect(src):', "    if sync_on():\n        if not reprotect(src):")
    L = L.replace('                if mode == "protected" or UNSAFE_PROMOTE:', '                if mode == "protected" or UNSAFE_PROMOTE or not sync_on():')
    L = L.replace('            _supervise_standby(S, w, auto)', '            if sync_on():\n                _supervise_standby(S, w, auto)')
    (here / "labctl.py").write_text(L)

# ------------------------------------------------------------------ repl_test: modo por laboratorio
T = (here / "repl_test.py").read_text()
if "def stage_f()" not in T:
    T = T.replace("def fresh_lab(tag: str, monitor=True, env=None):", "def fresh_lab(tag: str, monitor=True, env=None, sync=False):", 1)
    T = T.replace('''    stop_monitor()
    L.PAUSE.unlink(missing_ok=True)
    subprocess.run(["docker", "build"''', '''    stop_monitor()
    L.PAUSE.unlink(missing_ok=True)
    L.PROT.unlink(missing_ok=True)
    os.environ["LAB_SYNC"] = "1" if sync else "0"      # A-E: asíncrono (comparable con las corridas anteriores); F: síncrono
    subprocess.run(["docker", "build"''', 1)
    T = T.replace("def crash_under_load(tag: str, induce_s: float = 0.0) -> dict:\n    log = fresh_lab(tag)", "def crash_under_load(tag: str, induce_s: float = 0.0, sync: bool = False, hook=None, env=None) -> dict:\n    log = fresh_lab(tag, sync=sync, env=env)", 1)
    T = T.replace('''        t_dis = None
        if induce_s:
            sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE"); t_dis = time.time()
            time.sleep(induce_s)
        else:
            time.sleep(2)''', '''        t_dis = None; win = None
        if induce_s:
            sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE"); t_dis = time.time()
            time.sleep(induce_s)
        elif hook:
            win = hook()
        else:
            time.sleep(2)''', 1)
    T = T.replace('''        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),''', '''        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),
        "confirmaciones_al_cliente_durante_el_bloqueo_inducido": None if not win else sum(1 for a in acked if win[0] + 0.5 <= a[0] <= win[1]),''', 1)
    T = T.replace('    DATA.setdefault("C1", {})[tag] = d', '    DATA.setdefault("F2" if sync else "C1", {})[tag] = d', 1)

    stage_f = r'''

# ================================================================== ETAPA F (estrategia síncrona) — PREPARADA, no ejecutada hasta autorización
class Writers:
    """Clientes ficticios que reservan sin parar (una clave de idempotencia por intención, reintentos con la misma clave) y anotan cada confirmación 200/201."""
    def __init__(self, tag: str, n: int = 8):
        self.users = [new_user(f"{tag}{i}") for i in range(n)]
        self.acked, self.att, self.stop, self.ths = [], [], threading.Event(), []

    def _w(self, u):
        while not self.stop.is_set():
            key = uuid.uuid4().hex
            for _ in range(60):
                t0 = time.time()
                try:
                    st, js, srv = u.reserve(EV_GENERAL, {"quantity": 1}, key, timeout=3)
                    self.att.append((t0, st, time.time()))
                    if st in (200, 201):
                        self.acked.append((time.time(), key, js["reservation_id"], st)); break
                    if st < 500: break
                except Exception:
                    self.att.append((t0, 0, time.time()))
                if self.stop.is_set(): break
                time.sleep(0.25)
            time.sleep(0.05)

    def start(self):
        for u in self.users:
            t = threading.Thread(target=self._w, args=(u,), daemon=True); t.start(); self.ths.append(t)

    def halt(self):
        self.stop.set(); [t.join(20) for t in self.ths]

    def lost_on(self, node: str):
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in self.acked if a[2] not in ids]


def _pct(v, p):
    v = sorted(v); return round(1000 * v[min(len(v) - 1, int(len(v) * p))], 2) if v else None


def stage_f():
    print("== F estrategia síncrona: protección de reservas confirmadas", flush=True)
    # F1 mecanismo y coste
    fresh_lab("F1", sync=True)
    st0 = L.standby_state("pg-aws")
    u = new_user("f1")
    def timeit(n=150):
        lat = []
        for _ in range(n):
            t = time.time(); u.reserve(EV_GENERAL, {"quantity": 1}, uuid.uuid4().hex, timeout=5); lat.append(time.time() - t)
        return {"p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)}
    lat_sync = timeit()
    L.sync_names("pg-aws", ""); lat_async = timeit(); L.enable_sync("pg-aws")
    L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'off')"); time.sleep(1.5); lat_sub_off = timeit(30)
    L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'on')"); time.sleep(1.5)
    DATA["F1"] = {"estado_del_seguidor_en_pg_stat_replication": st0, "latencia_de_confirmacion_sincrona": lat_sync, "latencia_asincrona": lat_async,
                  "sincrona_con_suscripcion_synchronous_commit_off_(configuracion_incorrecta)": lat_sub_off}
    check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la opción synchronous_commit='on' de la suscripción es imprescindible (con 'off' cada confirmación es mucho más lenta)",
          st0 in ("quorum", "sync") and lat_sub_off["p50_ms"] > 3 * lat_sync["p50_ms"], DATA["F1"])

    # F2 caída de la primaria con carga y seguidor sano: ninguna reserva CONFIRMADA debe perderse (3 repeticiones)
    for i in range(1, 4):
        d = crash_under_load(f"F2-sync-{i}", sync=True)
        check(f"F2 {i}: con replicación síncrona y seguidor sano, 0 reservas confirmadas al cliente se pierden al caer la primaria (huérfanas inciertas: {d['huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)']})",
              d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["huerfanas_confirmadas_al_cliente_(perdidas)"] == 0,
              {k: d[k] for k in ("RTO_escritura_s_desde_la_orden_de_caida", "RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "errores_http_escritura", "escrituras_confirmadas_al_cliente")})

    # F3 retraso REAL de aplicación en el seguidor (bloqueo de la tabla): los COMMIT esperan, nada se confirma sin copia
    def lock_hook():
        t0 = time.time()
        subprocess.Popen(["docker", "exec", "-i", L.cname("pg-oci"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                          "BEGIN; LOCK TABLE reservations IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.5)
        return (t0, t0 + 2.5)
    d = crash_under_load("F3-retraso-de-aplicacion", sync=True, hook=lock_hook)
    check("F3 con la aplicación retrasada en el seguidor (tabla bloqueada) y caída de la primaria a mitad: 0 reservas confirmadas perdidas, y no hubo confirmaciones al cliente mientras duraba el bloqueo",
          d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["confirmaciones_al_cliente_durante_el_bloqueo_inducido"] == 0,
          {k: d[k] for k in ("RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "confirmaciones_al_cliente_durante_el_bloqueo_inducido", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "RTO_escritura_s_desde_la_orden_de_caida")})

    # F4 seguidor NO disponible con política BLOQUEAR (por defecto): los COMMIT esperan; no se confirma nada sin copia
    log = fresh_lab("F4", sync=True)
    w = Writers("f4"); w.start(); msleep(3)
    t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
    msleep(8)
    waiters = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
    acks_blocked = sum(1 for a in w.acked if a[0] > t_dis + 0.7)
    mode_blocked = L.prot_load().get("mode")
    promoted = ev_t(events(log), "promote_inicio", t_dis)
    L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE"); t_en = time.time()
    msleep(5); w.halt()
    resumed = sum(1 for a in w.acked if a[0] > t_en + 1)
    DATA["F4"] = {"commits_esperando_en_SyncRep": waiters, "confirmaciones_al_cliente_con_el_seguidor_caido": acks_blocked, "modo_de_proteccion": mode_blocked, "promociones": promoted is not None,
                  "confirmaciones_tras_volver_el_seguidor": resumed, "perdidas": len(w.lost_on("pg-aws"))}
    check("F4 con el seguidor no disponible y política BLOQUEAR: los COMMIT esperan (SyncRep), no se confirma nada al cliente, no se degrada ni se promueve (la primaria está viva) y al volver el seguidor se reanuda",
          int(waiters) > 0 and acks_blocked == 0 and mode_blocked == "protected" and promoted is None and resumed > 0 and DATA["F4"]["perdidas"] == 0, DATA["F4"])

    # F5 seguidor no disponible con política DEGRADAR + caída de la primaria: la compuerta impide promover (y la promoción insegura explícita pierde justo lo confirmado sin protección)
    log = fresh_lab("F5", sync=True, env={"LAB_DEGRADE_AFTER_S": "4"})
    w = Writers("f5"); w.start(); msleep(3)
    t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
    t_deg = wait_until(lambda: ev_t(events(log), "proteccion", t_dis, modo="degraded") is not None, 30)
    t_deg_wall = ev_t(events(log), "proteccion", t_dis, modo="degraded") or time.time()
    msleep(4)
    t_kill = kill_node("pg-aws")
    msleep(10)
    ev5 = events(log)
    blocked = ev_t(ev5, "promocion_bloqueada", t_kill) is not None
    no_lease = ev_t(ev5, "lease_otorgado", t_kill) is None
    at_risk = [a for a in w.acked if a[0] > t_deg_wall]
    log2 = start_monitor("F5-promocion-insegura", env={"LAB_UNSAFE_PROMOTE": "1", "LAB_DEGRADE_AFTER_S": "4"})
    t_unsafe = time.time()
    t_prom = wait_until(lambda: ev_t(events(log2), "lease_otorgado", t_unsafe) is not None, 60)
    msleep(3); w.halt()
    lost = w.lost_on("pg-oci")
    DATA["F5"] = {"degradado_tras_s": None if t_deg is None else round(t_deg, 1), "confirmadas_en_modo_degradado": len(at_risk), "promocion_automatica_bloqueada": blocked and no_lease,
                  "promocion_insegura_ordenada_ok": t_prom is not None, "confirmadas_perdidas_tras_la_promocion_insegura": len(lost),
                  "todas_las_perdidas_son_de_la_ventana_degradada": all(a[0] > t_deg_wall for a in lost)}
    check("F5 con política DEGRADAR: tras degradar y caer la primaria la promoción automática queda BLOQUEADA (se registra por qué); si se ordena explícitamente la promoción insegura, lo perdido son exactamente reservas confirmadas en la ventana degradada (límite de la garantía)",
          t_deg is not None and DATA["F5"]["promocion_automatica_bloqueada"] and t_prom is not None and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_de_la_ventana_degradada"], DATA["F5"])

    # F6 conmutación -> UNPROTECTED -> reconstrucción -> PROTECTED -> retorno planificado sin pérdida
    log = fresh_lab("F6", sync=True)
    w = Writers("f6"); w.start(); msleep(3)
    t_kill = kill_node("pg-aws")
    t_l = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
    msleep(3)
    mode_after = L.prot_load().get("mode")
    names_after = L.sql("pg-oci", "SHOW synchronous_standby_names")[1]
    acks_unprot = sum(1 for a in w.acked if a[0] > t_kill + 6)
    lost_failover = w.lost_on("pg-oci")
    L.reseed("pg-aws", "pg-oci")
    mode_reseed = L.prot_load().get("mode"); st_reseed = L.standby_state("pg-oci")
    msleep(3); w.halt()
    w2 = Writers("f6b"); w2.start(); msleep(2)
    with L.paused():
        ok_back = L.promote("pg-aws", planned=True)
    msleep(4); w2.halt()
    lost_back = [a for a in w.acked + w2.acked if a[2] not in set(q1("pg-aws", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())]
    DATA["F6"] = {"modo_tras_la_conmutacion": mode_after, "synchronous_standby_names_en_la_nueva_primaria": names_after, "confirmaciones_sin_proteccion": acks_unprot,
                  "perdidas_en_la_conmutacion": len(lost_failover), "modo_tras_reconstruir_el_seguidor": mode_reseed, "estado_del_seguidor": st_reseed,
                  "retorno_planificado_ok": ok_back, "perdidas_en_el_retorno": len(lost_back)}
    check("F6 tras la conmutación el sistema declara UNPROTECTED (sin seguidor); al reconstruir el seguidor vuelve a PROTECTED con confirmación síncrona; el retorno planificado no pierde reservas confirmadas",
          t_l is not None and mode_after == "unprotected" and names_after == "" and mode_reseed == "protected" and st_reseed in ("quorum", "sync") and ok_back and not lost_back, DATA["F6"])

    # F7 caída simultánea de AMBOS nodos y reinicio: durabilidad local de lo confirmado (no es una garantía de disponibilidad)
    log = fresh_lab("F7", sync=True)
    w = Writers("f7"); w.start(); msleep(4)
    stop_monitor()
    ts = [threading.Thread(target=lambda n=n: run("docker", "kill", L.cname(n))) for n in L.NODES]
    [t.start() for t in ts]; [t.join() for t in ts]
    w.halt()
    run("docker", "start", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 60)
    lost7 = w.lost_on("pg-aws")
    run("docker", "start", L.cname("pg-oci"))
    DATA["F7"] = {"confirmadas": len(w.acked), "perdidas_tras_reiniciar_la_primaria": len(lost7)}
    check("F7 caída simultánea de ambos nodos: tras reiniciar la primaria, 0 reservas confirmadas ausentes (durabilidad local con fsync); NO implica disponibilidad ni cubre pérdida de disco", len(lost7) == 0 and len(w.acked) > 0, DATA["F7"])
'''
    T = T.replace("# ================================================================== main", stage_f.lstrip("\n") + "\n\n# ================================================================== main", 1)
    T = T.replace('stages = {"A": stage_a, "B": stage_b, "C": stage_c, "D": stage_d, "E": stage_e}', 'stages = {"A": stage_a, "B": stage_b, "C": stage_c, "D": stage_d, "E": stage_e, "F": stage_f}')
    (here / "repl_test.py").write_text(T)
print("ok")
