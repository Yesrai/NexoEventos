#!/usr/bin/env python3
"""Humo del mecanismo SÍNCRONO sobre el laboratorio YA encendido (sin recrear contenedores ni borrar volúmenes). Es reversible: al final restaura la configuración.
Comprueba (1) que la suscripción lógica aparece como candidata síncrona, (2) coste en latencia de confirmación, (3) que con el seguidor desconectado el COMMIT se bloquea y
se libera al volver, y (4) el efecto de un retraso de aplicación (min_apply_delay) sobre la latencia de confirmación."""
import json, subprocess, sys, time
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.as_posix())
import labctl as L

out = {}


def pgbench(secs=3):
    r = subprocess.run(["docker", "exec", L.cname("pg-aws"), "pgbench", "-n", "-U", "postgres", "-c", "1", "-T", str(secs), "-f", "/tmp/ins.sql", "nexoeventos"], capture_output=True, text=True, timeout=60)
    g = lambda k: next((l.split("=")[1].split()[0] for l in r.stdout.splitlines() if l.startswith(k)), None)
    return {"tps": g("tps"), "latencia_media_ms": g("latency average")}


subprocess.run(["docker", "exec", L.cname("pg-aws"), "sh", "-c", "echo \"INSERT INTO lab_bulk(payload) VALUES (md5(random()::text));\" > /tmp/ins.sql"], check=True)
out["0_asincrona"] = pgbench()
assert L.sql("pg-aws", "ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (sub_oci)'")[0] == 0
assert L.sql("pg-aws", "SELECT pg_reload_conf()")[1] == "t"
for _ in range(20):
    st = L.sql("pg-aws", "SELECT string_agg(application_name||':'||state||':'||sync_state, ',') FROM pg_stat_replication")[1]
    if "quorum" in st or ":sync" in st:
        break
    time.sleep(0.5)
out["1_estado_en_pg_stat_replication"] = st
out["1_sync_default_suscripcion_off"] = pgbench()
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'on')")
time.sleep(1)
out["2_sync_suscripcion_on"] = pgbench()

# seguidor desconectado: el COMMIT debe bloquearse (la fila ya es visible en la primaria; la confirmación al cliente no llega)
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
time.sleep(1.5)
t0 = time.time()
p = subprocess.Popen(["docker", "exec", L.cname("pg-aws"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c", "INSERT INTO lab_bulk(payload) VALUES ('bloqueada')"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(4)
blocked = p.poll() is None
visible_en_primaria = L.sql("pg-aws", "SELECT count(*) FROM lab_bulk WHERE payload='bloqueada'")[1]
visible_en_seguidor = L.sql("pg-oci", "SELECT count(*) FROM lab_bulk WHERE payload='bloqueada'")[1]
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE")
p.wait(30)
out["3_seguidor_desconectado"] = {"commit_bloqueado_4s": blocked, "fila_visible_en_primaria_mientras_esperaba": visible_en_primaria, "fila_visible_en_seguidor_mientras_esperaba": visible_en_seguidor,
                                   "commit_liberado_al_volver_el_seguidor_s": round(time.time() - t0, 1)}

# retraso de aplicación: el COMMIT síncrono espera al seguidor
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (min_apply_delay = '2s')")
time.sleep(2)
out["4_min_apply_delay_2s"] = pgbench(6)

# restaurar
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (min_apply_delay = 0)")
L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'off')")
L.sql("pg-aws", "ALTER SYSTEM RESET synchronous_standby_names")
L.sql("pg-aws", "SELECT pg_reload_conf()")
time.sleep(1)
out["restaurado"] = {"sync_names": L.sql("pg-aws", "SHOW synchronous_standby_names")[1], "suscripcion": L.sql("pg-oci", "SELECT subenabled::text||' sync='||subsynccommit FROM pg_subscription")[1]}
print(json.dumps(out, indent=2, ensure_ascii=False))
