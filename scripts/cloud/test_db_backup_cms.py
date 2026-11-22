#!/usr/bin/env python3
"""Prueba LOCAL (sin nubes) de scripts/cloud/db-backup-cms.py con una CLI `aws` FALSA y claves desechables en un directorio temporal.
Casos: (1) éxito; (2) la huella cambia durante el volcado; (3) volcado inválido (no PGDMP); (4) sin NEXO_ALLOW_CLOUD_CHANGES; (5) la base no responde.
Uso: backend/.venv/bin/python scripts/cloud/test_db_backup_cms.py"""
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/cloud/db-backup-cms.py"
FAKE_AWS = r'''#!/usr/bin/env python3
import json, os, sys, shutil
from pathlib import Path
S = Path(os.environ["FAKE_STATE"]); a = sys.argv[1:]
def calls():
    f = S / "calls.txt"; f.write_text((f.read_text() if f.exists() else "") + " ".join(a[:2]) + "\n")
calls()
if a[:2] == ["s3api", "list-buckets"]: print("nexoeventos-academy-test")
elif a[:2] == ["ec2", "describe-instances"]: print("i-fake")
elif a[:2] == ["ssm", "send-command"]:
    params = json.loads(a[a.index("--parameters") + 1])["commands"][0]
    n = len(list(S.glob("cid-*"))); cid = f"cid-{n}"
    (S / cid).write_text("backup" if "pg_dump" in params else "fp"); print(cid)
elif a[:2] == ["ssm", "get-command-invocation"]:
    cid = a[a.index("--command-id") + 1]; kind = (S / cid).read_text()
    if kind == "fp":
        k = len(list(S.glob("fpdone-*"))); (S / f"fpdone-{k}").write_text("x")
        mode = os.environ["FAKE_MODE"]
        if mode == "sin_base": out = ""
        else: out = (S / ("fp_before.txt" if k == 0 else "fp_after_" + ("cambia" if mode == "huella_cambia" else "igual") + ".txt")).read_text()
    else: out = (S / "backup_out.txt").read_text()
    print(json.dumps({"Status": "Success", "StandardOutputContent": out, "StandardErrorContent": ""}))
elif a[:2] == ["s3", "cp"]: shutil.copyfile(S / ("cms_malo.bin" if os.environ["FAKE_MODE"] == "volcado_invalido" else "cms_ok.bin"), a[3])
else: sys.exit("llamada no prevista: " + " ".join(a))
'''
FP_BEFORE = "alembic=0008\nusers=25\nevents=35\nreservations=135\ntickets=135\noperator_assignments=2\naccess_logs=9\nreserved_total=135\ninventory_md5=aa\nreservations_md5=bb\n"


def run(mode, tmp, env_extra=None):
    st = tmp / f"state-{mode}"; shutil.rmtree(st, ignore_errors=True); st.mkdir()
    (tmp / "bin").mkdir(exist_ok=True); (tmp / "bin/aws").write_text(FAKE_AWS); (tmp / "bin/aws").chmod(0o755)
    (st / "fp_before.txt").write_text(FP_BEFORE); (st / "fp_after_igual.txt").write_text(FP_BEFORE)
    (st / "fp_after_cambia.txt").write_text(FP_BEFORE.replace("reservations=135", "reservations=136"))
    for name, data in (("cms_ok.bin", b"PGDMP" + os.urandom(6000)), ("cms_malo.bin", b"NOTADUMP" + os.urandom(6000))):
        raw = tmp / "raw.bin"; raw.write_bytes(data)
        subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-in", str(raw), "-out", str(st / name), "-outform", "DER", str(tmp / "pub.crt")], check=True, capture_output=True)
        if name == "cms_ok.bin": plain = hashlib.sha256(data).hexdigest()
    cms = (st / "cms_ok.bin").read_bytes()
    (st / "backup_out.txt").write_text(f"plain_sha256={plain}\ncms_sha256={hashlib.sha256(cms).hexdigest()}\ncms_bytes={len(cms)}\npg_dump=pg_dump (PostgreSQL) 18.6\nsubido\n")
    if mode == "volcado_invalido":  # la EC2 informa el hash del archivo malo
        bad = (st / "cms_malo.bin").read_bytes(); (st / "backup_out.txt").write_text(f"plain_sha256=x\ncms_sha256={hashlib.sha256(bad).hexdigest()}\ncms_bytes={len(bad)}\npg_dump=x\nsubido\n")
    env = {**os.environ, "PATH": f"{tmp/'bin'}:{os.environ['PATH']}", "FAKE_STATE": str(st), "FAKE_MODE": mode}
    if mode != "sin_autorizacion": env["NEXO_ALLOW_CLOUD_CHANGES"] = "YES"
    out = tmp / f"out-{mode}"
    r = subprocess.run([sys.executable, str(SCRIPT), "--cert", str(tmp / "pub.crt"), "--key", str(tmp / "priv.pem"), "--out", f"work/test-db-backup-{mode}"], cwd=ROOT, env=env, capture_output=True, text=True)
    return r, ROOT / f"work/test-db-backup-{mode}", st


def main():
    tmp = Path(tempfile.mkdtemp(prefix="dbb-test-"))
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tmp / "priv.pem"), "-out", str(tmp / "pub.crt"), "-days", "2", "-subj", "/CN=test"], check=True, capture_output=True)
    fails = []
    def chk(name, cond, det=""):
        print(("OK    " if cond else "FALLÓ ") + name + (f" — {det}" if det and not cond else "")); (None if cond else fails.append(name))
    try:
        r, out, st = run("exito", tmp)
        chk("éxito: termina con código 0", r.returncode == 0, r.stderr[-300:])
        res = json.loads((out / "respaldo-rds.json").read_text()) if (out / "respaldo-rds.json").exists() else {}
        chk("éxito: SHA-256, descifrado PGDMP y huella iguales", res.get("sha256_coincide") and res.get("descifra_a_pgdmp") and res.get("huella_igual"))
        bl = json.loads((out / "linea-base-restauracion.json").read_text())
        key = next(iter(bl["baselines"])); fp = bl["baselines"][key]["fingerprint"]
        chk("éxito: línea base compatible con restore-drill.sh (10 claves, reservations=135)", len(fp) == 10 and fp.get("reservations") == "135" and key.startswith("rds-"))
        chk("éxito: ningún archivo de clave ni texto plano en la salida", not any(p.suffix in (".pem", ".dump") for p in out.iterdir()))
        r, out, _ = run("huella_cambia", tmp); chk("huella cambia durante el volcado: falla con código ≠ 0 y lo indica", r.returncode != 0 and "huella_igual" in r.stderr, r.stderr[-200:])
        r, out, _ = run("volcado_invalido", tmp); chk("volcado no PGDMP: falla", r.returncode != 0 and "descifra_a_pgdmp" in r.stderr, r.stderr[-200:])
        r, out, _ = run("sin_autorizacion", tmp); chk("sin NEXO_ALLOW_CLOUD_CHANGES: no llama a ninguna CLI", r.returncode != 0 and "NEXO_ALLOW_CLOUD_CHANGES" in r.stderr)
        r, out, _ = run("sin_base", tmp); chk("la base no responde (huella vacía): se detiene antes de volcar", r.returncode != 0 and "Me detengo" in r.stderr, r.stderr[-200:])
        calls = (tmp / "state-sin_base/calls.txt").read_text() if (tmp / "state-sin_base/calls.txt").exists() else ""
        chk("sin huella previa no se ejecutó el volcado (solo 1 send-command)", calls.count("ssm send-command") == 1, calls)
    finally:
        for p in ROOT.glob("work/test-db-backup-*"): shutil.rmtree(p, ignore_errors=True)
        for p in (ROOT / "work/backups/external").glob("nexoeventos-rds-*.cms"): p.unlink()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nResultado: {'TODO CORRECTO' if not fails else 'FALLOS: ' + ', '.join(fails)}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
