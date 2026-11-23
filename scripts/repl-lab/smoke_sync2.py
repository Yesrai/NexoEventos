#!/usr/bin/env python3
"""Segundo humo (reversible, sin recrear nada): (a) confirma con pg_stat_activity que el COMMIT espera en 'SyncRep' cuando el seguidor está desconectado y qué ve otra sesión;
(b) induce un retraso de aplicación REAL bloqueando con LOCK la tabla en el seguidor (min_apply_delay no retrasó los commits síncronos en el primer humo)."""
import json, subprocess, sys, time
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.as_posix())
import labctl as L

out = {}
assert L.sql("pg-aws", "ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (sub_oci)'")[0] == 0
L.sql("pg-aws", "SELECT pg_reload_conf()")
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'on')")
time.sleep(2)


def commit_in_bg(payload):
    return subprocess.Popen(["docker", "exec", L.cname("pg-aws"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c", f"INSERT INTO lab_bulk(payload) VALUES ('{payload}')"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# (a) seguidor desconectado
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
time.sleep(1.5)
t0 = time.time(); p = commit_in_bg("espera_a")
time.sleep(3)
out["a"] = {"commit_sigue_esperando": p.poll() is None,
            "wait_event_en_pg_stat_activity": L.sql("pg-aws", "SELECT coalesce(string_agg(wait_event_type||'/'||wait_event, ','),'(ninguno)') FROM pg_stat_activity WHERE query LIKE 'INSERT INTO lab_bulk%espera_a%' AND pid <> pg_backend_pid()")[1],
            "filas_visibles_para_otra_sesion_en_primaria": L.sql("pg-aws", "SELECT count(*) FROM lab_bulk WHERE payload='espera_a'")[1],
            "filas_en_seguidor": L.sql("pg-oci", "SELECT count(*) FROM lab_bulk WHERE payload='espera_a'")[1]}
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE")
p.wait(30)
out["a"]["liberado_tras_s"] = round(time.time() - t0, 1)

# (b) retraso real: una transacción en el seguidor bloquea la tabla 4 s; el apply worker espera y los COMMIT síncronos de la primaria también
holder = subprocess.Popen(["docker", "exec", "-i", L.cname("pg-oci"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                           "BEGIN; LOCK TABLE lab_bulk IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
t1 = time.time(); p2 = commit_in_bg("retraso_b")
time.sleep(2)
mid = p2.poll() is None
p2.wait(30)
out["b"] = {"commit_espero_mientras_la_tabla_estaba_bloqueada_en_el_seguidor": mid, "commit_tardo_s": round(time.time() - t1, 1)}
holder.wait(30)

# restaurar
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'off')")
L.sql("pg-aws", "ALTER SYSTEM RESET synchronous_standby_names")
L.sql("pg-aws", "SELECT pg_reload_conf()")
time.sleep(1)
out["restaurado"] = {"sync_names": L.sql("pg-aws", "SHOW synchronous_standby_names")[1], "suscripcion": L.sql("pg-oci", "SELECT subenabled::text||' sync='||subsynccommit FROM pg_subscription")[1]}
print(json.dumps(out, indent=2, ensure_ascii=False))
