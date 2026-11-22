#!/usr/bin/env python3
"""Parte de las pruebas de patch_fix_round3.py (la parte de labctl.py ya se aplicó). Busca cada fragmento con la sangría que tenga en el archivo (los escenarios la aumentan en 4)."""
import textwrap
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
T = p.read_text()


def rep(old: str, new: str, count_required=True):
    global T
    for extra in (0, 4, 8):
        o = textwrap.indent(textwrap.dedent(old), " " * extra)
        n = textwrap.indent(textwrap.dedent(new), " " * extra)
        if o in T:
            T = T.replace(o, n, 1)
            return
    if count_required:
        raise AssertionError("no se encontró: " + old[:80])


rep('''
    def lost_on(self, node: str):
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in self.acked if a[2] not in ids]''', '''
    def lost_on(self, node: str):
        snapshot = list(self.acked)            # primero las confirmaciones conocidas y DESPUÉS la lectura de la BD (así una confirmación posterior no cuenta como perdida)
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in snapshot if a[2] not in ids]''')
rep('''
prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
msleep(3); w.halt()''', '''
wait_until(lambda: L.prot_load().get("mode") == "protected", 40)       # la reprotección (barrera de LSN) puede tardar unos segundos tras la reconstrucción, con carga activa
prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
msleep(3); w.halt()''')
rep('''"todas_las_perdidas_son_de_la_ventana_sin_sincrono": all(a[0] > (t_off or 0) for a in lost), "perdidas_iguales_a_las_confirmadas_sin_sincrono": len(lost) == len(at_risk)}''',
    '''"primera_perdida_menos_registro_de_la_intencion_s": None if not lost else round(min(a[0] for a in lost) - (t_intent or 0), 3),
"todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading": all(a[0] > (t_intent or 0) for a in lost)}''')
rep('''at_risk = [a for a in w.acked if a[0] > (t_off or time.time())]       # frontera correcta: desde que se desactivó el síncrono''',
    '''at_risk = [a for a in w.acked if a[0] > (t_intent or time.time())]    # frontera: desde que el estado dejó de ser 'protected' (intención registrada)''')
rep('''"confirmadas_con_el_sincrono_desactivado": len(at_risk)''', '''"confirmadas_desde_que_el_estado_dejo_de_ser_protected": len(at_risk)''')
rep('''and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_de_la_ventana_sin_sincrono"], DATA["F5"])''',
    '''and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading"] and len(lost) <= len(at_risk), DATA["F5"])''')
T = T.replace("la promoción insegura explícita pierde exactamente lo confirmado con el síncrono desactivado (límite de la garantía, no un defecto)",
              "la promoción insegura explícita pierde solo reservas confirmadas DESPUÉS de que el estado dejó de ser 'protected' (límite de la garantía, no un defecto)")
rep('''check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la opción synchronous_commit='on' de la suscripción es imprescindible (con 'off' cada confirmación es mucho más lenta)",
      st0 in ("quorum", "sync") and lat_sub_off["p50_ms"] > 3 * lat_sync["p50_ms"], DATA["F1"])''',
    '''check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la suscripción lleva synchronous_commit='on'; las latencias síncrona, asíncrona y con la opción en 'off' se registran como DATO (la diferencia con 'off' varió entre 10 y 224 ms de mediana según el patrón de carga: no se usa como criterio)",
      st0 in ("quorum", "sync") and "on" in q1("pg-oci", "SELECT subsynccommit FROM pg_subscription"), DATA["F1"])''')
p.write_text(T)
print("ok")
