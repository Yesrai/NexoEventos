"""T5 — puertas de solo lectura con un `aws` simulado: pasan solo con todo en orden; sin sesión se detiene; nunca se invoca una orden que cambie algo."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/t5-puertas-solo-lectura.sh"


def fake(tmp, **o):
    cfg = {"acc": "123456789012", "multiaz": "True", "rds": "stopped", "asg": "0\t0", "ec2": "0", "ami": "available", "acm": "ISSUED", "secret": "nexoeventos/academy/backend-env", **o}
    log = tmp / "aws.log"; log.write_text("")
    b = tmp / "aws"; b.write_text(f'''#!/usr/bin/env bash
echo "$*" >> "{log}"
case "$*" in
 *"sts get-caller-identity"*) [ "{cfg['acc']}" = NONE ] && exit 255; echo "{cfg['acc']}";;
 *"configure get region"*) echo us-east-1;;
 *"MultiAZ"*) echo "{cfg['multiaz']}";;
 *"DBInstanceStatus"*) echo "{cfg['rds']}";;
 *"describe-auto-scaling-groups"*) printf '{cfg['asg']}\\n';;
 *"describe-instances"*) echo "{cfg['ec2']}";;
 *"describe-images"*) echo "{cfg['ami']}";;
 *"describe-certificate"*) echo "{cfg['acm']}";;
 *"describe-secret"*) echo "{cfg['secret']}";;
esac
'''); b.chmod(0o755)
    tf = tmp / "t.tfvars"; tf.write_text('expected_account_id = "123456789012"\nami_id = "ami-0abc"\ncertificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/x"\n')
    return b, tf, log


def run(tmp, **o):
    b, tf, log = fake(tmp, **o)
    p = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env={**os.environ, "AWS_BIN": str(b), "T5_TFVARS": str(tf), "T5_OUT": str(tmp / "out")})
    return p, json.loads((tmp / "out/puertas.json").read_text()), log.read_text()


def test_todo_en_orden_pasa_y_no_imprime_la_cuenta(tmp_path):
    p, d, log = run(tmp_path); assert p.returncode == 0 and d["ok"] and "123456789012" not in p.stdout + p.stderr and "TODAS las puertas" in p.stdout
    assert oct((tmp_path / "out/puertas.json").stat().st_mode)[-3:] == "600"


def test_sin_sesion_o_cuenta_distinta_se_detiene_sin_mas_llamadas(tmp_path):
    p, d, log = run(tmp_path, acc="NONE"); assert p.returncode == 1 and not d["ok"] and log.count("\n") == 1
    t2 = tmp_path / "b"; t2.mkdir(); p, d, log = run(t2, acc="999999999999"); assert p.returncode == 1 and log.count("\n") == 1


def test_cada_puerta_fallida_impide_encender(tmp_path):
    for i, o in enumerate(({"multiaz": "False"}, {"asg": "2\t2"}, {"ec2": "2"}, {"ami": "failed"}, {"acm": "EXPIRED"}, {"secret": "otro"})):
        t = tmp_path / str(i); t.mkdir(); p, d, _ = run(t, **o); assert p.returncode == 1 and not d["ok"], o


def test_solo_ordenes_de_lectura():
    s = SCRIPT.read_text()
    for prohibido in (" create", " delete", " terminate", " stop-", " start-", " modify", " update-", " put-", " run-instances", " apply"): assert prohibido not in s
    assert set(__import__("re").findall(r'"\$AWS" (\S+ \S+)', s)) <= {"sts get-caller-identity", "configure get", "rds describe-db-instances", "autoscaling describe-auto-scaling-groups", "ec2 describe-instances", "ec2 describe-images", "acm describe-certificate", "secretsmanager describe-secret"}
