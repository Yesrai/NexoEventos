#!/usr/bin/env python3
"""Verificación de INTEGRIDAD de un par de paquetes C-04 (datos + claves de aplicación) SIN descifrar y sin pedir ninguna frase:
  1) firma del manifiesto con la clave pública fijada · 2) SHA-256 y tamaño del objeto cifrado = manifiesto · 3) el CMS está dirigido al certificado fijado (serie del destinatario) y el certificado
  tiene la huella fijada y está vigente · 4) (opcional --remote, SOLO LECTURA con `oci os object head`) el MD5 del objeto del bucket = el de la copia local (el bucket contiene exactamente lo verificado).
Uso: verificar_respaldo_c04.py --dir D --bundle nexoeventos-rds-… --secbundle app-secrets-… --cert C.crt --cert-sha256 FP --signer-pub P.pub [--remote --namespace NS --bucket B --profile P --prefix backups/c04-… --sec-prefix secrets/c04-…] --out F.json"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sh(*a, **k): return subprocess.run(list(a), capture_output=True, text=True, **k)


def sha256_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cert_info(cert):
    fp = sh("bash", "-c", f"openssl x509 -in '{cert}' -outform DER | openssl sha256 | awk '{{print $NF}}'").stdout.strip()
    serial = (sh("openssl", "x509", "-in", str(cert), "-noout", "-serial").stdout.strip().split("=")[-1]).lstrip("0").lower()
    end = sh("openssl", "x509", "-in", str(cert), "-noout", "-enddate").stdout.strip().split("=")[-1]
    ok_date = sh("openssl", "x509", "-in", str(cert), "-noout", "-checkend", "86400").returncode == 0
    return fp, serial, end, ok_date


def cms_recipient_serials(cms):
    t = sh("openssl", "cms", "-cmsout", "-print", "-inform", "DER", "-in", str(cms)).stdout
    return [re.sub(r"^0x", "", m.strip()).lstrip("0").lower() for m in re.findall(r"serialNumber:\s*(0x[0-9A-Fa-f]+|\d+)", t)]


def int_hex(s):
    s = s.strip()
    return format(int(s, 16) if s.startswith("0x") else int(s), "x") if re.fullmatch(r"(0x[0-9A-Fa-f]+|\d+)", s) else s.lower()


def verify_one(d: Path, name: str, kind: str, cert, fp_expected, signer_pub, remote=None) -> dict:
    out = {"paquete": name, "tipo": kind, "comprobaciones": {}}; c = out["comprobaciones"]
    cms, man, sig = d / f"{name}.cms", d / f"{name}.manifest.json", d / f"{name}.manifest.json.sig"
    for p in (cms, man, sig):
        if not p.is_file(): c["archivos_presentes"] = {"ok": False, "detalle": f"falta {p.name}"}; out["ok"] = False; return out
    c["archivos_presentes"] = {"ok": True, "detalle": "cms, manifiesto y firma"}
    v = sh("openssl", "dgst", "-sha256", "-verify", str(signer_pub), "-signature", str(sig), str(man)); c["firma_del_manifiesto"] = {"ok": v.returncode == 0, "detalle": v.stdout.strip() or v.stderr.strip()[:80]}
    try: m = json.loads(man.read_text())
    except ValueError: m = {}
    want_sha, want_len = (m.get("oci_cms_sha256") or m.get("cms_sha256")), (m.get("oci_cms_bytes") or m.get("cms_bytes"))
    c["sha256_y_tamano_del_cifrado"] = {"ok": bool(want_sha and sha256_file(cms) == want_sha and cms.stat().st_size == want_len), "detalle": f"{cms.stat().st_size} B"}
    fp, serial, end, vigente = cert_info(cert)
    c["certificado_con_la_huella_fijada"] = {"ok": fp == fp_expected, "detalle": f"vigente hasta {end}"}
    c["certificado_vigente_24h"] = {"ok": vigente, "detalle": end}
    recips = [int_hex(x) for x in cms_recipient_serials(cms)]
    c["cms_dirigido_al_certificado"] = {"ok": bool(recips) and serial in recips and len(recips) == 1, "detalle": f"{len(recips)} destinatario(s)"}
    if kind == "claves" and m.get("recipient_cert_sha256"): c["manifiesto_declara_la_misma_huella"] = {"ok": m["recipient_cert_sha256"] == fp_expected, "detalle": ""}
    if remote:
        md5_local = base64.b64encode(hashlib.md5(cms.read_bytes()).digest()).decode(); r = remote(f"{name}.cms")
        c["bucket_igual_a_la_copia_local_md5"] = {"ok": bool(r and r == md5_local), "detalle": "content-md5 del bucket vs local" if r else "no se pudo leer el objeto remoto"}
    out["ok"] = all(x["ok"] for x in c.values()); return out


def remote_md5(args):
    def fn(obj_name):
        prefix = args.prefix if obj_name.startswith("nexoeventos-rds") else args.sec_prefix
        r = sh("oci", "os", "object", "head", "--profile", args.profile, "--region", "sa-saopaulo-1", "-ns", args.namespace, "-bn", args.bucket, "--name", prefix + obj_name, "--query", "\"content-md5\"", "--raw-output",
               env={**os.environ, "SUPPRESS_LABEL_WARNING": "True"})
        return r.stdout.strip() if r.returncode == 0 else None
    return fn


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", required=True); ap.add_argument("--bundle", required=True); ap.add_argument("--secbundle", required=True)
    ap.add_argument("--cert", required=True); ap.add_argument("--cert-sha256", required=True); ap.add_argument("--signer-pub", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--remote", action="store_true"); ap.add_argument("--namespace"); ap.add_argument("--bucket", default="nexoeventos-recovery"); ap.add_argument("--profile", default="NEXOEVENTOS_UPLOADER")
    ap.add_argument("--prefix", default="backups/c04-20261119/"); ap.add_argument("--sec-prefix", default="secrets/c04-20261119/"); a = ap.parse_args(argv)
    fp = a.cert_sha256.replace(":", "").lower(); rem = remote_md5(a) if a.remote else None; d = Path(a.dir)
    res = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "huella_certificado_esperada": fp[:16] + "…", "no_descifra": True,
           "paquetes": [verify_one(d, a.bundle, "datos", a.cert, fp, a.signer_pub, rem), verify_one(d, a.secbundle, "claves", a.cert, fp, a.signer_pub, rem)]}
    res["ok"] = all(p["ok"] for p in res["paquetes"]); fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(res, f, indent=1, ensure_ascii=False)
    for p in res["paquetes"]:
        for k, v in p["comprobaciones"].items(): print(("OK    " if v["ok"] else "FALLÓ ") + f"{p['tipo']}: {k} — {v['detalle']}")
    print("RESULTADO:", "ÍNTEGRO" if res["ok"] else "NO ÍNTEGRO"); return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
