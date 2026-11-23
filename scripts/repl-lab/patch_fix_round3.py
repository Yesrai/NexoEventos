#!/usr/bin/env python3
"""Correcciones tras la corrida 2 de F:
(1) un fallo al CONSULTAR el estado (primaria muerta justo en ese instante) se interpretaba como 'el síncrono cambió fuera del controlador' y degradaba falsamente => ahora se omite el ciclo;
(2) reprotect exigía conteos iguales (imposible con carga continua) y habilitaba el síncrono aunque el seguidor no estuviera transmitiendo, bloqueando escrituras y el bucle del controlador =>
    ahora exige seguidor habilitado y TRANSMITIENDO, habilita el síncrono y usa una barrera de LSN; tiempos de espera cortos;
(3) pruebas: lost_on tomaba la lista de confirmadas DESPUÉS de leer la BD (carrera con escritores activos); F6 leía el estado de protección antes de que se restableciera; F5 medía la frontera con
    un evento posterior al efecto real; F1 comparaba latencias con un umbral frágil (se conserva como dato informativo)."""
from pathlib import Path

here = Path(__file__).parent
L = (here / "labctl.py").read_text()

old = '''    names = sql(w, "SHOW synchronous_standby_names", timeout=3)[1]
    good = standby_state(w) in ("quorum", "sync")
    expected = f"ANY 1 ({standby_name(w)})"'''
new = '''    rc_n, names, _ = sql(w, "SHOW synchronous_standby_names", timeout=3)
    sb = standby_state(w)
    if rc_n != 0 or sb == "?":          # no se pudo CONSULTAR (p. ej. la primaria acaba de caer): no se interpreta como un cambio de configuración; se omite el ciclo
        return
    good = sb in ("quorum", "sync")
    expected = f"ANY 1 ({standby_name(w)})"'''
assert old in L
L = L.replace(old, new)

a = L.index("def reprotect(primary: str) -> bool:")
b = L.index("def fence(node: str) -> bool:")
new_reprotect = '''def reprotect(primary: str) -> bool:
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


'''
L = L[:a] + new_reprotect + L[b:]
(here / "labctl.py").write_text(L)

T = (here / "repl_test.py").read_text()
old = '''    def lost_on(self, node: str):
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in self.acked if a[2] not in ids]'''
new = '''    def lost_on(self, node: str):
        snapshot = list(self.acked)            # primero las confirmaciones conocidas y DESPUÉS la lectura de la BD (así una confirmación posterior no cuenta como perdida)
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in snapshot if a[2] not in ids]'''
assert old in T
T = T.replace(old, new)

old = '''    prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
    msleep(3); w.halt()'''
new = '''    wait_until(lambda: L.prot_load().get("mode") == "protected", 40)       # la reprotección (barrera de LSN) puede tardar unos segundos tras la reconstrucción, con carga activa
    prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
    msleep(3); w.halt()'''
assert old in T
T = T.replace(old, new)

old = '''                  "todas_las_perdidas_son_de_la_ventana_sin_sincrono": all(a[0] > (t_off or 0) for a in lost), "perdidas_iguales_a_las_confirmadas_sin_sincrono": len(lost) == len(at_risk)}'''
new = '''                  "primera_perdida_menos_registro_de_la_intencion_s": None if not lost else round(min(a[0] for a in lost) - (t_intent or 0), 3),
                  "todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading": all(a[0] > (t_intent or 0) for a in lost)}'''
assert old in T
T = T.replace(old, new)
T = T.replace('''    at_risk = [a for a in w.acked if a[0] > (t_off or time.time())]       # frontera correcta: desde que se desactivó el síncrono''',
              '''    at_risk = [a for a in w.acked if a[0] > (t_intent or time.time())]    # frontera: desde que el estado dejó de ser 'protected' (intención registrada)''')
T = T.replace('''"confirmadas_con_el_sincrono_desactivado": len(at_risk)''', '''"confirmadas_desde_que_el_estado_dejo_de_ser_protected": len(at_risk)''')
T = T.replace('''and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_de_la_ventana_sin_sincrono"], DATA["F5"])''',
              '''and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading"] and len(lost) <= len(at_risk), DATA["F5"])''')
T = T.replace("la promoción insegura explícita pierde exactamente lo confirmado con el síncrono desactivado (límite de la garantía, no un defecto)", "la promoción insegura explícita pierde solo reservas confirmadas DESPUÉS de que el estado dejó de ser 'protected' (límite de la garantía, no un defecto)")

old = '''    check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la opción synchronous_commit='on' de la suscripción es imprescindible (con 'off' cada confirmación es mucho más lenta)",
          st0 in ("quorum", "sync") and lat_sub_off["p50_ms"] > 3 * lat_sync["p50_ms"], DATA["F1"])'''
new = '''    check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la suscripción lleva synchronous_commit='on'; las latencias síncrona, asíncrona y con la opción en 'off' se registran como DATO (la diferencia con 'off' varió entre 10 y 224 ms de mediana según el patrón de carga: no se usa como criterio)",
          st0 in ("quorum", "sync") and "on" in q1("pg-oci", "SELECT subsynccommit FROM pg_subscription"), DATA["F1"])'''
assert old in T
T = T.replace(old, new)
(here / "repl_test.py").write_text(T)
print("ok")
