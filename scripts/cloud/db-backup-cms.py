#!/usr/bin/env python3
"""Respaldo lógico cifrado de la RDS de V1 (reproducible). Requiere RDS y EC2 de V1 encendidas (RDS detenida no se puede volcar) y NEXO_ALLOW_CLOUD_CHANGES=YES.

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
import re
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
# La huella es la de scripts/multicloud/fingerprint.sql (las mismas claves que usa restore-drill.sh). No hay línea base fija: se exige que la huella
# previa y la posterior al volcado sean idénticas (sin escrituras durante el respaldo) y se guarda como nueva línea base para la restauración aislada.
FP_SQL = (ROOT / "scripts/multicloud/fingerprint.sql").read_text()


def fp_lines(txt):
    return sorted(l.strip() for l in txt.splitlines() if "=" in l)


def aws(*a):
    return subprocess.check_output(["aws", *a], text=True).strip()


PASSIN_OK = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|file:.+|fd:[0-9]+)$")


def cms_decrypt(cms: Path, key: str, passin: str):
    """Descifra un CMS DER con la clave privada (opcionalmente protegida con contraseña, S-01). Devuelve (ok, texto_plano, motivo).
    La contraseña solo se pasa como referencia (env:/file:/fd:), nunca como valor; stdin=/dev/null evita esperas; el stderr de openssl no se devuelve."""
    if passin and not PASSIN_OK.match(passin):
        return False, b"", "formato de --passin no admitido (use env:NOMBRE, file:RUTA o fd:N; pass: se rechaza)"
    head = Path(key).read_text(errors="replace")[:400]
    if ("ENCRYPTED PRIVATE KEY" in head or "ENCRYPTED" in head.split("\n\n")[0]) and not passin:
        return False, b"", "la clave privada está protegida con contraseña: indique --passin"
    cmd = ["openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(cms), "-inkey", key] + (["-passin", passin] if passin else [])
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    if r.returncode == 0:
        return True, r.stdout, None
    err = r.stderr.decode(errors="replace").lower()
    if any(t in err for t in ("bad decrypt", "bad password", "error reading password", "pem routines", "unable to load", "could not read", "could not find or decode", "unable to get passphrase", "ui routines", "no environment variable", "error getting password")):
        return False, b"", "contraseña incorrecta, no disponible o clave ilegible"
    return False, b"", "el archivo no corresponde a esta clave o está alterado"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--passin", default="", help="solo si la clave privada tiene contraseña: env:NOMBRE | file:RUTA | fd:N (nunca pass:)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES":
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES (sube un objeto a S3 y usa SSM).")
    cert = Path(a.cert).read_text()
    if "BEGIN CERTIFICATE" not in cert or "PRIVATE" in cert:
        sys.exit("--cert debe ser un certificado público.")
    bucket = aws("s3api", "list-buckets", "--query", "Buckets[?starts_with(Name,'nexoeventos-academy-')].Name|[0]", "--output", "text")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"nexoeventos-rds-{ts}.cms"
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    before = fp_lines(C.ssm(FP_SQL, "respaldo-rds: huella previa (lectura)"))
    if not any(l.startswith("alembic=") for l in before) or not any(l.startswith("reservations=") for l in before):
        sys.exit("La huella previa no contiene alembic ni reservas: la base no responde como se espera. Me detengo.")

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
    cid = aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", "respaldo-rds: pg_dump cifrado CMS",
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
    dec_ok, dec_plain, dec_reason = cms_decrypt(dest, a.key, a.passin)
    after = fp_lines(C.ssm(FP_SQL, "respaldo-rds: huella posterior (lectura)"))
    res = {
        "archivo": name, "bytes": dest.stat().st_size, "sha256_local": local_sha, "sha256_ec2": info.get("cms_sha256"),
        "sha256_coincide": local_sha == info.get("cms_sha256"), "plain_sha256": info.get("plain_sha256"), "pg_dump": info.get("pg_dump"),
        "descifra_a_pgdmp": dec_ok and dec_plain[:5] == b"PGDMP", "volcado_bytes": len(dec_plain), "motivo_si_no_descifra": dec_reason,
        "huella_previa": before, "huella_posterior": after, "huella_igual": before == after,
    }
    (out / "respaldo-rds.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    key = f"rds-{ts}"
    fp = dict(l.split("=", 1) for l in before)
    (out / "linea-base-restauracion.json").write_text(json.dumps({"schema": 1, "baselines": {key: {"descripcion": f"Huella OBSERVADA en la RDS de origen justo antes del volcado {name}", "fingerprint": fp}}}, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"Línea base para restore-drill.sh: {out / 'linea-base-restauracion.json'} (--baseline-key {key})")
    problems = [k for k, v in (("sha256_coincide", res["sha256_coincide"]), ("descifra_a_pgdmp", res["descifra_a_pgdmp"]), ("huella_igual", res["huella_igual"])) if not v]
    if res["volcado_bytes"] < 1024:
        problems.append("volcado_demasiado_pequeno")
    if problems:
        sys.exit(f"RESPALDO NO VÁLIDO ({', '.join(problems)}): no usar; repetir el volcado antes de apagar RDS.")


if __name__ == "__main__":
    main()
