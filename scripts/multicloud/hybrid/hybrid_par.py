#!/usr/bin/env python3
"""Auditoría de los PAR de la prueba híbrida. NO crea PAR (eso lo hace SOLO la propietaria, con `plan`, que imprime los comandos sin URLs) ni los borra: solo LEE (`oci os preauth-request list`,
`oci os bucket get`) y SONDEA con GET que deben ser rechazados. Las URLs viven en archivos 0600 y no se imprimen nunca.
  plan                          imprime los comandos que ejecutaría la propietaria (2 PAR, objetos exclusivos, caducidad corta)
  audit  --namespace N --bucket B --profile P     valida metadatos: solo los objetos de la prueba, sin Any*, ≤4 h, sin listado, sin backups/ ni secrets/, 2 PAR como máximo, bucket privado y versionado
  probe  --par-url-file F [--par-url-file G]      intenta (GET) leer backups/, secrets/ y listar el bucket con cada PAR: TODO debe ser rechazado
  verify-revoked --par-url-file F ... --namespace N --bucket B --profile P   tras revocar: la URL ya no responde 2xx y el listado de PAR está vacío
Límite conocido: un PAR de ObjectReadWrite NO puede exigir If-Match: quien tenga la URL puede sobrescribir el objeto sin CAS. Mitigaciones: URL 0600 y solo en los nodos, caducidad ≤ 4 h, versionado del bucket
(la versión anterior se recupera), objetos exclusivos de la prueba y detección por época/ETag en el cliente."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ALLOWED_OBJECTS = {"hybrid-test/writer-lease.json", "hybrid-test/fence-attestation.json"}
FORBIDDEN_PREFIXES = ("backups/", "secrets/", "backups", "secrets")
ALLOWED_ACCESS = {"ObjectRead", "ObjectReadWrite", "ObjectWrite"}
MAX_HOURS = 4


def run_oci(argv: list[str]) -> dict:
    cp = subprocess.run(["oci", *argv, "--output", "json"], capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError("oci falló: " + (cp.stderr.strip().splitlines() or ["?"])[-1][:200])
    return json.loads(cp.stdout or "{}")


def plan_commands(namespace: str = "<namespace>", bucket: str = "nexoeventos-recovery", profile: str = "<perfil>") -> list[str]:
    exp = f"$(date -u -v+{MAX_HOURS}H +%Y-%m-%dT%H:%M:%SZ)"                                       # macOS; en Linux: date -u -d '+4 hours'
    return [f"oci os preauth-request create --namespace-name {namespace} --bucket-name {bucket} --profile {profile} --name hybrid-test-{o.split('/')[-1].split('.')[0]} "
            f"--access-type ObjectReadWrite --object-name {o} --time-expires {exp}   # la URL de la respuesta va a un archivo 0600, NUNCA al chat" for o in sorted(ALLOWED_OBJECTS)]


def audit(par_list: list[dict], bucket: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc); problems: list[str] = []
    if bucket.get("public-access-type") != "NoPublicAccess": problems.append("el bucket no es NoPublicAccess")
    if bucket.get("versioning") != "Enabled": problems.append("el bucket no tiene versionado (no se podría recuperar un objeto sobrescrito)")
    if len(par_list) > len(ALLOWED_OBJECTS): problems.append(f"hay {len(par_list)} PAR activos (máximo {len(ALLOWED_OBJECTS)})")
    for p in par_list:
        name = p.get("name", "?"); obj = p.get("object-name") or ""; acc = p.get("access-type", "")
        if acc not in ALLOWED_ACCESS: problems.append(f"{name}: tipo de acceso no permitido ({acc})")
        if obj not in ALLOWED_OBJECTS: problems.append(f"{name}: objeto fuera de la prueba ({obj or 'bucket/prefijo completo'})")
        if obj.startswith(FORBIDDEN_PREFIXES): problems.append(f"{name}: alcanza backups/ o secrets/")
        if p.get("bucket-listing-action") not in (None, "Deny"): problems.append(f"{name}: permite listar el bucket")
        try:
            exp = datetime.fromisoformat(str(p.get("time-expires", "")).replace("Z", "+00:00"))
            if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
            if exp - now > timedelta(hours=MAX_HOURS, minutes=5): problems.append(f"{name}: caduca en más de {MAX_HOURS} h")
            if exp <= now: problems.append(f"{name}: ya está caducado (debe borrarse)")
        except ValueError:
            problems.append(f"{name}: caducidad ilegible")
    return {"ok": not problems, "problems": problems, "par_count": len(par_list)}


def read_url(path: str) -> str:
    st = os.stat(path)
    if st.st_mode & 0o077: raise PermissionError(f"{os.path.basename(path)}: permisos abiertos (exige 0600)")
    return Path(path).read_text().strip()


def _status(url: str, method: str = "GET") -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def probe(url: str, status=_status) -> dict:
    """Solo GET (no escribe nada). Devuelve códigos, nunca la URL. Con un PAR de objeto, cambiar el objeto o quitarlo debe dar 401/403/404."""
    m = re.match(r"^(.*?/o/)(.+)$", url)
    if not m: raise ValueError("la URL no tiene la forma /o/<objeto>")
    base = m.group(1)
    intentos = {"backups/": base + "backups/database/", "secrets/": base + "secrets/x", "listado": base.rstrip("/").rsplit("/o", 1)[0] + "/o/", "objeto hermano": base + "hybrid-test/otro.json"}
    res = {k: status(u) for k, u in intentos.items()}
    return {"codigos": res, "ok": all(c in (0, 400, 401, 403, 404) for c in res.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "audit", "probe", "verify-revoked"])
    ap.add_argument("--namespace"); ap.add_argument("--bucket", default="nexoeventos-recovery"); ap.add_argument("--profile"); ap.add_argument("--par-url-file", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            print("\n".join(plan_commands(a.namespace or "<namespace>", a.bucket, a.profile or "<perfil>"))); return 0
        if a.cmd in ("audit", "verify-revoked"):
            if not (a.namespace and a.profile): print("faltan --namespace y --profile", file=sys.stderr); return 2
            base = ["os", "preauth-request", "list", "--namespace-name", a.namespace, "--bucket-name", a.bucket, "--profile", a.profile, "--all"]
            lst = run_oci(base).get("data", []); b = run_oci(["os", "bucket", "get", "--namespace-name", a.namespace, "--bucket-name", a.bucket, "--profile", a.profile]).get("data", {})
            if a.cmd == "audit":
                r = audit(lst, b); print(json.dumps(r, ensure_ascii=False, indent=1)); return 0 if r["ok"] else 1
            vivos = [u for u in a.par_url_file if 200 <= _status(read_url(u)) < 300]
            ok = not lst and not vivos
            print(json.dumps({"ok": ok, "par_activos": len(lst), "urls_que_aun_responden": len(vivos)}, indent=1)); return 0 if ok else 1
        if not a.par_url_file: print("falta --par-url-file", file=sys.stderr); return 2
        out = [probe(read_url(f)) for f in a.par_url_file]; print(json.dumps(out, indent=1)); return 0 if all(o["ok"] for o in out) else 1
    except (PermissionError, ValueError, RuntimeError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
