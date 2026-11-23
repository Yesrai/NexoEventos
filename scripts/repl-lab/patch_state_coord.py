#!/usr/bin/env python3
"""Transiciones de protección COORDINADAS: el estado vive en el witness con compare-and-set (secuencia + época); degradar y promover se excluyen mutuamente; se registra la intención
ANTES de tocar la configuración (degrading -> degraded); la compuerta de promoción relee el estado fresco y exige verificación reciente; recuperación de estados intermedios;
inyección de fallos en los puntos críticos; y limpieza verificada de synchronous_standby_names al dejar de ser primario."""
from pathlib import Path

p = Path(__file__).with_name("labctl.py")
s = p.read_text()
if "def prot_cas(" in s:
    print("ya aplicado"); raise SystemExit


def cut(text, start_marker, end_marker):
    a = text.index(start_marker)
    b = text.index(end_marker, a)
    return a, b


# ---------------------------------------------------------------- 1) bloque de protección completo (hasta antes de fence)
a, b = cut(s, 'PROT = ROOT / "work" / "repl-lab" / "protection.json"', "HBA_PATH = ") if False else (s.index('PROT = ROOT / "work" / "repl-lab" / "protection.json"'), s.index("def fence(node: str) -> bool:"))
block = '''PROT = ROOT / "work" / "repl-lab" / "protection.json"                    # en desuso: el estado de protección vive ahora en el witness (CAS por secuencia y época)
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
    """Vuelve a 'protected' solo con: CAS a 'reprotecting', síncrono habilitado y seguidor confirmando, y barrera de LSN (el seguidor al día)."""
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
    tabs = published_tables(primary)
    if counts(primary, tabs) != counts(f, tabs):
        return False
    prev = "degraded" if mode == "degraded" else "unprotected"
    if mode != "reprotecting" and not prot_cas("reprotecting", expect=("unknown", "unprotected", "degraded"), primario=primary, motivo=f"reprotección desde {mode}"):
        return False
    ok = enable_sync(primary, wait_s=10) and catch_up(primary, 15) and counts(primary, tabs) == counts(f, tabs)
    if ok and prot_cas("protected", expect=("reprotecting",), primario=primary, seguidor=f, motivo="síncrono activo, seguidor confirmando y al día (barrera de LSN)"):
        return True
    sync_names(primary, "")
    prot_cas(prev, expect=("reprotecting",), primario=primary, motivo="no se pudo completar la reprotección")
    return False


'''
s = s[:a] + block + s[b:]

# ---------------------------------------------------------------- 2) setup
old = '''        assert enable_sync("pg-aws"), "no se pudo habilitar la replicación síncrona"
        prot_save("protected", primario="pg-aws", seguidor="pg-oci", motivo="setup")
    else:
        prot_save("unprotected", primario="pg-aws", motivo="setup asíncrono (LAB_SYNC=0)")'''
new = '''        assert enable_sync("pg-aws"), "no se pudo habilitar la replicación síncrona"
        assert catch_up("pg-aws"), "el seguidor no alcanzó a la primaria en el setup"
        assert prot_cas("protected", expect=("unknown",), primario="pg-aws", seguidor="pg-oci", motivo="setup"), "no se pudo registrar la protección"
    else:
        prot_cas("unprotected", expect=("unknown",), primario="pg-aws", motivo="setup asíncrono (LAB_SYNC=0)")'''
assert old in s
s = s.replace(old, new)

# ---------------------------------------------------------------- 3) promoción
old = '''    prot_save("unprotected", primario=target, motivo="conmutación: aún no hay seguidor; las escrituras confirmadas hasta reconstruirlo NO tienen copia")'''
new = '''    prot_cas("unprotected", expect=("unknown",), primario=target, motivo="conmutación: aún no hay seguidor; las escrituras confirmadas hasta reconstruirlo NO tienen copia")'''
assert old in s
s = s.replace(old, new)
old = '''        log("drenado", igual=counts(src, tabs) == counts(target, tabs))'''
new = '''        log("drenado", igual=counts(src, tabs) == counts(target, tabs))
        log("sync_del_origen_limpiado", ok=sync_names(src, ""))      # el origen dejará de ser primario: que no conserve un síncrono hacia un seguidor que será su primaria'''
assert old in s
s = s.replace(old, new)

# ---------------------------------------------------------------- 4) supervisión + compuerta
a = s.index("def _supervise_standby(S: dict, w: str, auto: bool) -> None:")
b = s.index("def _step(S: dict, auto: bool) -> None:")
sup = '''def _supervise_standby(S: dict, w: str, auto: bool) -> None:
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
    names = sql(w, "SHOW synchronous_standby_names", timeout=3)[1]
    good = standby_state(w) in ("quorum", "sync")
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


'''
s = s[:a] + sup + s[b:]
a = s.index("                prot = prot_load()\n                mode = prot.get(\"mode\")")
b = s.index("    elif w is None and auto:", a)
s = s[:a] + "                _try_promote(S, w)\n" + s[b:]

# ---------------------------------------------------------------- 5) orphans / reseed: limpiar el síncrono obsoleto, verificando
old = '''    ro = set_readonly_global(old, True)
    w_ok, w_err = app_connect(old, write=True, origin=old)'''
new = '''    log("sync_obsoleto_limpiado", nodo=old, ok=sync_names(old, ""))
    ro = set_readonly_global(old, True)
    w_ok, w_err = app_connect(old, write=True, origin=old)'''
assert old in s
s = s.replace(old, new)
old = '''    sql(node, "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE NOT active")   # ranura obsoleta: llenaría el disco'''
new = '''    stale = sql(node, "SHOW synchronous_standby_names")[1]
    assert sync_names(node, ""), "no se pudo limpiar synchronous_standby_names: el TRUNCATE y la resuscripción quedarían esperando a un seguidor inexistente"
    log("sync_obsoleto_limpiado", nodo=node, valor_previo=stale, valor_actual=sql(node, "SHOW synchronous_standby_names")[1])
    sql(node, "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE NOT active")   # ranura obsoleta: llenaría el disco'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("coordinación aplicada")
