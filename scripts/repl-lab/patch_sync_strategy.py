#!/usr/bin/env python3
"""Estrategia de protección de reservas confirmadas: replicación SÍNCRONA (synchronous_standby_names = 'ANY 1 (sub_<seguidor>)') con estados de protección,
política ante un seguidor no disponible (bloquear por defecto; degradar solo si se configura) y compuerta de promoción (no se promueve si hubo escrituras confirmadas
sin protección, salvo orden explícita). Se aplica sobre labctl.py (idempotente)."""
from pathlib import Path

p = Path(__file__).with_name("labctl.py")
s = p.read_text()
if "def enable_sync(" in s:
    print("ya aplicado"); raise SystemExit

# 1) sql(): opciones de sesión (PGOPTIONS)
old = '''def sql(node: str, q: str, *, user="postgres", origin: str | None = None, timeout=8, stdin: str | None = None, db="nexoeventos") -> tuple[int, str, str]:'''
new = '''def sql(node: str, q: str, *, user="postgres", origin: str | None = None, timeout=8, stdin: str | None = None, db="nexoeventos", pgoptions: str | None = None) -> tuple[int, str, str]:'''
assert old in s; s = s.replace(old, new)
old = '''    cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={APP_PW if user == 'nexoeventos_app' else REPL_PW if user == 'repl' else ADMIN_PW}", "-e", "PGCONNECT_TIMEOUT=2",
           cname(origin or node), "psql", "-X", "-q", "-U", user, "-d", db, "-tA", "-v", "ON_ERROR_STOP=1"]'''
new = '''    cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={APP_PW if user == 'nexoeventos_app' else REPL_PW if user == 'repl' else ADMIN_PW}", "-e", "PGCONNECT_TIMEOUT=2"]
    if pgoptions:
        cmd += ["-e", f"PGOPTIONS={pgoptions}"]
    cmd += [cname(origin or node), "psql", "-X", "-q", "-U", user, "-d", db, "-tA", "-v", "ON_ERROR_STOP=1"]'''
assert old in s; s = s.replace(old, new)

# 2) la sonda de vida del escritor confirma LOCALMENTE: una primaria bloqueada esperando al seguidor síncrono NO está muerta
old = '''    rc, out, err = sql(node, f"INSERT INTO lab_probe(node) VALUES ('{node}')", user="nexoeventos_app", origin=origin, timeout=4)
    return rc == 0, (err.splitlines() or [""])[-1][:140]'''
new = '''    rc, out, err = sql(node, f"INSERT INTO lab_probe(node) VALUES ('{node}')", user="nexoeventos_app", origin=origin, timeout=4, pgoptions="-c synchronous_commit=local")
    return rc == 0, (err.splitlines() or [""])[-1][:140]'''
assert old in s; s = s.replace(old, new)

# 3) app_connect: las escrituras de verificación no esperan al seguidor
old = '''    if override:
        cmd += ["-e", "PGOPTIONS=-c default_transaction_read_only=off"]'''
new = '''    cmd += ["-e", "PGOPTIONS=-c synchronous_commit=local" + (" -c default_transaction_read_only=off" if override else "")]'''
assert old in s; s = s.replace(old, new)

# 4) la suscripción confirma en modo síncrono (obligatorio: con el valor por defecto 'off' cada COMMIT tardó ~220 ms)
old = '''f"WITH (copy_data={'true' if copy_data else 'false'}, slot_name='slot_{s}')")'''
new = '''f"WITH (copy_data={'true' if copy_data else 'false'}, slot_name='slot_{s}', synchronous_commit='on')")'''
assert old in s; s = s.replace(old, new)

# 5) funciones de protección
a = s.index("def fence(node: str) -> bool:")
helpers = '''PROT = ROOT / "work" / "repl-lab" / "protection.json"
DEGRADE_AFTER_S = float(os.environ.get("LAB_DEGRADE_AFTER_S", "0"))      # 0 = nunca degradar: con el seguidor caído las escrituras ESPERAN (sin pérdida)
UNSAFE_PROMOTE = os.environ.get("LAB_UNSAFE_PROMOTE") == "1"             # promover aun con escrituras confirmadas sin protección (orden explícita; puede perder reservas)


def prot_load() -> dict:
    try:
        return json.loads(PROT.read_text())
    except Exception:
        return {"mode": "unknown"}


def prot_save(mode: str, **kw) -> None:
    """mode: protected (RPO=0 bajo las condiciones definidas) · degraded (escrituras confirmadas SIN seguidor síncrono) · unprotected (sin seguidor, p. ej. tras una conmutación)."""
    PROT.parent.mkdir(parents=True, exist_ok=True)
    cur = prot_load()
    PROT.write_text(json.dumps({"mode": mode, "since": time.time(), **kw}))
    log("proteccion", modo=mode, antes=cur.get("mode"), **kw)


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


def reprotect(primary: str) -> bool:
    """Vuelve a PROTECTED solo si el seguidor ya alcanzó a la primaria (mismos conteos en las tablas publicadas) y confirma como síncrono."""
    f = other(primary)
    tabs = published_tables(primary)
    if not running(cname(f)) or counts(primary, tabs) != counts(f, tabs):
        return False
    if enable_sync(primary, wait_s=10):
        prot_save("protected", primario=primary, seguidor=f, motivo="el seguidor alcanzó a la primaria")
        return True
    return False


'''
s = s[:a] + helpers + s[a:]

# 6) setup: protegido desde el inicio
old = '''    assert fm["efecto_en_conexion_nueva"] and om["efecto_en_conexion_nueva"], "el modo de acceso inicial no tuvo efecto"
'''
new = '''    assert fm["efecto_en_conexion_nueva"] and om["efecto_en_conexion_nueva"], "el modo de acceso inicial no tuvo efecto"
    if os.environ.get("LAB_SYNC", "1") == "1":
        assert enable_sync("pg-aws"), "no se pudo habilitar la replicación síncrona"
        prot_save("protected", primario="pg-aws", seguidor="pg-oci", motivo="setup")
    else:
        prot_save("unprotected", primario="pg-aws", motivo="setup asíncrono (LAB_SYNC=0)")
'''
assert old in s; s = s.replace(old, new)

# 7) promoción: el destino sin seguidor => UNPROTECTED y sin ajuste síncrono heredado
old = '''    seqs = fix_sequences(target)                         # 4) las secuencias no se replican'''
new = '''    sync_names(target, "")                               # 3b) el destino aún no tiene seguidor: un ajuste síncrono heredado bloquearía todos los COMMIT
    seqs = fix_sequences(target)                         # 4) las secuencias no se replican'''
assert old in s; s = s.replace(old, new)
old = '''    log("lease_otorgado", escritor=target, epoca=st["epoch"], t_desde_inicio_s=round(time.time() - t0, 2))'''
new = '''    log("lease_otorgado", escritor=target, epoca=st["epoch"], t_desde_inicio_s=round(time.time() - t0, 2))
    prot_save("unprotected", primario=target, motivo="conmutación: aún no hay seguidor; las escrituras confirmadas hasta reconstruirlo NO tienen copia")'''
assert old in s; s = s.replace(old, new)

# 8) reseed: al terminar, la primaria vuelve a PROTECTED
old = '''    log("reseed", nodo=node, origen=src, sincronizada_s=round(wait_synced(node), 1), conteos_iguales=counts(node, tabs) == counts(src, tabs))'''
new = '''    log("reseed", nodo=node, origen=src, sincronizada_s=round(wait_synced(node), 1), conteos_iguales=counts(node, tabs) == counts(src, tabs))
    if os.environ.get("LAB_SYNC", "1") == "1":
        if not reprotect(src):
            log("proteccion_no_restablecida", primario=src, motivo="el seguidor no alcanzó/confirmó como síncrono")'''
assert old in s; s = s.replace(old, new)

# 9) monitor: supervisión del seguidor, política y compuerta de promoción
old = '''        if ok:
            S["fails"][w] = 0
            code, js = w_req("POST", "/renew", {"node": w, "epoch": st["epoch"]})
            if code != 200:
                log("renovacion_rechazada", nodo=w, respuesta=js)
        else:
            S["fails"][w] += 1
            log("sonda_escritura_fallida", nodo=w, consecutivas=S["fails"][w], error=err)
            if auto and S["fails"][w] >= PROBE_FAILS_TO_PROMOTE:
                S["fails"][w] = 0
                promote(other(w))'''
new = '''        if ok:
            S["fails"][w] = 0
            code, js = w_req("POST", "/renew", {"node": w, "epoch": st["epoch"]})
            if code != 200:
                log("renovacion_rechazada", nodo=w, respuesta=js)
            _supervise_standby(S, w, auto)
        else:
            S["fails"][w] += 1
            log("sonda_escritura_fallida", nodo=w, consecutivas=S["fails"][w], error=err)
            if auto and S["fails"][w] >= PROBE_FAILS_TO_PROMOTE:
                mode = prot_load().get("mode")
                if mode == "protected" or UNSAFE_PROMOTE:
                    if mode != "protected":
                        log("promocion_insegura_ordenada", modo=mode, aviso="las escrituras confirmadas sin protección pueden perderse")
                    S["fails"][w] = 0
                    promote(other(w))
                elif time.time() - S.get("blocked_log", 0) > 5:
                    S["blocked_log"] = time.time()
                    log("promocion_bloqueada", modo=mode, desde=prot_load().get("since"), motivo="hubo escrituras confirmadas sin seguidor síncrono: promover podría perderlas; se requiere decisión explícita (LAB_UNSAFE_PROMOTE=1)")'''
assert old in s; s = s.replace(old, new)
a = s.index("def _step(S: dict, auto: bool) -> None:")
sup = '''def _supervise_standby(S: dict, w: str, auto: bool) -> None:
    """Vigila al seguidor síncrono del escritor vigente. Con el seguidor no disponible los COMMIT esperan (sin pérdida). Solo si LAB_DEGRADE_AFTER_S > 0 se degrada, de forma
    explícita y registrada, y a partir de ahí NO se promueve automáticamente (compuerta)."""
    if time.time() - S.get("sb_t", 0) < 1.0:
        return
    S["sb_t"] = time.time()
    mode = prot_load().get("mode")
    st = standby_state(w)
    good = st in ("quorum", "sync")
    if mode == "protected":
        if good:
            S.pop("sb_bad", None)
        else:
            S.setdefault("sb_bad", time.time())
            if S["sb_bad"] and time.time() - S["sb_bad"] == 0:
                log("seguidor_no_disponible", estado=st)
            if DEGRADE_AFTER_S > 0 and time.time() - S["sb_bad"] > DEGRADE_AFTER_S and auto:
                disable_sync(w, f"seguidor no disponible > {DEGRADE_AFTER_S}s: se prefiere disponibilidad (RPO > 0 posible)")
                prot_save("degraded", primario=w, motivo="seguidor no disponible", estado_seguidor=st)
                S.pop("sb_bad", None)
    elif mode == "degraded" and auto and good is False and running(cname(other(w))):
        reprotect(w)       # solo vuelve a PROTECTED con conteos iguales y confirmación síncrona
    elif mode == "unprotected" and auto and running(cname(other(w))) and sql(other(w), "SELECT count(*) FROM pg_subscription")[1] not in ("0", ""):
        reprotect(w)


'''
s = s[:a] + sup + s[a:]

# 10) status
old = '''    out = {"witness": witness_state(), "haproxy_db": hap_state(), "contenedores": {n: running(cname(n)) for n in NODES}}'''
new = '''    out = {"witness": witness_state(), "haproxy_db": hap_state(), "contenedores": {n: running(cname(n)) for n in NODES}, "proteccion": prot_load()}'''
assert old in s; s = s.replace(old, new)
p.write_text(s)
print("estrategia síncrona aplicada")
