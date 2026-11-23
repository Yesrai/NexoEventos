#!/usr/bin/env python3
"""Dry-run de preparación para WRITE_GATE_MODE=enforce (solo lectura; ver backend/app/failover/enforce_readiness.py). Lee la configuración del entorno actual (WRITE_GATE_*), NO la cambia.
Opcional: --monitor-url-file ARCHIVO (URL SQLAlchemy de un rol de MONITOREO de la base; archivo 0600) para el detector de escritores externos; --selftest-writes SOLO contra un almacén de ensayo.
Códigos: 0 SEGURO_PARA_ACTIVAR · 1 NO_SEGURO · 2 NO_VERIFICADO."""
import argparse, json, os, stat, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--monitor-url-file"); ap.add_argument("--app-role", default="nexoeventos_app"); ap.add_argument("--selftest-writes", action="store_true")
    a = ap.parse_args(argv)
    from app.failover.enforce_readiness import check_enforce_readiness
    from app.failover.external_writers import scan_external_writers
    from app.main import create_app
    ext = None
    if a.monitor_url_file:
        p = Path(a.monitor_url_file)
        if not p.is_file() or p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            print("RECHAZADO: el archivo de la URL de monitoreo debe existir con permisos 0600", file=sys.stderr); return 2
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        eng = create_engine(p.read_text().strip(), poolclass=NullPool)
        def ex(sql, params=None):
            with eng.connect() as c:
                r = c.exec_driver_sql(sql, params or {}); return [tuple(x) for x in r.fetchall()] if r.returns_rows else []
        ext = lambda: scan_external_writers(ex, app_role=a.app_role).as_dict()
    original = dict(os.environ)
    os.environ["WRITE_GATE_MODE"] = "off"               # el dry-run construye la app SIN compuerta: nunca activa nada ni lanza la autoprueba de arranque
    try:
        app = create_app()
    finally:
        os.environ.clear(); os.environ.update(original)
    rep = check_enforce_readiness(original, app=app, external_check=ext, selftest_writes=a.selftest_writes)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return {"SEGURO_PARA_ACTIVAR": 0, "NO_SEGURO": 1}.get(rep["veredicto"], 2)


if __name__ == "__main__":
    sys.exit(main())
