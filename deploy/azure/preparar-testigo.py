#!/usr/bin/env python3
"""Prepara la configuración del TESTIGO en la VM (EN la VM, como root, solo con autorización; NO sobrescribe nada existente).
 · invokers.json (0600): tokens de invocador «t4-atestador» (alcance attest) y «t4-lector» (alcance entry). Solo se guarda el SHA-256; los tokens en claro se imprimen UNA vez.
 · reporters.json (0600): claves PÚBLICAS Ed25519 frescas para operator/aws/oci cuyas privadas se DESCARTAN al instante: nadie puede informar, así el testigo queda SIN INICIALIZAR y sin dueño hasta que
   T5/T6 sustituyan reporters.json por las claves públicas reales de los informantes (con autorización propia).
Uso: preparar-testigo.py [--dir /etc/witness] [--owner nexowitness]"""
import argparse
import base64
import hashlib
import json
import os
import pwd
import secrets
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="/etc/witness"); ap.add_argument("--owner", default="")
    a = ap.parse_args(argv); d = Path(a.dir)
    inv, rep = d / "invokers.json", d / "reporters.json"
    if inv.exists() or rep.exists():
        print("ya existe configuración del testigo: no se sobrescribe", file=sys.stderr); return 2
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    d.mkdir(parents=True, exist_ok=True); os.chmod(d, 0o700)
    tokens = {"t4-atestador": ["attest"], "t4-lector": ["entry"]}; plain = {k: "wt-" + secrets.token_urlsafe(32) for k in tokens}
    pubs = {n: [base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()] for n in ("operator", "aws", "oci")}   # privadas descartadas
    for p, obj in ((inv, {"tokens": [{"id": k, "sha256": hashlib.sha256(plain[k].encode()).hexdigest(), "scopes": s} for k, s in tokens.items()]}), (rep, pubs)):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f: json.dump(obj, f)
        if a.owner:
            u = pwd.getpwnam(a.owner); os.chown(p, u.pw_uid, u.pw_gid)
    if a.owner:
        os.chown(d, pwd.getpwnam(a.owner).pw_uid, pwd.getpwnam(a.owner).pw_gid)
    print("Tokens del testigo (se muestran UNA vez; guárdelos en su gestor de contraseñas, nunca en el repositorio ni en el chat):")
    for k, v in plain.items(): print(f"  {k}: {v}")
    print("reporters.json: claves públicas sin dueño (el testigo queda sin inicializar hasta T5/T6)"); return 0


if __name__ == "__main__":
    sys.exit(main())
