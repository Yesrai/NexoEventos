#!/usr/bin/env python3
"""F0: el control asíncrono se midió tarde (después de esperar a que el bloqueo del seguidor terminara, cuando el seguidor ya se había puesto al día). El punto de medida correcto es el
instante en que el COMMIT devuelve el control: se lee flush_lsn de la primaria en ese momento y se compara con el LSN de la transacción."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = '''            rc, out, err = L.sql("pg-aws", script.format(p=label), stdin=script.format(p=label), timeout=30)
            box.update(rc=rc, out=out, dur=time.time() - t0)'''
new = '''            rc, out, err = L.sql("pg-aws", script.format(p=label), stdin=script.format(p=label), timeout=30)
            box.update(rc=rc, out=out, dur=time.time() - t0)
            lsn_tx = next((l.split("=")[1] for l in out.splitlines() if l.startswith("LSN0=")), None)
            if lsn_tx:    # en el instante en que el COMMIT devolvió el control, ¿ya había confirmado el seguidor (flush) esa transacción?
                box["flush_ge_al_volver"] = q1("pg-aws", f"SELECT coalesce(flush_lsn >= '{lsn_tx}'::pg_lsn, false) FROM pg_stat_replication WHERE application_name='sub_oci'")
                box["flush_al_volver"] = q1("pg-aws", "SELECT flush_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")'''
assert old in s
s = s.replace(old, new)
old = '''        return {"duracion_del_commit_s": round(box.get("dur", 0), 2), "durante_la_espera": mid, "fila_en_el_seguidor_al_volver_el_commit": row, "LSN_de_la_transaccion": lsn0,'''
new = '''        return {"duracion_del_commit_s": round(box.get("dur", 0), 2), "durante_la_espera": mid, "fila_en_el_seguidor_al_terminar_el_bloqueo": row, "LSN_de_la_transaccion": lsn0,
                "AL_VOLVER_EL_COMMIT_flush_lsn_del_seguidor": box.get("flush_al_volver"), "AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion": box.get("flush_ge_al_volver"),'''
assert old in s
s = s.replace(old, new)
old = '''          and s["fila_en_el_seguidor_al_volver_el_commit"] == "1" and s["flush_lsn_mayor_o_igual_que_el_LSN_de_la_transaccion"] == "t"
          and a["duracion_del_commit_s"] < 1.0 and a["fila_en_el_seguidor_al_volver_el_commit"] == "0")'''
new = '''          and s["fila_en_el_seguidor_al_terminar_el_bloqueo"] == "1" and s["AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion"] == "t"
          and a["duracion_del_commit_s"] < 1.0 and a["AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion"] == "f")'''
assert old in s
s = s.replace(old, new)
s = s.replace("al volver el control asíncrono NO espera y la fila queda ausente", "al volver el control asíncrono NO espera")
s = s.replace("con el seguidor retenido el COMMIT espera (SyncRep) hasta que la fila está en el seguidor con flush_lsn >= LSN de la transacción; el control asíncrono NO espera y la fila queda ausente",
              "con el seguidor retenido el COMMIT espera (SyncRep) y al volver el seguidor YA había confirmado (flush_lsn >= LSN de la transacción); el control asíncrono NO espera y al volver el seguidor aún NO había confirmado")
p.write_text(s)
print("ok")
