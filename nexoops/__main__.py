"""CLI: `create-admin`, `send-test-mail`, `serve`. La contraseña del administrador se pide por terminal (getpass) y no se guarda en historial ni logs."""
from __future__ import annotations

import argparse
import getpass
import sys

from .config import Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nexoops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-admin"); sub.add_parser("send-test-mail"); sub.add_parser("check-integrations"); sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8088)
    a = ap.parse_args(argv)
    cfg = Config.from_env(); cfg.validate()
    if a.cmd == "create-admin":
        import os
        from ops_center.audit import AuditLog
        from .auth import AuthService
        from . import mailer
        email = os.environ.get("NEXOOPS_ADMIN_EMAIL") or input("Correo del SUPER_ADMIN_TI: ")
        pw = getpass.getpass("Contraseña (≥12 caracteres): ")
        if pw != getpass.getpass("Repite la contraseña: "):
            sys.exit("las contraseñas no coinciden")
        AuthService(cfg, mailer.CaptureMailer(), AuditLog(cfg.data_dir / "audit.jsonl")).create_user(email, pw)
        print("Administrador creado.")
    elif a.cmd == "send-test-mail":
        import os
        from . import mailer
        to = os.environ.get("NEXOOPS_ADMIN_EMAIL") or input("Destino: ")
        mailer.build(cfg).send(to, "000000"); print("Envío aceptado por el proveedor (confirma la recepción en la bandeja; código de prueba 000000).")
    elif a.cmd == "check-integrations":
        from . import checks
        from .integrations.aws import Aws
        from .integrations.grafana import Grafana
        from .integrations.zabbix import Zabbix
        res = checks.run(cfg, Grafana(cfg), Zabbix(cfg), Aws(cfg))
        for r in res["results"]:
            print(f"{r['result']:<15} {r['check']:<40} {r['detail']}")
        print("resumen:", res["summary"])
    else:
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
