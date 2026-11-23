#!/usr/bin/env python3
"""F4R: repite 5 veces el escenario 'seguidor no disponible, política BLOQUEAR' con el INVARIANTE exacto: toda reserva confirmada al cliente después de que el seguidor se deshabilitó debe
existir ya en el seguidor (si no, se confirmó sin copia). En la corrida 3 de F aparecieron 5 confirmaciones en esa ventana sin explicación comprobada (hipótesis: respuestas 200 de repeticiones o
cola de latencia de commits ya replicados); aquí se registra cada una con su instante y se comprueba su presencia en el seguidor."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
T = p.read_text()
if "def stage_f4r()" in T:
    print("ya aplicado"); raise SystemExit
code = r'''

def stage_f4r():
    print("== F4R repetición del escenario 'seguidor no disponible' con el invariante exacto", flush=True)
    DATA["F4R"] = {}
    for i in range(1, 6):
        tag = f"F4R-{i}"
        with scenario(tag):
            log = fresh_lab(tag, sync=True)
            w = Writers("f4r"); w.start(); msleep(3)
            L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE"); t_off = time.time()      # el comando ya volvió: el apply worker está parado
            msleep(8)
            win = [a for a in w.acked if a[0] > t_off]
            ids_seg = set(q1("pg-oci", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
            absent = [a for a in win if a[2] not in ids_seg]
            waiters = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
            L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE")
            msleep(4); w.halt()
            DATA["F4R"][tag] = {"commits_esperando_en_SyncRep": waiters, "confirmaciones_al_cliente_tras_el_DISABLE": len(win),
                                "de_ellas_ausentes_en_el_seguidor_(confirmadas_sin_copia)": len(absent),
                                "instante_y_estado_de_cada_una_(s_tras_el_DISABLE, http)": [(round(a[0] - t_off, 2), a[3]) for a in win][:40],
                                "ausentes_detalle": [(round(a[0] - t_off, 2), a[3], a[2]) for a in absent][:20], "modo": L.prot_load().get("mode")}
            check(f"F4R {i}: tras deshabilitar el seguidor ninguna reserva confirmada al cliente carece de copia en el seguidor (hubo {len(win)} confirmaciones en la ventana; ausentes: {len(absent)})",
                  len(absent) == 0 and int(waiters) > 0, DATA["F4R"][tag])

'''
T = T.replace("\n# ================================================================== main", code + "\n# ================================================================== main", 1)
T = T.replace('"F0": f0_precheck, "F": stage_f}', '"F0": f0_precheck, "F": stage_f, "F4R": stage_f4r}')
p.write_text(T)
print("ok")
