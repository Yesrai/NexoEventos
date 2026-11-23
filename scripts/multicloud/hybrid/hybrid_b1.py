#!/usr/bin/env python3
"""B1 · encendido CONTROLADO de la EC2 y la RDS de V1 para la prueba híbrida, con parada garantizada. NADA de esto se ejecuta hasta que la propietaria lo autoriza (frase + variable de entorno + etapa B registrada).
Solo enciende y apaga los DOS recursos exactos del proyecto; el cliente AWS rechaza cualquier otra operación (lista blanca): no modifica, no crea, no borra, no toca Auto Scaling, IAM, redes ni DNS.
  preflight  --credit-remaining USD --max-minutes N        solo lectura: identidad, recursos correctos y detenidos, Auto Scaling a 0, presupuesto
  (con --reuse-ec2: la EC2 ya encendida se reutiliza, se comprueba que no haya operaciones críticas y solo se enciende la RDS; `--gate-stage B1` exige el subpaso B1 y no la etapa B)
  start      --credit-remaining USD --max-minutes N --confirm "ENCENDER EC2 Y RDS DE V1 PARA B1" --state-file F --gate-state G     (NEXO_ALLOW_CLOUD_CHANGES=YES; etapa B «en curso» en el controlador)
  stop       [--state-file F]                              apaga EC2 y RDS y verifica `stopped` (siempre permitido, idempotente, reintenta); ante CUALQUIER error de start se ejecuta solo
  watchdog   --state-file F                                proceso aparte, lanzado ANTES de encender: a la hora límite apaga todo aunque el resto haya muerto
  status                                                   solo lectura
Presupuesto: techo 0,50 USD; tarifa estimada (NO verificada con la facturación) ≈ 0,06 USD/h entre EC2 t3.small, RDS db.t3.micro Multi-AZ y almacenamiento; crédito mínimo exigido 10 USD."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# El ID de cuenta ya no está en el código: se exige por entorno (NEXO_EXPECTED_ACCOUNT_ID). Sin él, identity() se detiene (nunca coincide con una cuenta real).
EXPECT = {"account": os.environ.get("NEXO_EXPECTED_ACCOUNT_ID", "000000000000"), "role": "assumed-role/voclabs/", "region": "us-east-1", "ec2_name": "nexoeventos-academy-app", "project": "NexoEventos", "rds": "nexoeventos-academy-postgres", "asg": "nexoeventos-academy-v2-asg"}
HOURLY_USD = 0.06
BUDGET_USD = 0.50
MIN_CREDIT_USD = 10.0
CONFIRM = "ENCENDER EC2 Y RDS DE V1 PARA B1"
ALLOWED = {("sts", "get-caller-identity"), ("ec2", "describe-instances"), ("ec2", "describe-instance-status"), ("ec2", "start-instances"), ("ec2", "stop-instances"),
           ("rds", "describe-db-instances"), ("rds", "start-db-instance"), ("rds", "stop-db-instance"), ("autoscaling", "describe-auto-scaling-groups"),
           ("ssm", "list-commands"), ("ssm", "describe-sessions"), ("cloudwatch", "get-metric-statistics")}


class B1Error(Exception):
    pass


def estimate_usd(minutes: float) -> float:
    return round(HOURLY_USD * minutes / 60.0, 4)


class Aws:
    def __init__(self, profile="nexoeventos-lab", run=None, region=EXPECT["region"]):
        self.profile, self.region = profile, region
        self._run = run or self._subprocess

    @staticmethod
    def _subprocess(argv):
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, env={**os.environ, "AWS_PAGER": ""})
        if r.returncode != 0:
            raise B1Error("aws falló: " + (r.stderr.strip().splitlines() or ["?"])[-1][:160])
        return r.stdout

    def call(self, service, op, *args):
        if (service, op) not in ALLOWED:
            raise B1Error(f"operación no permitida: {service} {op}")                          # lista blanca: solo encender/apagar/leer estos recursos
        out = self._run(["aws", "--profile", self.profile, "--region", self.region, service, op, *args, "--output", "json"])
        return json.loads(out) if out.strip() else {}


class B1:
    def __init__(self, aws: Aws, sleep=time.sleep, now=time.time):
        self.aws, self.sleep, self.now = aws, sleep, now
        self.ec2_id: str | None = None

    # ---------------- lectura
    def identity(self):
        i = self.aws.call("sts", "get-caller-identity")
        if i.get("Account") != EXPECT["account"] or EXPECT["role"] not in i.get("Arn", ""):
            raise B1Error("identidad distinta de la esperada (cuenta/rol de AWS Academy de NexoEventos): se detiene")

    def ec2(self):
        d = self.aws.call("ec2", "describe-instances", "--filters", f"Name=tag:Name,Values={EXPECT['ec2_name']}", "--query", "Reservations[].Instances[].{id:InstanceId,state:State.Name,proj:Tags[?Key==`Project`]|[0].Value}")
        if not isinstance(d, list) or len(d) != 1:
            raise B1Error(f"se esperaba exactamente 1 instancia «{EXPECT['ec2_name']}» y hay {len(d) if isinstance(d, list) else '?'}")
        if d[0].get("proj") != EXPECT["project"]:
            raise B1Error("la instancia no lleva la etiqueta Project=NexoEventos")
        self.ec2_id = d[0]["id"]; return d[0]

    def rds(self):
        d = self.aws.call("rds", "describe-db-instances", "--db-instance-identifier", EXPECT["rds"], "--query", "DBInstances[].{status:DBInstanceStatus,engine:Engine,ver:EngineVersion,multi:MultiAZ,replicas:ReadReplicaDBInstanceIdentifiers,auto:AutomaticRestartTime}")
        if not isinstance(d, list) or len(d) != 1 or d[0].get("engine") != "postgres":
            raise B1Error("la RDS esperada no existe o no es PostgreSQL")
        return d[0]

    def asg_desired(self):
        d = self.aws.call("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", EXPECT["asg"], "--query", "AutoScalingGroups[].{d:DesiredCapacity,i:length(Instances)}")
        return d[0] if isinstance(d, list) and d else {"d": 0, "i": 0}

    def critical_ops(self) -> dict:
        """¿Hay operaciones críticas activas en la EC2? SOLO LECTURA: comandos SSM en curso/pendientes, sesiones SSM activas y CPU de los últimos 30 min (una CPU alta sugiere trabajo en curso)."""
        i = self.ec2_id
        cmds = []
        cmds += self.aws.call("ssm", "list-commands", "--instance-id", i, "--filters", "key=Status,value=InProgress", "--query", "Commands[].CommandId") or []
        cmds += self.aws.call("ssm", "list-commands", "--filters", "key=Status,value=Pending", "--query", f"Commands[?contains(InstanceIds, `{i}`)].CommandId") or []      # (la API no admite instance-id junto a Pending)
        sess = self.aws.call("ssm", "describe-sessions", "--state", "Active", "--filters", f"key=Target,value={i}", "--query", "Sessions[].SessionId") or []
        end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now())); start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now() - 1800))
        cpu = self.aws.call("cloudwatch", "get-metric-statistics", "--namespace", "AWS/EC2", "--metric-name", "CPUUtilization", "--dimensions", f"Name=InstanceId,Value={i}", "--start-time", start, "--end-time", end,
                            "--period", "900", "--statistics", "Average", "--query", "sort_by(Datapoints,&Timestamp)[].Average") or []
        return {"comandos_ssm": len(cmds), "sesiones_ssm": len(sess), "cpu_media_30min": [round(x, 1) for x in cpu], "critica": bool(cmds or sess or any(x > 30 for x in cpu))}

    def preflight(self, credit_remaining: float, max_minutes: float, reuse_ec2: bool = False) -> dict:
        self.identity(); e, r, g = self.ec2(), self.rds(), self.asg_desired()
        blockers = []; crit = None
        if reuse_ec2:
            if e["state"] != "running": blockers.append(f"EC2 `{e['state']}`: con --reuse-ec2 se espera `running` (si está detenida, B1 estándar)")
            else:
                crit = self.critical_ops()
                if crit["critica"]: blockers.append(f"hay actividad en la EC2 que podría ser una operación crítica: {crit}")
        elif e["state"] != "stopped": blockers.append(f"EC2 `{e['state']}`: B1 parte de `stopped`")
        if r["status"] != "stopped": blockers.append(f"RDS `{r['status']}`: B1 parte de `stopped`")
        if g.get("d") or g.get("i"): blockers.append("Auto Scaling de V2 tiene capacidad > 0: no se enciende nada con instancias de V2 activas")
        est = estimate_usd(max_minutes)
        if credit_remaining < MIN_CREDIT_USD: blockers.append(f"crédito {credit_remaining} USD < {MIN_CREDIT_USD} USD exigidos")
        if est > BUDGET_USD: blockers.append(f"gasto estimado {est} USD > techo {BUDGET_USD} USD")
        if not (5 <= max_minutes <= 240): blockers.append("--max-minutes debe estar entre 5 y 240")
        return {"ok": not blockers, "blockers": blockers, "ec2": e["state"], "rds": r["status"], "rds_multi_az": r.get("multi"), "rds_replicas": r.get("replicas") or [], "rds_reinicio_automatico": r.get("auto"),
                "gasto_estimado_usd": est, "tarifa_estimada_usd_h": HOURLY_USD, "reutiliza_ec2": reuse_ec2, "operaciones_criticas_ec2": crit, "instancia_ec2": self.ec2_id, "nota_costes": "estimación con tarifas públicas, no verificada con la facturación"}

    # ---------------- escritura (solo estos dos recursos)
    def _wait(self, fn, ok, timeout_s, poll_s=15):
        end = self.now() + timeout_s
        while self.now() < end:
            v = fn()
            if ok(v): return v
            self.sleep(poll_s)
        raise B1Error("tiempo agotado esperando el estado")

    def start(self, state_path: Path, max_minutes: float, log=print, reuse_ec2: bool = False) -> dict:
        start_t = self.now(); st = {"inicio": start_t, "limite": start_t + max_minutes * 60, "ec2": self.ec2()["id"], "ec2_reutilizada": reuse_ec2, "estado": "encendiendo"}; self._save(state_path, st)
        log("RDS: start-db-instance"); self.aws.call("rds", "start-db-instance", "--db-instance-identifier", EXPECT["rds"])
        self._wait(lambda: self.rds()["status"], lambda s: s == "available", 25 * 60)
        if not reuse_ec2:
            log("EC2: start-instances"); self.aws.call("ec2", "start-instances", "--instance-ids", st["ec2"])
            self._wait(lambda: self.ec2()["state"], lambda s: s == "running", 10 * 60)
        else:
            self._wait(lambda: self.ec2()["state"], lambda s: s == "running", 60)                  # la EC2 ya encendida NO se toca
        st["estado"] = "encendidas"; st["encendidas"] = self.now(); self._save(state_path, st); return st

    def stop_all(self, state_path: Path | None = None, log=print, attempts: int = 3) -> dict:
        """Apaga EC2 y RDS y VERIFICA `stopped`. Idempotente. Si la RDS está `starting`/`backing-up`/`modifying`, espera a `available` antes de pararla (RDS no permite parar en esos estados)."""
        res = {"ec2": None, "rds": None, "errores": []}
        for i in range(attempts):
            try:
                e = self.ec2()
                if e["state"] in ("running", "pending"):
                    log("EC2: stop-instances"); self.aws.call("ec2", "stop-instances", "--instance-ids", e["id"])
                r = self.rds()
                if r["status"] in ("starting", "backing-up", "modifying", "rebooting", "configuring-enhanced-monitoring", "storage-optimization"):
                    self._wait(lambda: self.rds()["status"], lambda s: s in ("available", "stopped"), 20 * 60)
                    r = self.rds()
                if r["status"] == "available":
                    log("RDS: stop-db-instance"); self.aws.call("rds", "stop-db-instance", "--db-instance-identifier", EXPECT["rds"])
                self._wait(lambda: self.ec2()["state"], lambda s: s == "stopped", 10 * 60)
                self._wait(lambda: self.rds()["status"], lambda s: s == "stopped", 20 * 60)
                res.update(ec2="stopped", rds="stopped"); break
            except B1Error as ex:
                res["errores"].append(str(ex)[:120]); self.sleep(10)
        else:
            res["ec2"], res["rds"] = self._safe(lambda: self.ec2()["state"]), self._safe(lambda: self.rds()["status"])
        if state_path:
            st = self._load(state_path); st["estado"] = "detenidas" if res["rds"] == "stopped" and res["ec2"] == "stopped" else "PARADA_INCOMPLETA"; self._save(state_path, st)
        return res

    @staticmethod
    def _safe(fn):
        try: return fn()
        except Exception: return "desconocido"

    @staticmethod
    def _save(p, st):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f: json.dump(st, f)

    @staticmethod
    def _load(p):
        try: return json.loads(Path(p).read_text())
        except (OSError, ValueError): return {}

    def watchdog(self, state_path: Path, log=print, poll_s=30):
        """Hasta la hora límite; si el estado ya es `detenidas`, termina. Si llega la hora límite, apaga todo."""
        while True:
            st = self._load(state_path)
            if st.get("estado") == "detenidas": return {"resultado": "ya detenidas"}
            if self.now() >= st.get("limite", 0): return self.stop_all(state_path, log)
            self.sleep(poll_s)


def gate_b_en_curso(gate_state_file: str, stage: str = "B") -> bool:
    try:
        return json.loads(Path(gate_state_file).read_text())["stages"][stage]["estado"] == "en curso"
    except (OSError, ValueError, KeyError):
        return False


def main(argv=None, aws: Aws | None = None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["preflight", "start", "stop", "watchdog", "status"]); ap.add_argument("--profile", default="nexoeventos-lab")
    ap.add_argument("--credit-remaining", type=float, default=0.0); ap.add_argument("--max-minutes", type=float, default=90.0); ap.add_argument("--confirm", default="")
    ap.add_argument("--state-file", default=str(Path.home() / ".nexoeventos/hybrid-b1-state.json")); ap.add_argument("--gate-state", default="work/hybrid-estado.json")
    ap.add_argument("--reuse-ec2", action="store_true", help="la EC2 ya está encendida: se reutiliza (no se apaga ni se vuelve a encender); solo se enciende la RDS"); ap.add_argument("--gate-stage", default="B", help="etapa/subpaso «en curso» exigido en el controlador (B1 = solo este paso)")
    a = ap.parse_args(argv); b = B1(aws or Aws(a.profile)); sp = Path(a.state_file)
    try:
        if a.cmd == "preflight":
            r = b.preflight(a.credit_remaining, a.max_minutes, a.reuse_ec2); print(json.dumps(r, indent=1, ensure_ascii=False)); return 0 if r["ok"] else 1
        if a.cmd == "status":
            b.identity(); print(json.dumps({"ec2": b.ec2()["state"], "rds": b.rds()["status"]})); return 0
        if a.cmd == "stop":
            r = b.stop_all(sp if sp.exists() else None); print(json.dumps(r)); return 0 if r["ec2"] == "stopped" and r["rds"] == "stopped" else 1
        if a.cmd == "watchdog":
            print(json.dumps(b.watchdog(sp))); return 0
        # start
        if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or a.confirm != CONFIRM:
            print("RECHAZADO: falta NEXO_ALLOW_CLOUD_CHANGES=YES y la frase exacta.", file=sys.stderr); return 3
        if not gate_b_en_curso(a.gate_state, a.gate_stage):
            print(f"RECHAZADO: «{a.gate_stage}» no está «en curso» en el controlador (hybrid_gate.py start --stage {a.gate_stage} …).", file=sys.stderr); return 3
        pre = b.preflight(a.credit_remaining, a.max_minutes, a.reuse_ec2)
        if not pre["ok"]:
            print(json.dumps(pre, indent=1, ensure_ascii=False)); return 1
        sp.parent.mkdir(parents=True, exist_ok=True)
        b._save(sp, {"limite": b.now() + a.max_minutes * 60, "estado": "armado"})
        if aws is None:                                                                         # watchdog en un proceso APARTE, ANTES de encender: si este proceso muere, igualmente se apaga todo
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watchdog", "--state-file", str(sp), "--profile", a.profile], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            st = b.start(sp, a.max_minutes, reuse_ec2=a.reuse_ec2)
        except BaseException as e:  # noqa: BLE001 — cualquier error o Ctrl-C: se apaga todo
            print(f"ERROR en el encendido ({type(e).__name__}): se apagan EC2 y RDS", file=sys.stderr)
            r = b.stop_all(sp); print(json.dumps(r)); return 1
        print(json.dumps({"estado": st["estado"], "limite_unix": st["limite"], "apagado_automatico": "watchdog + `hybrid_b1.py stop`"})); return 0
    except B1Error as e:
        print(f"ERROR: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
