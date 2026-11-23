#!/usr/bin/env python3
"""Administración del lease REAL en el almacén de OCI (objeto del bucket por PAR). `status` lee (y verifica la semántica If-Match/If-None-Match con objetos de prueba exclusivos); `init` crea el
objeto del lease UNA sola vez (If-None-Match: *; si ya existe NO lo toca). La URL del PAR va en un archivo 0600 (nunca en argumentos). No borra nada, no crea el PAR."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.failover.lease import Record, init_lease  # noqa: E402
from app.failover.store import PreconditionFailed, StoreError, build_verified_par_store  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["status", "init"]); ap.add_argument("--par-url-file", required=True); ap.add_argument("--object", default="writer-lease.json")
    ap.add_argument("--allow-http-localhost", action="store_true", help="solo pruebas locales"); ap.add_argument("--ttl", type=float, default=15.0); ap.add_argument("--margin", type=float, default=5.0)
    a = ap.parse_args(argv)
    try:
        store, rep = build_verified_par_store(a.par_url_file, a.object, allow_http_localhost=a.allow_http_localhost)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: PAR inválido ({type(e).__name__})", file=sys.stderr); return 2
    if not store.verified:
        print(json.dumps({"verificado": False, "autoprueba": rep}, indent=1)); return 1
    try:
        rv = store.read()
    except StoreError:
        print("ERROR: el almacén no respondió", file=sys.stderr); return 1
    if a.cmd == "init":
        if rv is not None:
            print("OK    el lease ya existe: no se modifica"); return 0
        try:
            init_lease(store, ttl_s=a.ttl, margin_s=a.margin)          # If-None-Match: * (crea una sola vez)
        except (PreconditionFailed, StoreError) as e:
            print(f"ERROR: no se pudo crear ({type(e).__name__})", file=sys.stderr); return 1
        print("OK    lease creado (sin titular, época 0)"); return 0
    if rv is None:
        print(json.dumps({"verificado": True, "inicializado": False})); return 1
    rec = Record.load(rv.data)
    print(json.dumps({"verificado": True, "inicializado": True, "titular": rec.holder, "epoca": rec.epoch, "liberado": rec.released, "ttl_s": rec.ttl_s, "margen_s": rec.margin_s}, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
