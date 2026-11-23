#!/usr/bin/env python3
"""B2 · precheck de SOLO LECTURA en la RDS REAL, ejecutado DENTRO de la EC2 por SSM. La contraseña del administrador (secreto administrado de RDS) se lee dentro de la EC2 con el rol de la instancia, se usa para armar un archivo
de conexión 0600 efímero y se descarta: NUNCA se imprime, no viaja por SSM, no se guarda en logs ni sale de la EC2. El script remoto no despliega ni reinicia nada del backend; solo ejecuta UNA transacción
`BEGIN TRANSACTION READ ONLY` con SELECTs de catálogo y la deshace. Devuelve solo hechos técnicos (versión, privilegios, parámetros, recuentos): ningún dato de negocio.
  build   imprime el script remoto (para revisarlo)   |   run  --instance-id I --secret-id S --endpoint H --confirm "EJECUTAR PASO B2 PRECHECK DE SOLO LECTURA" (NEXO_ALLOW_CLOUD_CHANGES=YES)"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.failover.pg_fence import READONLY_SQL, readonly_verdict  # noqa: E402

CONFIRM = "EJECUTAR PASO B2 PRECHECK DE SOLO LECTURA"
EC2_PY = "/opt/nexoeventos/backend/.venv/bin/python"

REMOTE = r'''
import json, os, shutil, subprocess, sys, tempfile
HOST = os.environ.get("NEXO_B2_HOST", {host!r}); PORT = os.environ.get("NEXO_B2_PORT", "5432"); DB = os.environ.get("NEXO_B2_DB", {dbname!r}); SSL = os.environ.get("NEXO_B2_SSLMODE", "require")
SQL = {sql!r}
out = {{"ok": False}}
tmp = tempfile.mkdtemp(prefix="nexo-b2-"); os.chmod(tmp, 0o700); out["tmpdir"] = os.path.basename(tmp)
try:
    r = subprocess.run(["aws", "secretsmanager", "get-secret-value", "--secret-id", {secret!r}, "--query", "SecretString", "--output", "text"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError("secreto no legible")
    sec = json.loads(r.stdout); user, pw = sec["username"], sec["password"]; del r
    import psycopg
    from psycopg.conninfo import make_conninfo
    f = os.path.join(tmp, "admin.conninfo"); fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh: fh.write(make_conninfo(host=HOST, port=PORT, dbname=DB, user=user, password=pw, sslmode=SSL, connect_timeout="15", application_name="nexo-b2-readonly"))
    del pw, sec
    out["archivo_permisos"] = oct(os.stat(f).st_mode & 0o777)
    with psycopg.connect(open(f).read(), autocommit=True) as c, c.cursor() as cur:
        cur.execute("BEGIN TRANSACTION READ ONLY"); cur.execute("SHOW transaction_read_only"); out["transaction_read_only"] = cur.fetchone()[0]
        cur.execute(SQL); out["hechos"] = cur.fetchone()[0]; cur.execute("ROLLBACK")
    out["ok"] = True
except Exception as e:
    out["error"] = type(e).__name__                                       # solo la CLASE: el mensaje podría incluir datos de conexión
finally:
    try:
        for n in os.listdir(tmp):
            p = os.path.join(tmp, n); open(p, "r+b").write(b"\0" * os.path.getsize(p)); os.remove(p)
    except Exception: pass
    shutil.rmtree(tmp, ignore_errors=True); out["efimero_eliminado"] = not os.path.exists(tmp)
print("NEXO_B2_JSON=" + json.dumps(out, default=str))
'''


def build_remote(schema="public", app_role="nexoeventos_app", endpoint="", dbname="nexoeventos", secret_id="") -> str:
    sql = READONLY_SQL.replace("%(s)s", "'" + schema + "'").replace("%(a)s", "'" + app_role + "'").replace("%%", "%")
    return REMOTE.format(host=endpoint, dbname=dbname, sql=sql, secret=secret_id)


def parse_output(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("NEXO_B2_JSON="):
            return json.loads(line[len("NEXO_B2_JSON="):])
    raise ValueError("sin resultado")


def ssm_run(script: str, instance_id: str, profile="nexoeventos-lab", region="us-east-1", run=None, sleep=time.sleep, timeout_s=240) -> str:
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=120, env={**os.environ, "AWS_PAGER": ""}))
    b64 = base64.b64encode(script.encode()).decode()
    params = {"commands": [f"echo {b64} | base64 -d > /tmp/nexo-b2.py", f"{EC2_PY} /tmp/nexo-b2.py; rc=$?; rm -f /tmp/nexo-b2.py; exit $rc"], "executionTimeout": ["180"]}
    pf = Path(os.path.expanduser("~/.nexoeventos")) / "b2-ssm-params.json"; pf.parent.mkdir(mode=0o700, exist_ok=True); fd = os.open(pf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(params, f)
    try:
        base = ["aws", "--profile", profile, "--region", region, "ssm"]
        r = run([*base, "send-command", "--document-name", "AWS-RunShellScript", "--instance-ids", instance_id, "--comment", "NexoEventos B2 precheck solo lectura", "--parameters", f"file://{pf}", "--query", "Command.CommandId", "--output", "text"])
        if r.returncode != 0: raise RuntimeError("send-command falló")
        cid = r.stdout.strip(); end = time.time() + timeout_s
        while time.time() < end:
            g = run([*base, "get-command-invocation", "--command-id", cid, "--instance-id", instance_id, "--output", "json"])
            if g.returncode == 0:
                d = json.loads(g.stdout)
                if d.get("Status") in ("Success", "Failed", "TimedOut", "Cancelled"):
                    if d["Status"] != "Success": raise RuntimeError(f"SSM {d['Status']}")
                    return d.get("StandardOutputContent", "")
            sleep(5)
        raise RuntimeError("tiempo agotado")
    finally:
        pf.unlink(missing_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["build", "run"]); ap.add_argument("--instance-id"); ap.add_argument("--secret-id"); ap.add_argument("--endpoint"); ap.add_argument("--dbname", default="nexoeventos")
    ap.add_argument("--app-role", default="nexoeventos_app"); ap.add_argument("--confirm", default=""); a = ap.parse_args(argv)
    if a.cmd == "build":
        print(build_remote(app_role=a.app_role, endpoint=a.endpoint or "<endpoint>", dbname=a.dbname, secret_id=a.secret_id or "<secreto>")); return 0
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or a.confirm != CONFIRM:
        print("RECHAZADO: falta NEXO_ALLOW_CLOUD_CHANGES=YES y la frase exacta.", file=sys.stderr); return 3
    try:
        out = parse_output(ssm_run(build_remote(app_role=a.app_role, endpoint=a.endpoint, dbname=a.dbname, secret_id=a.secret_id), a.instance_id))
    except (RuntimeError, ValueError, OSError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr); return 2
    res = {"remoto": {k: v for k, v in out.items() if k != "hechos"}, "veredicto": readonly_verdict(out["hechos"]) if out.get("ok") else None, "hechos": out.get("hechos")}
    print(json.dumps(res, indent=1, default=str, ensure_ascii=False)); return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
