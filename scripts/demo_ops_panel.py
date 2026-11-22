#!/usr/bin/env python3
"""Demostración LOCAL del panel «Operación»: PostgreSQL DESECHABLE (initdb en /tmp, sin red) + migraciones + cuentas de PRUEBA + API FastAPI en 127.0.0.1:8000.
No toca ninguna base persistente, Docker, nube, DNS ni claves. Los registros de respaldo/failover son SIMULADOS (origen «simulado»). Ctrl+C detiene la API y borra todo.
Uso:  backend/.venv/bin/python scripts/demo_ops_panel.py [--port 8000] [--sin-datos]     (frontend aparte: cd frontend && npm run dev)"""
import argparse, json, os, secrets, signal, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from tests.pgtemp import TempCluster, available  # noqa: E402


def iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8000); ap.add_argument("--sin-datos", action="store_true", help="no crear registros simulados (todo «No verificado»)")
    a = ap.parse_args()
    if not available():
        sys.exit("initdb/pg_ctl no disponibles")
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, text
    from app.auth import hash_password
    cl = TempCluster(); api = None
    try:
        admin = cl.url("postgres")
        e = create_engine(admin, isolation_level="AUTOCOMMIT")
        with e.connect() as c:
            c.execute(text("CREATE ROLE nexoeventos_app LOGIN")); c.execute(text("CREATE ROLE nexoeventos_owner NOLOGIN")); c.execute(text("GRANT nexoeventos_owner TO postgres"))
            c.execute(text("CREATE DATABASE nexoeventos_demo OWNER nexoeventos_owner"))
        mig = cl.url("nexoeventos_demo")
        env = {**os.environ, "MIGRATION_DATABASE_URL": mig}
        r = subprocess.run([str(ROOT / "backend/.venv/bin/alembic"), "upgrade", "head"], cwd=ROOT / "backend", env=env, capture_output=True, text=True)
        if r.returncode:
            sys.exit("alembic falló:\n" + r.stderr[-1500:])
        pw = {k: "Demo-" + secrets.token_urlsafe(12) for k in ("organizer", "organizer_other", "operator")}
        users = [("organizador@example.com", "Organizador de prueba", "organizer"), ("otro-organizador@example.com", "Otro organizador (sin permiso del panel)", "organizer_other"),
                 ("operador@example.com", "Operador de prueba", "operator")]
        with create_engine(mig).begin() as c:
            for mail, name, k in users:
                c.execute(text("INSERT INTO users (id, email, display_name, password_hash, role) VALUES (gen_random_uuid(), :m, :n, :h, :r)"),
                          {"m": mail, "n": name, "h": hash_password(pw[k]), "r": "operator" if k == "operator" else "organizer"})
        ops = cl.base / "ops"; ops.mkdir(mode=0o700)
        if not a.sin_datos:
            (ops / "cycles.jsonl").write_text("\n".join(json.dumps(r) for r in [
                {"ok": True, "env": "SIMULADO", "name": "nexoeventos-rds-demo-001.cms", "finished_at": iso(130), "duration_s": 3.1, "cms_bytes": 91000},
                {"ok": True, "env": "SIMULADO", "name": "nexoeventos-rds-demo-002.cms", "finished_at": iso(12), "duration_s": 3.4, "cms_bytes": 92911}]) + "\n")
            (ops / "ledger.json").write_text(json.dumps({"state": "NONE", "run_id": None, "epoch": None}))
            (ops / "last-run.json").write_text(json.dumps({"outcome": "ABORTED", "safe_state": "SIMULADO: el primario sigue siendo el escritor; no se promovió nada", "abort_reason": "simulado: quórum de sondas no alcanzado",
                                                          "origen": "simulado", "timeline": [["PRECHECK", 1.0], ["DECIDE", 2.0]], "epoch": None}))
        s = {"app": "postgresql+psycopg://nexoeventos_app@/nexoeventos_demo?host=%s&port=%d" % (cl.base, cl.port)}
        genv = {**os.environ, "DATABASE_URL": s["app"], "TICKET_ENCRYPTION_KEY": Fernet.generate_key().decode(), "APP_ENV": "development", "OPS_PANEL_ENABLED": "1",
                "OPS_ALLOWED_EMAILS": "organizador@example.com", "WRITE_GATE_MODE": "off"}
        genv.pop("OPS_BACKUP_STATE_DIR", None); genv.pop("OPS_FAILOVER_DIR", None)
        if not a.sin_datos:
            genv["OPS_BACKUP_STATE_DIR"] = genv["OPS_FAILOVER_DIR"] = str(ops)
        creds = cl.base / "cuentas-de-prueba.json"
        fd = os.open(creds, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f: json.dump({m: pw[k] for m, _, k in users}, f)
        api = subprocess.Popen([str(ROOT / "backend/.venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(a.port)], cwd=ROOT / "backend", env=genv)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{a.port}/health", timeout=1); break
            except Exception:
                time.sleep(0.5)
        print(f"LISTO API=http://127.0.0.1:{a.port} cuentas={creds}", flush=True)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        api.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if api and api.poll() is None:
            api.terminate()
            try: api.wait(10)
            except Exception: api.kill()
        cl.stop(); print("detenido y limpiado", flush=True)


if __name__ == "__main__":
    main()
