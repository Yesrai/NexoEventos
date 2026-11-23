#!/usr/bin/env python3
"""Controlador del laboratorio nexo-repl-lab (solo Docker local, solo stdlib).

Hace de "plano de control": monta la replicación, vigila al escritor con ESCRITURAS REALES, promueve con fencing verificado y rehace la antigua primaria.
En la nube esto sería un servicio en un tercer sitio con credenciales de API para aislar nodos; aquí usa la CLI de Docker (ver informe, sección de límites).

Uso: labctl.py {setup|status|monitor [--no-auto]|promote NODO [--planned]|orphans ANTIGUA NUEVA|reseed NODO ORIGEN|witness-set ESCRITOR}
Variables: LAB_EVENT_LOG=archivo.jsonl (registro de eventos) · LAB_FENCE_FAIL=1 (inyecta que el aislamiento NO se pueda confirmar).
"""
from __future__ import annotations

import json, os, signal, subprocess, sys, time, traceback, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = "nexo-repl-lab"
NODES = ["pg-aws", "pg-oci"]
SHORT = {"pg-aws": "aws", "pg-oci": "oci"}
ADMIN_PW, APP_PW, REPL_PW = "lab-local-only-admin", "lab-local-only-app", "lab-local-only-repl"
WITNESS = "http://127.0.0.1:18100"
HAP_DB = "http://127.0.0.1:18405/;csv"
KEYFILE = ROOT / "work" / "repl-lab" / "key.env"
PROBE_FAILS_TO_PROMOTE = 3
EVENT_LOG = os.environ.get("LAB_EVENT_LOG")


def log(ev: str, **kw):
    line = json.dumps({"t": round(time.time(), 3), "ev": ev, **kw}, ensure_ascii=False)
    print(line, flush=True)
    if EVENT_LOG:
        with open(EVENT_LOG, "a") as f:
            f.write(line + "\n")


PAUSE = ROOT / "work" / "repl-lab" / "monitor.pause"


class paused:
    """Mientras dura una operación manual (promote/orphans/reseed por CLI) el monitor no actúa, para que no compita con ella."""
    def __enter__(self):
        PAUSE.parent.mkdir(parents=True, exist_ok=True); PAUSE.write_text(str(time.time())); time.sleep(0.8)

    def __exit__(self, *a):
        PAUSE.unlink(missing_ok=True)


def other(n: str) -> str:
    return NODES[1] if n == NODES[0] else NODES[0]


def cname(n: str) -> str:
    return f"{PROJECT}-{n}-1"


def dc(*args: str, check=True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if KEYFILE.exists():
        for l in KEYFILE.read_text().splitlines():
            if "=" in l:
                k, v = l.split("=", 1); env[k] = v
    r = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(HERE / "compose.yml"), "--profile", "tools", "--profile", "fault", "--profile", "stale", *args],
                       capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} falló: {r.stderr[-600:]}")
    return r


def running(c: str) -> bool:
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.Paused}}", c], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.split()[:2] == ["true", "false"]


def sql(node: str, q: str, *, user="postgres", origin: str | None = None, timeout=8, stdin: str | None = None, db="nexoeventos", pgoptions: str | None = None) -> tuple[int, str, str]:
    """Ejecuta SQL con psql dentro de un contenedor. Con `origin`, el camino es TCP desde ese contenedor hacia `node` (atraviesa la red del laboratorio)."""
    tcp = origin is not None or user != "postgres"
    cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={APP_PW if user == 'nexoeventos_app' else REPL_PW if user == 'repl' else ADMIN_PW}", "-e", "PGCONNECT_TIMEOUT=2"]
    if pgoptions:
        cmd += ["-e", f"PGOPTIONS={pgoptions}"]
    cmd += [cname(origin or node), "psql", "-X", "-q", "-U", user, "-d", db, "-tA", "-v", "ON_ERROR_STOP=1"]
    if tcp:
        cmd += ["-h", node]
    cmd += ["-c", q] if stdin is None else ["-f", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=stdin)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo de espera agotado"


def probe_write(node: str) -> tuple[bool, str]:
    """ESCRITURA REAL con el rol de la aplicación, por TCP desde el otro nodo (o desde el propio si el otro no corre)."""
    o = other(node)
    origin = o if running(cname(o)) else node
    rc, out, err = sql(node, f"INSERT INTO lab_probe(node) VALUES ('{node}')", user="nexoeventos_app", origin=origin, timeout=4, pgoptions="-c synchronous_commit=local")
    return rc == 0, (err.splitlines() or [""])[-1][:140]


# ------------------------------------------------------------------ witness
def w_req(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(WITNESS + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def witness_state() -> dict:
    code, js = w_req("GET", "/state")
    return js


def witness_set(writer: str | None, expect_epoch: int, ttl=6.0) -> dict:
    code, js = w_req("POST", "/set", {"writer": writer, "expect_epoch": expect_epoch, "ttl": ttl})
    if code != 200:
        raise RuntimeError(f"witness rechazó el cambio: {js}")
    return js


def hap_state() -> dict:
    try:
        with urllib.request.urlopen(HAP_DB, timeout=1.5) as r:
            rows = [l.split(",") for l in r.read().decode().splitlines()[1:] if l]
        return {x[1]: x[17] for x in rows if x[0] == "writer" and x[1] in NODES}
    except Exception:
        return {}


# ------------------------------------------------------------------ datos
def published_tables(node="pg-aws") -> list[str]:
    rc, out, _ = sql(node, "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','lab_probe') ORDER BY 1")
    return out.split()


def counts(node: str, tables: list[str]) -> dict:
    q = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in tables)
    rc, out, _ = sql(node, q)
    return {l.split("|")[0]: int(l.split("|")[1]) for l in out.splitlines()} if rc == 0 else {}


def fix_sequences(node: str) -> list[str]:
    q = ("SELECT s.relname, t.relname, a.attname FROM pg_class s JOIN pg_depend d ON d.objid=s.oid AND d.deptype='a' JOIN pg_class t ON t.oid=d.refobjid "
         "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid WHERE s.relkind='S'")
    rc, out, err = sql(node, q)
    stmts, done = [], []
    for l in out.splitlines():
        seq, tab, col = l.split("|")
        stmts.append(f"SELECT setval('{seq}', GREATEST((SELECT coalesce(max({col}),0) FROM {tab}), 1) + 1000)")
        done.append(f"{seq}<-{tab}.{col}")
    if stmts:
        sql(node, ";\n".join(stmts))
    return done


def subscription(target: str, src: str, copy_data=True):
    s = SHORT[target]
    rc, _, err = sql(target, f"CREATE SUBSCRIPTION sub_{s} CONNECTION 'host={src} dbname=nexoeventos user=repl password={REPL_PW}' PUBLICATION nexo_pub "
                             f"WITH (copy_data={'true' if copy_data else 'false'}, slot_name='slot_{s}', synchronous_commit='on')")
    assert rc == 0, err


def wait_synced(node: str, timeout=60) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        rc, out, _ = sql(node, "SELECT count(*) FROM pg_subscription_rel WHERE srsubstate <> 'r'")
        if rc == 0 and out == "0":
            rc2, out2, _ = sql(node, "SELECT count(*) FROM pg_subscription_rel")
            if out2 not in ("", "0"):
                return time.time() - t0
        time.sleep(0.5)
    raise RuntimeError("la suscripción no sincronizó")


# ------------------------------------------------------------------ setup
def setup():
    log("setup", paso="levantar PostgreSQL y witness")
    dc("up", "-d", "pg-aws", "pg-oci", "witness")
    for n in NODES:
        for _ in range(60):
            if sql(n, "SELECT 1")[0] == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"{n} no arrancó")
    for n in NODES:
        log("setup", paso="migraciones", nodo=n)
        r = dc("run", "--rm", "-e", f"MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:{ADMIN_PW}@{n}:5432/nexoeventos", "migrate", check=False)
        assert r.returncode == 0, r.stderr[-400:]
    lab = ("CREATE TABLE IF NOT EXISTS lab_probe(id bigserial PRIMARY KEY, node text, ts timestamptz DEFAULT now());"
           "CREATE TABLE IF NOT EXISTS lab_bulk(id bigserial PRIMARY KEY, payload text);"
           "GRANT ALL ON lab_probe, lab_bulk TO nexoeventos_app; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexoeventos_app;"
           "GRANT pg_read_all_data TO repl;")
    for n in NODES:
        assert sql(n, lab)[0] == 0
    tables = published_tables()
    for n in NODES:
        assert sql(n, f"CREATE PUBLICATION nexo_pub FOR TABLE {', '.join(tables)}")[0] == 0
    log("setup", paso="publicaciones", tablas=len(tables))
    # el seguidor parte vacío: las migraciones sembraron datos en ambos y la copia inicial chocaría
    assert sql("pg-oci", f"TRUNCATE {', '.join(tables)} CASCADE")[0] == 0
    sql("pg-oci", "ALTER ROLE nexoeventos_app SET default_transaction_read_only = on")
    sql("pg-aws", "ALTER ROLE nexoeventos_app RESET default_transaction_read_only")
    subscription("pg-oci", "pg-aws")
    log("setup", paso="suscripción creada", sincronizada_s=round(wait_synced("pg-oci"), 1))
    st = witness_state()
    witness_set("pg-aws", st["epoch"])
    fm = set_mode("pg-oci", "fenced")
    om = set_mode("pg-aws", "open")
    log("setup", paso="modos de acceso", pg_oci=fm, pg_aws=om)
    assert fm["efecto_en_conexion_nueva"] and om["efecto_en_conexion_nueva"], "el modo de acceso inicial no tuvo efecto"
    if sync_on():
        assert enable_sync("pg-aws"), "no se pudo habilitar la replicación síncrona"
        assert catch_up("pg-aws"), "el seguidor no alcanzó a la primaria en el setup"
        assert prot_cas("protected", expect=("unknown",), primario="pg-aws", seguidor="pg-oci", motivo="setup"), "no se pudo registrar la protección"
    else:
        prot_cas("unprotected", expect=("unknown",), primario="pg-aws", motivo="setup asíncrono (LAB_SYNC=0)")
    dc("up", "-d", "app-aws", "app-oci", "haproxy-db-aws", "haproxy-db-oci", "haproxy-edge")
    log("setup", paso="levantadas apps y HAProxy")
    for _ in range(40):
        if hap_state().get("pg-aws", "").startswith("UP"):
            break
        witness_renew()
        time.sleep(0.5)
    log("setup", paso="listo", haproxy_db=hap_state(), witness=witness_state())


def witness_renew():
    st = witness_state()
    if st.get("writer"):
        w_req("POST", "/renew", {"node": st["writer"], "epoch": st["epoch"]})


# ------------------------------------------------------------------ fencing y promoción
HBA_PATH = "/var/lib/postgresql/lab-hba.conf"
HBA_TEXT = {"open": "local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\nhost all all all scram-sha-256\n",
            "fenced": "local all all trust\nhost all all all reject\n"}


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
    cmd += ["-e", "PGOPTIONS=-c synchronous_commit=local" + (" -c default_transaction_read_only=off" if override else "")]
    host = "127.0.0.1" if o == node else node     # desde su propio contenedor: loopback (el nombre DNS no resuelve si el nodo está particionado)
    cmd += [cname(o), "psql", "-X", "-q", "-U", "nexoeventos_app", "-d", "nexoeventos", "-h", host, "-tA", "-v", "ON_ERROR_STOP=1", "-c", q]
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


PROT = ROOT / "work" / "repl-lab" / "protection.json"                    # en desuso: el estado de protección vive ahora en el witness (CAS por secuencia y época)
DEGRADE_AFTER_S = float(os.environ.get("LAB_DEGRADE_AFTER_S", "0"))      # 0 = nunca degradar: con el seguidor caído las escrituras ESPERAN (sin pérdida)
UNSAFE_PROMOTE = os.environ.get("LAB_UNSAFE_PROMOTE") == "1"             # promover aun con escrituras confirmadas sin protección (orden explícita; puede perder reservas)
VERIFY_MAX_AGE = float(os.environ.get("LAB_VERIFY_MAX_AGE", "15"))       # antigüedad máxima de la última verificación de la protección para permitir una promoción automática


def sync_on() -> bool:
    return os.environ.get("LAB_SYNC", "1") == "1"


def prot_load() -> dict:
    """Estado de protección tal como lo guarda el witness (única fuente de verdad)."""
    try:
        st = witness_state()
        p = dict(st.get("prot", {}))
        p.setdefault("mode", "unknown")
        p["witness_epoch"] = st.get("epoch")
        return p
    except Exception as e:  # noqa: BLE001
        return {"mode": "unknown", "error": f"witness no disponible ({type(e).__name__})"}


def prot_cas(mode: str, *, expect=None, **kw) -> bool:
    """Cambia el estado de protección SOLO si nadie lo cambió antes (secuencia) y seguimos en la misma época. Si el witness no responde, NO cambia nada."""
    try:
        st = witness_state()
    except Exception as e:  # noqa: BLE001
        log("proteccion_cas_fallida", modo=mode, motivo=f"witness no disponible ({type(e).__name__})", **kw)
        return False
    pr = st["prot"]
    if expect is not None and pr["mode"] not in expect:
        log("proteccion_cas_rechazada", modo=mode, actual=pr["mode"], esperado=list(expect), **kw)
        return False
    code, js = w_req("POST", "/prot", {"expect_seq": pr["seq"], "mode": mode, "primario": kw.get("primario", pr.get("primario")), "epoch": st["epoch"]})
    log("proteccion", modo=mode, antes=pr["mode"], ok=(code == 200), seq=js.get("prot", {}).get("seq"), **kw)
    return code == 200


def prot_verify(pr: dict, w: str, epoch: int) -> bool:
    code, _ = w_req("POST", "/prot_verify", {"seq": pr["seq"], "epoch": epoch, "primario": w})
    return code == 200


def standby_name(primary: str) -> str:
    return f"sub_{SHORT[other(primary)]}"


def standby_state(primary: str) -> str:
    """Estado síncrono del seguidor visto desde la primaria ('quorum'/'sync' = confirmando; '' = no conectado)."""
    rc, out, _ = sql(primary, f"SELECT coalesce(string_agg(sync_state, ','), '') FROM pg_stat_replication WHERE application_name='{standby_name(primary)}' AND state='streaming'", timeout=3)
    return out if rc == 0 else "?"


def sync_names(node: str, value: str) -> bool:
    """ALTER SYSTEM, recarga y comprobación del valor efectivo (tres operaciones separadas)."""
    q = f"ALTER SYSTEM SET synchronous_standby_names = '{value}'" if value else "ALTER SYSTEM RESET synchronous_standby_names"
    rc1, _, e1 = sql(node, q)
    rc2, out2, e2 = sql(node, "SELECT pg_reload_conf()")
    if rc1 != 0 or rc2 != 0:
        log("operacion_fallida", donde="sync_names", nodo=node, alter_system=e1[-120:], reload=e2[-120:]); return False
    for _ in range(20):
        if sql(node, "SHOW synchronous_standby_names")[1] == value:
            return True
        time.sleep(0.25)
    return False


def enable_sync(primary: str, wait_s=20) -> bool:
    ok = sync_names(primary, f"ANY 1 ({standby_name(primary)})")
    st = ""
    for _ in range(int(wait_s / 0.5)):
        st = standby_state(primary)
        if ok and st in ("quorum", "sync"):
            log("sync_habilitada", primario=primary, estado_seguidor=st); return True
        time.sleep(0.5)
    log("sync_no_confirmada", primario=primary, ajustado=ok, estado_seguidor=st)
    return False


def disable_sync(primary: str, motivo: str) -> bool:
    ok = sync_names(primary, "")
    log("sync_deshabilitada", primario=primary, motivo=motivo, ok=ok)
    return ok


def catch_up(primary: str, timeout=15) -> bool:
    """Barrera: el seguidor confirmó (flush) todo el WAL de la primaria hasta el LSN actual."""
    rc, lsn, _ = sql(primary, "SELECT pg_current_wal_lsn()")
    if rc != 0:
        return False
    for _ in range(int(timeout / 0.25)):
        rc, out, _ = sql(primary, f"SELECT coalesce(bool_and(flush_lsn >= '{lsn}'::pg_lsn), false) FROM pg_stat_replication WHERE application_name='{standby_name(primary)}' AND state='streaming'", timeout=3)
        if rc == 0 and out == "t":
            return True
        time.sleep(0.25)
    return False


def _fault(point: str, primary: str) -> None:
    """Inyección de fallos en los puntos críticos de una transición (solo pruebas): LAB_FAULT='<punto>:<exit|kill_primary>'."""
    spec = os.environ.get("LAB_FAULT", "")
    if not spec.startswith(point + ":"):
        return
    action = spec.split(":", 1)[1]
    log("fallo_inyectado", punto=point, accion=action)
    if action == "kill_primary":
        subprocess.run(["docker", "kill", cname(primary)], capture_output=True)
    elif action == "exit":
        os._exit(7)            # caída del controlador en ese punto exacto


def degrade(primary: str, motivo: str) -> bool:
    """Degradar SIN carreras: 1) intención registrada con CAS (si hay una promoción o cualquier otro cambio en curso, se aborta sin tocar la configuración);
    2) se desactiva el síncrono y se verifica; 3) se registra 'degraded'. Mientras el estado no sea 'protected' la compuerta NO promueve automáticamente."""
    if not prot_cas("degrading", expect=("protected",), primario=primary, motivo=motivo):
        log("degradacion_abortada", motivo="el estado de protección cambió o hay una promoción en curso: no se toca la configuración")
        return False
    _fault("after_intent", primary)
    ok = sync_names(primary, "")
    log("sync_deshabilitada", primario=primary, motivo=motivo, ok=ok)
    _fault("after_disable", primary)
    if not ok:
        return False                                       # queda 'degrading': la recuperación lo resolverá
    done = prot_cas("degraded", expect=("degrading",), primario=primary, motivo=motivo)
    _fault("after_record", primary)
    return done


def reprotect(primary: str) -> bool:
    """Vuelve a 'protected' sin bloquear al controlador ni a las escrituras: exige que el seguidor esté habilitado y TRANSMITIENDO (si no, no toca nada), pasa por 'reprotecting' con CAS,
    habilita el síncrono y usa una barrera de LSN (el seguidor confirmó todo el WAL previo). No exige conteos iguales: con carga continua nunca coinciden."""
    f = other(primary)
    try:
        st = witness_state()
    except Exception:  # noqa: BLE001
        return False
    mode = st["prot"]["mode"]
    if mode == "protected":
        return True
    if mode not in ("unknown", "unprotected", "degraded", "reprotecting") or not running(cname(f)):
        return False
    rc, en, _ = sql(f, "SELECT coalesce(bool_and(subenabled), false) FROM pg_subscription", timeout=3)
    rc2, streaming, _ = sql(primary, f"SELECT count(*) FROM pg_stat_replication WHERE application_name='{standby_name(primary)}' AND state='streaming'", timeout=3)
    if rc != 0 or en != "t" or rc2 != 0 or streaming in ("", "0"):
        return False                                                # seguidor no disponible: no se cambia ni el estado ni la configuración
    prev = "degraded" if mode == "degraded" else "unprotected"
    if mode != "reprotecting" and not prot_cas("reprotecting", expect=("unknown", "unprotected", "degraded"), primario=primary, motivo=f"reprotección desde {mode}"):
        return False
    ok = enable_sync(primary, wait_s=5) and catch_up(primary, 8)
    if ok and prot_cas("protected", expect=("reprotecting",), primario=primary, seguidor=f, motivo="síncrono activo, seguidor confirmando y al día (barrera de LSN)"):
        return True
    sync_names(primary, "")
    prot_cas(prev, expect=("reprotecting",), primario=primary, motivo="no se pudo completar la reprotección")
    return False


def fence(node: str) -> bool:
    """Aísla `node` en capas y COMPRUEBA con intentos reales de escritura directa (conexión nueva, y con intento de anular el solo-lectura).
    Devuelve True solo si el nodo queda detenido o rechazando toda escritura; si no, el estado se registra como INSEGURO y no se promueve."""
    if os.environ.get("LAB_FENCE_FAIL") == "1":
        log("fence", nodo=node, resultado="inyectado: no se puede confirmar el aislamiento")
        log("estado_inseguro", nodo=node, motivo="aislamiento no confirmable (inyectado): NO se promueve a otro escritor")
        return False
    if running(cname(node)):
        d = {"modo_cerrado": set_mode(node, "fenced"), "solo_lectura_global": set_readonly_global(node, True), "sesiones_app_terminadas": terminate_app_sessions(node)}
        w_ok, w_err = app_connect(node, write=True, origin=node)
        o_ok, o_err = app_connect(node, write=True, override=True, origin=node)
        d.update(escritura_real_conexion_nueva_aceptada=w_ok, escritura_real_con_anulacion_aceptada=o_ok, rechazo_conexion_nueva=w_err, rechazo_con_anulacion=o_err)
        hba_w, hba_o = "pg_hba.conf rejects" in w_err, "pg_hba.conf rejects" in o_err   # una negativa por DNS o por tiempo agotado NO cuenta como aislamiento verificado
        d.update(rechazo_atribuible_a_pg_hba=hba_w and hba_o)
        verified = d["modo_cerrado"].get("efecto_en_conexion_nueva") and d["sesiones_app_terminadas"] and not w_ok and not o_ok and hba_w and hba_o
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


def promote(target: str, planned=False) -> bool:
    try:
        return _promote(target, planned)
    except Exception:
        safe_exc("promote")
        log("promote_abortada", motivo="excepción durante la promoción: se queda SIN nuevo escritor (falla segura); requiere revisión", destino=target)
        return False


def _promote(target: str, planned=False) -> bool:
    src = other(target)
    t0 = time.time()
    try:
        st = witness_state()
    except Exception as e:
        log("promote_abortada", motivo=f"witness no disponible ({type(e).__name__}): no se promueve", nodo=target)
        return False
    epoch = st["epoch"]
    log("promote_inicio", destino=target, origen=src, planificada=planned, epoca=epoch)
    st = witness_set(None, epoch)                       # 1) nadie es escritor mientras se decide
    epoch = st["epoch"]
    log("lease_retirado", epoca=epoch)
    if planned:                                          # 1b) drenado ordenado del escritor actual
        sql(src, "ALTER ROLE nexoeventos_app SET default_transaction_read_only = on; SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='nexoeventos_app'")
        tabs = published_tables(src)
        for _ in range(60):
            if counts(src, tabs) == counts(target, tabs):
                break
            time.sleep(0.5)
        log("drenado", igual=counts(src, tabs) == counts(target, tabs))
        log("sync_del_origen_limpiado", ok=sync_names(src, ""))      # el origen dejará de ser primario: que no conserve un síncrono hacia un seguidor que será su primaria
    if not fence(src):                                   # 2) sin aislamiento confirmado NO se promueve
        ok, _ = probe_write(src)
        if ok:
            st = witness_set(src, epoch)
            log("promote_abortada", motivo="aislamiento no confirmado; el escritor anterior responde: se le devuelve el lease", lease_a=src, epoca=st["epoch"])
        else:
            log("promote_abortada", motivo="aislamiento no confirmado y el escritor anterior no responde: SIN escritor (falla segura)", epoca=epoch)
        return False
    s = SHORT[target]                                    # 3) cortar la suscripción (la ranura queda en el origen caído)
    sql(target, f"ALTER SUBSCRIPTION sub_{s} DISABLE; ALTER SUBSCRIPTION sub_{s} SET (slot_name = NONE); DROP SUBSCRIPTION sub_{s}")
    sync_names(target, "")                               # 3b) el destino aún no tiene seguidor: un ajuste síncrono heredado bloquearía todos los COMMIT
    seqs = fix_sequences(target)                         # 4) las secuencias no se replican
    log("secuencias_ajustadas", cantidad=len(seqs))
    rc_r, _, e_r = sql(target, "ALTER ROLE nexoeventos_app RESET default_transaction_read_only")
    ro_off = set_readonly_global(target, False)
    opened = set_mode(target, "open")
    terminate_app_sessions(target)
    log("destino_abierto", rol_sin_solo_lectura=rc_r == 0, solo_lectura_global_apagado=ro_off, modo_abierto=opened)
    if rc_r != 0 or not ro_off or not opened.get("efecto_en_conexion_nueva"):
        log("promote_abortada", motivo="no se pudo abrir el destino con efecto comprobado", epoca=epoch)
        return False
    ok, err = probe_write(target)                        # 5) escritura real en el destino ANTES de dar el lease
    log("escritura_destino", aceptada=ok, error=err)
    if not ok:
        log("promote_abortada", motivo="el destino no acepta escrituras", epoca=epoch)
        return False
    st = witness_set(target, epoch)                      # 6) lease al destino
    log("lease_otorgado", escritor=target, epoca=st["epoch"], t_desde_inicio_s=round(time.time() - t0, 2))
    prot_cas("unprotected", expect=("unknown",), primario=target, motivo="conmutación: aún no hay seguidor; las escrituras confirmadas hasta reconstruirlo NO tienen copia")
    for _ in range(40):
        if hap_state().get(target, "").startswith("UP"):
            log("haproxy_db_enruta", nodo=target, t_desde_inicio_s=round(time.time() - t0, 2)); break
        time.sleep(0.25)
    ok2, err2 = probe_write(src)                         # 7) comprobación posterior: el antiguo escritor sigue sin poder escribir
    log("verificacion_final", antiguo_escribe=ok2, error=err2)
    return not ok2


# ------------------------------------------------------------------ monitor
def safe_exc(donde: str) -> None:
    """Registra la excepción en curso (tipo, detalle y cola de la traza) como evidencia. Nunca se silencia."""
    log("excepcion", donde=donde, tipo=type(sys.exc_info()[1]).__name__, detalle=str(sys.exc_info()[1])[:300], traza=traceback.format_exc()[-700:])


def _supervise_standby(S: dict, w: str, auto: bool) -> None:
    """Supervisión del seguidor síncrono y máquina de estados de protección (cada transición, con CAS en el witness). Con el seguidor no disponible los COMMIT esperan (sin pérdida);
    solo si LAB_DEGRADE_AFTER_S > 0 se degrada, de forma explícita, registrada y coordinada."""
    if time.time() - S.get("sb_t", 0) < 1.0:
        return
    S["sb_t"] = time.time()
    try:
        st = witness_state()
    except Exception:  # noqa: BLE001
        return
    pr = st["prot"]
    mode = pr["mode"]
    rc_n, names, _ = sql(w, "SHOW synchronous_standby_names", timeout=3)
    sb = standby_state(w)
    if rc_n != 0 or sb == "?":          # no se pudo CONSULTAR (p. ej. la primaria acaba de caer): no se interpreta como un cambio de configuración; se omite el ciclo
        return
    good = sb in ("quorum", "sync")
    expected = f"ANY 1 ({standby_name(w)})"
    if mode == "protected":
        if pr.get("primario") != w or pr.get("epoch") != st["epoch"]:
            prot_cas("unprotected", expect=("protected",), primario=w, motivo="el registro de protección no corresponde al escritor o a la época vigentes")
        elif names != expected:
            prot_cas("degraded", expect=("protected",), primario=w, motivo=f"synchronous_standby_names cambió fuera del controlador: {names!r}")
        elif good:
            S.pop("sb_bad", None)
            prot_verify(pr, w, st["epoch"])
        else:
            if "sb_bad" not in S:
                S["sb_bad"] = time.time()
                log("seguidor_no_disponible", estado=standby_state(w), politica=("degradar tras %ss" % DEGRADE_AFTER_S) if DEGRADE_AFTER_S > 0 else "bloquear: los COMMIT esperan, sin pérdida")
            if DEGRADE_AFTER_S > 0 and auto and time.time() - S["sb_bad"] > DEGRADE_AFTER_S:
                degrade(w, f"seguidor no disponible > {DEGRADE_AFTER_S}s: se prefiere disponibilidad (RPO > 0 posible)")
                S.pop("sb_bad", None)
    elif mode == "degrading":                       # transición interrumpida (caída del controlador o fallo entre pasos): se resuelve según la configuración EFECTIVA
        if names == "":
            prot_cas("degraded", expect=("degrading",), primario=w, motivo="recuperación: el síncrono ya estaba desactivado")
        elif good or not (DEGRADE_AFTER_S > 0 and auto):
            prot_cas("protected", expect=("degrading",), primario=w, motivo="recuperación: el síncrono seguía activo (nada se confirmó sin copia)")
        elif sync_names(w, ""):
            prot_cas("degraded", expect=("degrading",), primario=w, motivo="recuperación: se completa la degradación")
    elif mode == "reprotecting":
        reprotect(w)
    elif mode == "promoting":
        prot_cas("unprotected", expect=("promoting",), primario=w, motivo="promoción abortada o interrumpida: se asume sin protección")
    elif mode == "unknown":
        prot_cas("unprotected", expect=("unknown",), primario=w, motivo="estado desconocido: se asume sin protección")
    elif mode in ("degraded", "unprotected") and auto and running(cname(other(w))) and sql(other(w), "SELECT count(*) FROM pg_subscription")[1] not in ("0", ""):
        reprotect(w)


def _try_promote(S: dict, w: str) -> None:
    """Compuerta de promoción automática con sync activo: relee el estado FRESCO del witness justo antes de decidir (la lectura del inicio del ciclo puede ser obsoleta), exige modo
    'protected', escritor y época coherentes y una verificación reciente, y reclama la promoción con un CAS exclusivo: una degradación concurrente falla y viceversa."""
    if not sync_on():
        S["fails"][w] = 0
        promote(other(w)); return
    try:
        st = witness_state()
    except Exception as e:  # noqa: BLE001
        log("promocion_aplazada", motivo=f"witness no disponible ({type(e).__name__}): no se promueve")
        return
    pr = st["prot"]
    age = pr.get("verified_age_s")
    reasons = []
    if st.get("writer") != w:
        reasons.append("el escritor vigente del witness no es el nodo que cae")
    if pr.get("mode") != "protected":
        reasons.append(f"modo de protección {pr.get('mode')!r}")
    if pr.get("primario") != w:
        reasons.append(f"el estado de protección es de {pr.get('primario')!r}, no de {w!r}")
    if pr.get("epoch") != st.get("epoch"):
        reasons.append("la época del estado de protección no es la vigente")
    if age is None or age > VERIFY_MAX_AGE:
        reasons.append(f"última verificación de la protección hace {age}s (máximo {VERIFY_MAX_AGE}s)")
    if reasons and not UNSAFE_PROMOTE:
        if time.time() - S.get("blocked_log", 0) > 5:
            S["blocked_log"] = time.time()
            log("promocion_bloqueada", razones=reasons, modo=pr.get("mode"), escritor_que_cae=w, secuencia=pr.get("seq"),
                motivo="no se puede comprobar que lo confirmado tenga copia síncrona: promover podría perder reservas; se requiere decisión explícita (LAB_UNSAFE_PROMOTE=1)")
        return
    if reasons:
        log("promocion_insegura_ordenada", razones=reasons, aviso="las escrituras confirmadas sin protección pueden perderse")
    elif not prot_cas("promoting", expect=("protected",), primario=w, motivo="reclamo exclusivo de la promoción"):
        log("promocion_aplazada_por_cambio_concurrente_de_estado")
        return
    S["fails"][w] = 0
    promote(other(w))


def _step(S: dict, auto: bool) -> None:
    """Un ciclo del monitor. Ante cualquier duda (witness, lease, aislamiento) NO se promueve: se registra y se espera."""
    t = time.time()
    try:
        st = witness_state()
    except Exception as e:
        if S["last"] != "witness_caido":
            log("witness_no_disponible", detalle=type(e).__name__, accion="no se renueva ni se promueve (falla segura)")
        S["last"] = "witness_caido"
        return
    if S["last"] == "witness_caido":
        log("witness_recuperado", estado=st)
    S["last"] = "ok"
    if t - S["beat"] >= 5:
        S["beat"] = t
        log("latido", witness=st, sondas_fallidas=dict(S["fails"]))
    w = st.get("writer")
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
    if w in NODES:
        ok, err = probe_write(w)
        if ok:
            S["fails"][w] = 0
            code, js = w_req("POST", "/renew", {"node": w, "epoch": st["epoch"]})
            if code != 200:
                log("renovacion_rechazada", nodo=w, respuesta=js)
            if sync_on():
                _supervise_standby(S, w, auto)
        else:
            S["fails"][w] += 1
            log("sonda_escritura_fallida", nodo=w, consecutivas=S["fails"][w], error=err)
            if auto and S["fails"][w] >= PROBE_FAILS_TO_PROMOTE:
                _try_promote(S, w)
    elif w is None and auto:
        # Sin escritor. Solo se devuelve el lease si EXACTAMENTE un nodo es escribible y no es un seguidor; si hay ambigüedad, no se hace nada.
        cands = []
        for n in NODES:
            if running(cname(n)) and sql(n, "SELECT pg_is_in_recovery()")[1] == "f":
                ok, _ = probe_write(n)
                _, subs, _ = sql(n, "SELECT count(*) FROM pg_subscription")
                if ok and subs == "0":
                    cands.append(n)
        if len(cands) == 1:
            witness_set(cands[0], st["epoch"]); log("lease_restaurado", escritor=cands[0]); S["stuck"] = 0
        elif len(cands) > 1:
            log("sin_escritor_ambiguo", candidatos=cands, accion="no se otorga lease: dos nodos aceptan escrituras")
        else:
            S["stuck"] += 1
            # promoción interrumpida (p. ej. el witness cayó a mitad): si el antiguo escritor NO está en ejecución, se reanuda; promote() vuelve a aislar y a verificar
            f_nodes = [n for n in NODES if running(cname(n)) and sql(n, "SELECT count(*) FROM pg_subscription")[1] not in ("0", "")]
            if S["stuck"] >= 4 and len(f_nodes) == 1 and not running(cname(other(f_nodes[0]))):
                S["stuck"] = 0
                log("reanudar_promocion_interrumpida", destino=f_nodes[0])
                promote(f_nodes[0])


def monitor(auto=True):
    S = {"fails": {n: 0 for n in NODES}, "guard": 0.0, "last": None, "beat": 0.0, "stuck": 0}
    log("monitor_inicio", auto=auto, pid=os.getpid())
    signal.signal(signal.SIGTERM, lambda *a: (log("monitor_fin", motivo="SIGTERM"), sys.exit(0)))
    errs = 0
    while True:
        t = time.time()
        if PAUSE.exists():
            time.sleep(0.3); continue
        try:
            _step(S, auto)
            errs = 0
        except Exception:
            errs += 1
            safe_exc("monitor._step")          # ciclo omitido: no se promueve nada ante la duda
            if errs >= 50:
                log("monitor_fin", motivo="demasiadas excepciones seguidas"); sys.exit(2)
        time.sleep(max(0, 0.5 - (time.time() - t)))


# ------------------------------------------------------------------ failback seguro
def orphans(old: str, new: str, out_dir: str) -> dict:
    """Con la antigua primaria arrancada en SOLO LECTURA, calcula y guarda (fuera de Docker) las filas que existen en ella y NO en la nueva primaria."""
    if not running(cname(old)):
        subprocess.run(["docker", "start", cname(old)], capture_output=True)
    for _ in range(60):
        if sql(old, "SELECT 1")[0] == 0:
            break
        time.sleep(1)
    log("sync_obsoleto_limpiado", nodo=old, ok=sync_names(old, ""))
    ro = set_readonly_global(old, True)
    w_ok, w_err = app_connect(old, write=True, origin=old)
    o_ok, _ = app_connect(old, write=True, override=True, origin=old)
    log("antigua_primaria_al_volver", nodo=old, solo_lectura_global=ro, escritura_real_aceptada=w_ok, escritura_real_con_anulacion_aceptada=o_ok, rechazo=w_err)
    tabs = published_tables(new)
    res, dup = {}, []
    for t in tabs:
        q = ("SELECT string_agg(quote_ident(a.attname)||'::text', '||''|''||' ORDER BY array_position(i.indkey::int2[], a.attnum)) FROM pg_index i "
             f"JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey) WHERE i.indrelid='{t}'::regclass AND i.indisprimary")
        pk = sql(new, q)[1]
        if not pk:
            continue
        old_ids = set(sql(old, f"SELECT {pk} FROM {t}")[1].splitlines())
        new_ids = set(sql(new, f"SELECT {pk} FROM {t}")[1].splitlines())
        miss = sorted(old_ids - new_ids)
        if miss:
            lit = ",".join("'" + m.replace("'", "''") + "'" for m in miss)
            rows = [json.loads(x) for x in sql(old, f"SELECT row_to_json(x) FROM {t} x WHERE ({pk}) IN ({lit})")[1].splitlines() if x]
            res[t] = rows
    # duplicados lógicos: reservas huérfanas cuya Idempotency-Key ya existe en la nueva primaria con otro id
    for r in res.get("reservations", []):
        rc, out, _ = sql(new, f"SELECT id FROM reservations WHERE idempotency_key='{r['idempotency_key']}'")
        if out and out != str(r["id"]):
            dup.append({"orfana": r["id"], "idempotency_key": r["idempotency_key"], "reserva_en_nueva_primaria": out})
    summary = {"tablas_con_huerfanas": {t: len(v) for t, v in res.items()}, "duplicados_logicos_por_idempotency_key": dup}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / f"huerfanas-{old}-{int(time.time())}.json").write_text(json.dumps({"resumen": summary, "filas": res}, indent=2, ensure_ascii=False, default=str) + "\n")
    log("huerfanas_guardadas", **summary)
    return summary


def reseed(node: str, src: str):
    """Reconstruye `node` como seguidor de `src`. DESTRUCTIVO para los datos de `node`: exige haber guardado antes las huérfanas (orphans)."""
    if not running(cname(node)):
        subprocess.run(["docker", "start", cname(node)], capture_output=True)
    for _ in range(60):
        if sql(node, "SELECT 1")[0] == 0:
            break
        time.sleep(1)
    stale = sql(node, "SHOW synchronous_standby_names")[1]
    assert sync_names(node, ""), "no se pudo limpiar synchronous_standby_names: el TRUNCATE y la resuscripción quedarían esperando a un seguidor inexistente"
    log("sync_obsoleto_limpiado", nodo=node, valor_previo=stale, valor_actual=sql(node, "SHOW synchronous_standby_names")[1])
    sql(node, "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE NOT active")   # ranura obsoleta: llenaría el disco
    assert set_readonly_global(node, False), "no se pudo quitar el solo-lectura global para reconstruir el nodo"
    tabs = published_tables(src)
    assert sql(node, f"TRUNCATE {', '.join(tabs)} CASCADE")[0] == 0
    sql(node, "ALTER ROLE nexoeventos_app SET default_transaction_read_only = on")
    terminate_app_sessions(node)
    log("reseed_modo", nodo=node, **set_mode(node, "fenced"))
    s = SHORT[node]
    sql(node, f"DROP SUBSCRIPTION IF EXISTS sub_{s}")
    subscription(node, src)
    log("reseed", nodo=node, origen=src, sincronizada_s=round(wait_synced(node), 1), conteos_iguales=counts(node, tabs) == counts(src, tabs))
    if sync_on():
        if not reprotect(src):
            log("proteccion_no_restablecida", primario=src, motivo="el seguidor no alcanzó/confirmó como síncrono")


def status():
    out = {"witness": witness_state(), "haproxy_db": hap_state(), "contenedores": {n: running(cname(n)) for n in NODES}, "proteccion": prot_load()}
    for n in NODES:
        if running(cname(n)):
            out[n] = {"en_recuperacion": sql(n, "SELECT pg_is_in_recovery()")[1], "suscripciones": sql(n, "SELECT string_agg(subname||':'||subenabled::text, ',') FROM pg_subscription")[1],
                      "reservas": sql(n, "SELECT count(*) FROM reservations")[1], "usuarios": sql(n, "SELECT count(*) FROM users")[1]}
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "setup": setup()
    elif cmd == "status": status()
    elif cmd == "monitor": monitor(auto="--no-auto" not in a)
    elif cmd == "promote":
        with paused(): sys.exit(0 if promote(a[1], planned="--planned" in a) else 1)
    elif cmd == "orphans":
        with paused(): orphans(a[1], a[2], a[3] if len(a) > 3 else str(ROOT / "work" / "repl-lab"))
    elif cmd == "reseed":
        with paused(): reseed(a[1], a[2])
    elif cmd == "witness-set": w = witness_state(); print(witness_set(a[1] if a[1] != "none" else None, w["epoch"]))
    else: sys.exit(__doc__)
