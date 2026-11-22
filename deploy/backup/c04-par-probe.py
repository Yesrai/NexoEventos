#!/usr/bin/env python3
"""C-04: sonda de `If-None-Match` con el PAR de OCI. Escribe UN objeto diminuto de prueba (nombre único con marca de tiempo, dentro del prefijo del PAR) y lo vuelve a
escribir con el MISMO nombre: si OCI respeta `If-None-Match: *` en un PAR, la segunda escritura debe responder 412 (no se sobrescribe). NO se ejecuta sin confirmación
de la propietaria (es una escritura en OCI). No imprime ni guarda la URL del PAR. Códigos: 0 = If-None-Match respetado (2.ª escritura 412) · 1 = NO respetado · 2 = otro error.
Uso (en la EC2, como root): python3 c04-par-probe.py --par-url-file /etc/nexoeventos/c04/backup-par.url"""
import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def put(url: str, data: bytes) -> int:
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("If-None-Match", "*")
    req.add_header("Content-Type", "text/plain")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError:
        return -1


PREFIX = "backups/c04-20261119/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--par-url-file", required=True)
    a = ap.parse_args()
    base = Path(a.par_url_file).read_text().strip()
    p = urllib.parse.urlparse(base)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        print("La URL del PAR debe ser HTTPS válida.", file=sys.stderr)
        return 2
    base = base if base.endswith("/") else base + "/"
    # El access-uri real de un PAR con prefijo termina en `/o/`: el nombre DEBE llevar el prefijo autorizado (si la URL ya lo trae, no se repite).
    pfx = "" if base.endswith(PREFIX) else PREFIX
    name = pfx + "_sonda-if-none-match-%s.txt" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    url = base + urllib.parse.quote(name)
    first = put(url, b"c04 sonda 1\n")
    second = put(url, b"c04 sonda 2 (no debe sobrescribir)\n")
    print(f"objeto de prueba: {name}")
    print(f"1.ª escritura: HTTP {first} | 2.ª escritura con el mismo nombre: HTTP {second}")
    if first in (200, 201) and second == 412:
        print("RESULTADO: If-None-Match se RESPETA con el PAR (no hay sobrescritura).")
        return 0
    if first in (200, 201) and second in (200, 201):
        print("RESULTADO: If-None-Match NO se respeta con el PAR (la 2.ª escritura sobrescribió; el versionado del bucket conserva la versión previa).")
        return 1
    print("RESULTADO: no concluyente (revisar el alcance, la caducidad y la conectividad del PAR).")
    return 2


if __name__ == "__main__":
    sys.exit(main())
