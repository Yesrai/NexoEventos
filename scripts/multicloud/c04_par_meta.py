#!/usr/bin/env python3
"""C-04: valida por METADATOS (sin URL ni token) el PAR creado por la propietaria: exactamente uno, tipo AnyObjectWrite, objeto = prefijo exclusivo, bucket correcto y
caducidad ≤ creación + 100 min (y con tiempo suficiente por delante). Solo lista (`oci os preauth-request list`, que no devuelve la URL) y muestra campos de una lista blanca.
Uso: c04_par_meta.py --namespace NS --bucket nexoeventos-recovery --profile DEFAULT [--prefix backups/c04-20261119/] [--name c04-escritura-20261119] [--min-left-min 60]"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

WHITELIST = ("name", "access-type", "object-name", "time-created", "time-expires")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(items: list[dict], *, prefix: str, name: str, now: datetime, min_left_min: int = 60, max_life_min: int = 100) -> dict:
    rows = [{k: i.get(k) for k in WHITELIST} for i in items]  # NUNCA se copia access-uri ni otro campo
    checks: list[tuple[str, bool]] = []
    checks.append(("exactamente 1 PAR en el bucket", len(rows) == 1))
    if len(rows) == 1:
        r = rows[0]
        created, expires = parse(r["time-created"]), parse(r["time-expires"])
        life = (expires - created).total_seconds() / 60
        left = (expires - now).total_seconds() / 60
        checks += [
            (f"nombre = {name}", r["name"] == name),
            ("tipo = AnyObjectWrite (solo escritura; sin lectura ni listado)", r["access-type"] == "AnyObjectWrite"),
            (f"objeto/prefijo exacto = {prefix}", r["object-name"] == prefix),
            (f"vida total ≤ {max_life_min} min (es {life:.0f})", life <= max_life_min + 1),
            (f"quedan ≥ {min_left_min} min de validez (quedan {left:.0f})", left >= min_left_min),
        ]
    return {"pares": rows, "comprobaciones": [{"ok": ok, "que": que} for que, ok in checks], "ok": all(ok for _, ok in checks)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--prefix", default="backups/c04-20261119/")
    ap.add_argument("--name", default="c04-escritura-20261119")
    ap.add_argument("--min-left-min", type=int, default=60)
    a = ap.parse_args(argv)
    r = subprocess.run(["oci", "os", "preauth-request", "list", "--bucket-name", a.bucket, "--namespace-name", a.namespace, "--profile", a.profile, "--all"],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        print("No se pudo listar los PAR.", file=sys.stderr)
        return 2
    items = (json.loads(r.stdout).get("data") if r.stdout.strip() else []) or []
    rep = evaluate(items, prefix=a.prefix, name=a.name, now=datetime.now(timezone.utc), min_left_min=a.min_left_min)
    for p in rep["pares"]:
        print("PAR:", json.dumps(p, ensure_ascii=False))
    for c in rep["comprobaciones"]:
        print(("OK    " if c["ok"] else "FALLÓ ") + c["que"])
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
