#!/usr/bin/env python3
"""Generación y verificación de las claves de FIRMA del lease (NO son la clave C-04 que protege los respaldos: otra función, otro material, otra custodia).
Por qué firmar: el lease vive en un objeto que un PAR (o cualquiera con su URL) puede SOBRESCRIBIR sin If-Match. La exclusión mutua NO depende de las firmas (la dan el CAS y la espera ttl+margen: ver lease.py);
las firmas solo habilitan la liberación voluntaria inmediata y descartan registros ajenos del cálculo de épocas.
Esquemas:  ed25519 (recomendado)  cada nodo guarda SOLO su clave privada + las claves PÚBLICAS de los demás; un nodo comprometido no puede firmar como otro.
           hmac                   cada nodo guarda las claves de todos (secretos compartidos): más simple, peor aislamiento.
Reglas de seguridad: aleatoriedad del sistema (os.urandom), carpeta 0700 y archivos 0600, NUNCA se imprimen claves, se niega a escribir dentro de un repositorio git, en una carpeta no vacía o sin la doble llave
(NEXO_ALLOW_KEY_GENERATION=YES + --confirm «GENERAR CLAVES DEL LEASE»).
Uso:  lease_keys.py generate --out-dir D --holders aws,oci [--scheme ed25519|hmac] --confirm "GENERAR CLAVES DEL LEASE"
      lease_keys.py verify --node-dir D/aws --holder aws          (permisos, formato, que la clave no sea trivial)
      lease_keys.py verify-pair --node-dir D/aws --holder aws --peer-dir D/oci --peer-holder oci   (firma en un nodo, verifica en el otro)"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
CONFIRM = "GENERAR CLAVES DEL LEASE"
HOLDER = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


class KeyError_(Exception):
    pass


def inside_git(p: Path) -> bool:
    return any((q / ".git").exists() for q in [p.resolve(), *p.resolve().parents])


def write_secret(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f: f.write(text)


def b64(b: bytes) -> str: return base64.b64encode(b).decode()


def generate(out_dir: str, holders: list[str], scheme: str) -> dict:
    out = Path(out_dir)
    if len(set(holders)) != len(holders) or len(holders) < 2 or not all(HOLDER.match(h) for h in holders):
        raise KeyError_("se exigen ≥ 2 titulares distintos con nombres [a-z0-9_-]")
    if inside_git(out.parent if not out.exists() else out):
        raise KeyError_("la carpeta de destino está dentro de un repositorio git: las claves nunca van a Git")
    if out.exists() and any(out.iterdir()):
        raise KeyError_("la carpeta de destino no está vacía (no se sobrescribe material existente)")
    out.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(out, 0o700)
    summary = {"scheme": scheme, "holders": holders, "fingerprints": {}}
    if scheme == "ed25519":
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        keys = {}
        for h in holders:
            k = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
            keys[h] = (k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()), k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
            summary["fingerprints"][h] = hashlib.sha256(keys[h][1]).hexdigest()[:16]
        for h in holders:
            d = out / h; d.mkdir(mode=0o700); os.chmod(d, 0o700)
            write_secret(d / "lease-signing.key", b64(keys[h][0]) + "\n")                                         # SOLO este nodo
            write_secret(d / "lease-peers.json", json.dumps({o: [b64(keys[o][1])] for o in holders if o != h}))    # públicas de los demás (no secretas)
    elif scheme == "hmac":
        keys = {h: secrets.token_bytes(32) for h in holders}
        for h in holders:
            d = out / h; d.mkdir(mode=0o700); os.chmod(d, 0o700)
            write_secret(d / "lease-auth.json", json.dumps({o: keys[o].hex() for o in holders}))                  # simétrico: TODOS los secretos en cada nodo
        summary["advertencia"] = "hmac: cada nodo tiene las claves de todos; un nodo comprometido puede firmar como cualquiera"
    else:
        raise KeyError_("esquema desconocido")
    return summary


def load_node(node_dir: str, holder: str):
    d = Path(node_dir)
    for f in d.iterdir():
        if f.is_file() and f.stat().st_mode & 0o077:
            raise KeyError_(f"{f.name}: permisos abiertos (exige 0600)")
    if d.stat().st_mode & 0o077:
        raise KeyError_("la carpeta del nodo debe ser 0700")
    from app.failover.lease import Ed25519Auth, HmacAuth
    if (d / "lease-signing.key").exists():
        priv = base64.b64decode((d / "lease-signing.key").read_text().strip(), validate=True)
        peers = {h: [base64.b64decode(k, validate=True) for k in ks] for h, ks in json.loads((d / "lease-peers.json").read_text()).items()}
        if len(priv) != 32 or len(set(priv)) < 8:
            raise KeyError_("clave privada inválida o trivial")
        return Ed25519Auth(holder, priv, peers), "ed25519"
    keys = {h: bytes.fromhex(v) for h, v in json.loads((d / "lease-auth.json").read_text()).items()}
    if holder not in keys or len(keys) < 2 or any(len(k) < 32 or len(set(k)) < 8 for k in keys.values()) or len({k for k in keys.values()}) != len(keys):
        raise KeyError_("claves hmac inválidas, triviales o repetidas entre titulares")
    return HmacAuth(keys), "hmac"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["generate", "verify", "verify-pair", "plan"]); ap.add_argument("--out-dir"); ap.add_argument("--holders", default="aws,oci")
    ap.add_argument("--scheme", default="ed25519"); ap.add_argument("--confirm", default=""); ap.add_argument("--node-dir"); ap.add_argument("--holder"); ap.add_argument("--peer-dir"); ap.add_argument("--peer-holder")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":                                                      # solo IMPRIME los comandos: no crea nada ni toca claves
            d = a.out_dir or "$HOME/.nexoeventos/hybrid-lease-keys"
            print("\n".join([f"# 1) (cuando se autorice) generar — carpeta FUERA de cualquier repositorio, 0700:",
                              f"NEXO_ALLOW_KEY_GENERATION=YES backend/.venv/bin/python scripts/multicloud/hybrid/lease_keys.py generate --out-dir {d} --holders aws,oci --scheme ed25519 --confirm \"{CONFIRM}\"",
                              f"# 2) comprobar la pareja (firma en un nodo, verifica en el otro):",
                              f"backend/.venv/bin/python scripts/multicloud/hybrid/lease_keys.py verify-pair --node-dir {d}/aws --holder aws --peer-dir {d}/oci --peer-holder oci",
                              f"# 3) copiar a cada nodo SOLO su carpeta ({d}/aws → EC2; {d}/oci → standby) y borrar el origen. Variables del backend de prueba:",
                              "#    WRITE_GATE_LEASE_SIGNING_KEY_FILE=<nodo>/lease-signing.key  WRITE_GATE_LEASE_PEER_PUBKEYS_FILE=<nodo>/lease-peers.json  WRITE_GATE_LEASE_STATE_FILE=<nodo>/lease.state",
                              "# Nunca: Git, Terraform, logs, chat, SSM Parameter Store en claro. No es la clave C-04."])); return 0
        if a.cmd == "generate":
            if os.environ.get("NEXO_ALLOW_KEY_GENERATION") != "YES" or a.confirm != CONFIRM:
                print("RECHAZADO: falta NEXO_ALLOW_KEY_GENERATION=YES y la frase de confirmación exacta.", file=sys.stderr); return 3
            if not a.out_dir: print("falta --out-dir", file=sys.stderr); return 2
            print(json.dumps(generate(a.out_dir, a.holders.split(","), a.scheme), indent=1)); return 0
        if not (a.node_dir and a.holder): print("faltan --node-dir y --holder", file=sys.stderr); return 2
        auth, scheme = load_node(a.node_dir, a.holder)
        if a.cmd == "verify":
            print(json.dumps({"ok": True, "scheme": scheme})); return 0
        if not (a.peer_dir and a.peer_holder): print("faltan --peer-dir y --peer-holder", file=sys.stderr); return 2
        peer, _ = load_node(a.peer_dir, a.peer_holder)
        msg = secrets.token_bytes(32)
        ok = peer.verify(a.holder, msg, auth.sign(a.holder, msg)) and auth.verify(a.peer_holder, msg, peer.sign(a.peer_holder, msg)) and not peer.verify(a.holder, msg + b"x", auth.sign(a.holder, msg))
        print(json.dumps({"ok": bool(ok), "scheme": scheme})); return 0 if ok else 1
    except (KeyError_, OSError, ValueError, KeyError) as e:
        print(f"ERROR: {type(e).__name__}: {e}" if isinstance(e, KeyError_) else f"ERROR: {type(e).__name__}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
