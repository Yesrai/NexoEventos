#!/usr/bin/env python3
"""Prueba controlada de failover Multi-AZ de la RDS de V1 (AWS Academy). No toca Terraform, datos ni respaldos.

  --preflight  solo lectura: estado RDS, conexiones activas, huella de datos, /healthz y conectividad EC2 -> RDS.
  --execute    provoca `reboot-db-instance --force-failover` y mide. Exige NEXO_ALLOW_CLOUD_CHANGES=YES y --i-am-authorized.
Mide a la vez: /healthz público (1 s, desde esta estación), PostgreSQL desde la EC2 (`select 1` cada 1 s, SSM en segundo plano),
estado/AZ de RDS (2 s) y eventos RDS. Compara la huella antes y después. Nunca imprime endpoints, IDs de cuenta ni secretos.
Uso: backend/.venv/bin/python scripts/cloud/rds-failover-test.py --preflight|--execute --out docs/evidencias/multicloud/aws/AAAAMMDD-failover
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RDS_ID = "nexoeventos-academy-postgres"
BASE = "https://nexoeventos-demo.duckdns.org"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load("flow", "scripts/cloud/verify-controlled-flow.py")  # ssm(), FINGERPRINT, MIG (solo lecturas aquí)


def now():
    return datetime.now(timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def aws(*args):
    return subprocess.check_output(["aws", *args], text=True).strip()


def rds_state():
    d = json.loads(aws("rds", "describe-db-instances", "--db-instance-identifier", RDS_ID, "--query",
                       "DBInstances[0].{s:DBInstanceStatus,m:MultiAZ,p:AvailabilityZone,q:SecondaryAvailabilityZone}", "--output", "json"))
    return d


ACTIVITY = """
SELECT 'sesiones_otras='||count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();
SELECT 'activas='||count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND state='active';
SELECT 'idle_in_transaction='||count(*) FROM pg_stat_activity WHERE datname=current_database() AND state LIKE 'idle in transaction%';
SELECT 'transacciones_abiertas>5s='||count(*) FROM pg_stat_activity WHERE xact_start < now()-interval '5 seconds' AND pid<>pg_backend_pid();
SELECT 'ultimo_acceso_registrado='||coalesce(max(created_at)::text,'-') FROM access_logs;
SELECT 'ultima_reserva='||coalesce(max(created_at)::text,'-') FROM reservations;
"""


def health():
    r = subprocess.run(["curl", "--connect-timeout", "3", "--max-time", "5", "-sS", "-o", "/dev/null", "-w", "%{http_code} %{time_total}", f"{BASE}/healthz"],
                       capture_output=True, text=True)
    return (r.stdout.strip() or "000 0").split()


def preflight():
    out = {"hora": iso(now()), "rds": rds_state(), "healthz": health()}
    out["actividad"] = C.ssm(ACTIVITY, "failover: actividad (lectura)").strip().split("\n")
    out["huella"] = C.ssm(C.FINGERPRINT, "failover: huella previa (lectura)").strip().split("\n")
    return out


PROBE_START = (C.MIG + 'export DB_URL PGCONNECT_TIMEOUT=2\n'
               "nohup bash -c 'end=$((SECONDS+@DUR@)); while [ $SECONDS -lt $end ]; do t=$(date +%s.%N); "
               'if psql "$DB_URL" -Atc "select 1" >/dev/null 2>&1; then echo "$t 1"; else echo "$t 0"; fi; sleep 1; done > /tmp/pgprobe.log\' >/dev/null 2>&1 &\n'
               "disown; echo iniciado\n")

PROBE_SUMMARY = r"""awk 'BEGIN{OFS=" "} {n++; if($2==0){f++; if(!a)a=$1; b=$1; c=0} else if(a&&!c&&$1>b){c=$1} if($2==1&&!a)okpre=$1}
END{print "muestras="n, "fallos="f+0, "primer_fallo="a, "ultimo_fallo="b, "primer_ok_despues="c}' /tmp/pgprobe.log"""


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preflight", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--i-am-authorized", action="store_true")
    ap.add_argument("--window", type=int, default=420, help="segundos máximos de observación tras el failover")
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    if a.preflight:
        res = preflight()
        (out / "preflight.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or not a.i_am_authorized:
        sys.exit("Bloqueado: requiere NEXO_ALLOW_CLOUD_CHANGES=YES y --i-am-authorized (autorización explícita).")
    pre = preflight()
    st = pre["rds"]
    if not (st["s"] == "available" and st["m"] is True and st["q"]):
        sys.exit(f"Estado RDS no apto para la prueba: {st}")
    if pre["healthz"][0] != "200":
        sys.exit("healthz no responde 200 antes de la prueba.")
    busy = {l.split("=")[0]: l.split("=", 1)[1] for l in pre["actividad"] if "=" in l}
    if busy.get("idle_in_transaction") != "0" or busy.get("transacciones_abiertas>5s") != "0":
        sys.exit(f"Hay transacciones abiertas: {busy}")

    iid = aws("ec2", "describe-instances", "--filters", "Name=tag:Name,Values=nexoeventos-academy-app", "Name=instance-state-name,Values=running",
              "--query", "Reservations[0].Instances[0].InstanceId", "--output", "text")
    C.ssm("SELECT 1;", "failover: conectividad")  # confirma ruta SSM->RDS antes de provocar el fallo
    aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", "failover: sonda PostgreSQL 1 s",
        "--parameters", json.dumps({"commands": [PROBE_START.replace("@DUR@", str(a.window))]}), "--query", "Command.CommandId", "--output", "text")
    time.sleep(5)

    http, rdsline, stop = [], [], threading.Event()

    def http_loop():
        while not stop.is_set():
            t = now()
            code, secs = health()
            http.append({"t": iso(t), "code": code, "s": secs})
            time.sleep(max(0, 1 - (now() - t).total_seconds()))

    def rds_loop():
        while not stop.is_set():
            t = now()
            try:
                s = rds_state()
            except Exception as e:  # noqa: BLE001 - se registra, no se oculta
                s = {"error": str(e)[-120:]}
            rdsline.append({"t": iso(t), **s})
            time.sleep(2)

    ths = [threading.Thread(target=http_loop, daemon=True), threading.Thread(target=rds_loop, daemon=True)]
    for th in ths:
        th.start()
    time.sleep(8)  # línea base con servicio estable

    t_cmd = now()
    with open(ROOT / "work/operacion/sesiones-cloud.log", "a") as f:
        f.write(f"{iso(t_cmd)} academy failover: reboot-db-instance --force-failover (autorizado)\n")
    r = subprocess.run(["aws", "rds", "reboot-db-instance", "--db-instance-identifier", RDS_ID, "--force-failover", "--query", "DBInstance.DBInstanceStatus", "--output", "text"],
                       capture_output=True, text=True)
    t_ret = now()
    print("reboot:", r.stdout.strip() or r.stderr.strip()[-300:])
    if r.returncode:
        stop.set()
        (out / "error.txt").write_text(r.stderr[-600:])
        sys.exit("AWS rechazó el failover (ver error.txt). Nada que revertir.")

    # espera: RDS available con AZ primaria cambiada y healthz 200 estable 15 s, o ventana agotada
    deadline = time.time() + a.window
    recovered = None
    while time.time() < deadline:
        time.sleep(3)
        last = rdsline[-1] if rdsline else {}
        recent = http[-15:]
        if last.get("s") == "available" and last.get("p") != st["p"] and len(recent) == 15 and all(h["code"] == "200" for h in recent):
            recovered = now()
            break
    stop.set()
    for th in ths:
        th.join(timeout=10)
    time.sleep(2)

    post = {"rds": rds_state(), "healthz": health()}
    post["huella"] = C.ssm(C.FINGERPRINT, "failover: huella posterior (lectura)").strip().split("\n")
    # la sonda de la EC2 puede seguir corriendo hasta su ventana; el resumen usa lo escrito hasta ahora
    cid = aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", "failover: resumen sonda",
              "--parameters", json.dumps({"commands": [PROBE_SUMMARY]}), "--query", "Command.CommandId", "--output", "text")
    time.sleep(6)
    summary = aws("ssm", "get-command-invocation", "--command-id", cid, "--instance-id", iid, "--query", "StandardOutputContent", "--output", "text")
    events = aws("rds", "describe-events", "--source-type", "db-instance", "--source-identifier", RDS_ID, "--duration", "30",
                 "--query", "Events[].[Date,Message]", "--output", "text")

    bad = [h for h in http if h["code"] != "200"]
    res = {
        "comando_enviado": iso(t_cmd), "comando_retorno": iso(t_ret), "recuperado_estable": iso(recovered) if recovered else None,
        "rds_antes": st, "rds_despues": post["rds"],
        "healthz_total": len(http), "healthz_no200": len(bad),
        "healthz_primer_fallo": bad[0]["t"] if bad else None, "healthz_ultimo_fallo": bad[-1]["t"] if bad else None,
        "healthz_codigos": sorted({h["code"] for h in http}),
        "sonda_postgres_ec2": summary.strip(), "huella_antes": pre["huella"], "huella_despues": post["huella"],
        "huella_igual": pre["huella"] == post["huella"], "eventos_rds": events.strip().split("\n"),
    }
    (out / "resultado.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    (out / "healthz-1s.json").write_text(json.dumps(http) + "\n")
    (out / "rds-2s.json").write_text(json.dumps(rdsline) + "\n")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
