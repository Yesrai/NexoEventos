#!/usr/bin/env python3
"""Respaldo lógico cifrado de la RDS de V1 (reproducible). Requiere RDS y EC2 de V1 encendidas y NEXO_ALLOW_CLOUD_CHANGES=YES.

En la EC2 (vía SSM): `pg_dump -Fc --no-owner --no-acl` → `openssl cms -encrypt` (AES-256-CBC, DER) con el certificado PÚBLICO de recuperación de AWS,
sin texto plano en disco; sube el .cms a s3://<bucket privado>/backups/database/ (SSE) y borra los temporales. Localmente descarga el .cms a work/backups/external/,
verifica el SHA-256 contra el calculado en la EC2, comprueba que descifra a un volcado PGDMP (clave privada de AWS, no se imprime) y compara la huella de datos antes y
después del volcado con la línea base. No toca Terraform ni datos; solo lecturas SQL.
Uso: backend/.venv/bin/python scripts/cloud/db-backup-cms.py --cert work/recovery-keys/<dir>/recovery-public.crt --key work/recovery-keys/<dir>/recovery-private.pem --out docs/evidencias/...
"""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load("flow", "scripts/cloud/verify-controlled-flow.py")  # ssm(), FINGERPRINT, MIG
BASELINE = ["reservations=135:cbe0c1c26e4cee71ffac596dd24d3607", "tickets=135", "users=25", "alembic=0008"]


def aws(*a):
    return subprocess.check_output(["aws", *a], text=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES":
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES (sube un objeto a S3 y usa SSM).")
    cert = Path(a.cert).read_text()
    if "BEGIN CERTIFICATE" not in cert or "PRIVATE" in cert:
        sys.exit("--cert debe ser un certificado público.")
    bucket = aws("s3api", "list-buckets", "--query", "Buckets[?starts_with(Name,'nexoeventos-academy-')].Name|[0]", "--output", "text")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"nexoeventos-alembic0008-{ts}.cms"
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    before = C.ssm(C.FINGERPRINT, "backup0008: huella previa (lectura)").strip().split("\n")
    missing = [b for b in BASELINE if b not in before]
    if missing:
        sys.exit(f"La huella previa no coincide con la línea base: {missing}")

    remote = f"""umask 077; F=/tmp/{name}; CRT=/tmp/rc-{ts}.crt
cat > "$CRT" <<'CRT_EOF'
{cert.strip()}
CRT_EOF
pg_dump "$DB_URL" -Fc --no-owner --no-acl | tee >(sha256sum | cut -d' ' -f1 > /tmp/plain-{ts}.sha) | openssl cms -encrypt -binary -aes-256-cbc -outform DER -out "$F" "$CRT"
sleep 1; echo "plain_sha256=$(cat /tmp/plain-{ts}.sha)"; echo "cms_sha256=$(sha256sum "$F" | cut -d' ' -f1)"; echo "cms_bytes=$(wc -c < "$F" | tr -d ' ')"; echo "pg_dump=$(pg_dump --version)"
aws s3 cp "$F" "s3://{bucket}/backups/database/{name}" --sse AES256 --only-show-errors
rm -f "$F" "$CRT" /tmp/plain-{ts}.sha; echo subido
"""
    script = C.MIG + remote
    iid = aws("ec2", "describe-instances", "--filters", "Name=tag:Name,Values=nexoeventos-academy-app", "Name=instance-state-name,Values=running",
              "--query", "Reservations[0].Instances[0].InstanceId", "--output", "text")
    cid = aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", "backup0008: pg_dump cifrado CMS",
              "--parameters", json.dumps({"commands": [script]}), "--timeout-seconds", "600", "--query", "Command.CommandId", "--output", "text")
    import time
    for _ in range(200):
        time.sleep(3)
        r = subprocess.run(["aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", iid, "--output", "json"], capture_output=True, text=True)
        if r.returncode:
            continue
        d = json.loads(r.stdout)
        if d["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
    if d["Status"] != "Success":
        sys.exit(f"SSM {d['Status']}: {d['StandardErrorContent'][-400:]}")
    info = dict(l.split("=", 1) for l in d["StandardOutputContent"].splitlines() if "=" in l)

    dest = ROOT / "work/backups/external" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    aws("s3", "cp", f"s3://{bucket}/backups/database/{name}", str(dest), "--only-show-errors")
    os.chmod(dest, 0o600)
    local_sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    dec = subprocess.run(["openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(dest), "-inkey", a.key], capture_output=True)
    after = C.ssm(C.FINGERPRINT, "backup0008: huella posterior (lectura)").strip().split("\n")
    res = {
        "archivo": name, "bytes": dest.stat().st_size, "sha256_local": local_sha, "sha256_ec2": info.get("cms_sha256"),
        "sha256_coincide": local_sha == info.get("cms_sha256"), "plain_sha256": info.get("plain_sha256"), "pg_dump": info.get("pg_dump"),
        "descifra_a_pgdmp": dec.returncode == 0 and dec.stdout[:5] == b"PGDMP", "volcado_bytes": len(dec.stdout),
        "huella_previa": before, "huella_posterior": after, "huella_igual": before == after,
    }
    (out / "respaldo-0008.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
