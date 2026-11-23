"""CLI: `create-admin`, `send-test-mail`, `serve`. La contraseña del administrador se pide por terminal (getpass) y no se guarda en historial ni logs."""
from __future__ import annotations

import argparse
import getpass
import sys

from .config import Config


ENV_FILE_DEFAULT = "work/nexoops/nexoops.env"


def load_env_file(path=None):
    """Carga KEY=VALUE de un archivo 0600 (sin sobrescribir el entorno ya definido). Así los secretos no pasan por argumentos ni por el historial del shell."""
    import os
    from pathlib import Path
    p = Path(path or os.environ.get("NEXOOPS_ENV_FILE", ENV_FILE_DEFAULT))
    if not p.is_file():
        return
    if p.stat().st_mode & 0o077:
        sys.exit(f"{p} debe tener permisos 0600")
    for line in p.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v)


def configure_smtp():
    """Pide correo y contraseña de aplicación de Gmail por terminal (getpass: sin eco ni historial) y los guarda en un archivo 0600 fuera de git."""
    import os
    import secrets
    from pathlib import Path
    p = Path(os.environ.get("NEXOOPS_ENV_FILE", ENV_FILE_DEFAULT)); p.parent.mkdir(parents=True, exist_ok=True)
    email = input("Cuenta de Gmail (usuario y remitente): ").strip()
    pw = getpass.getpass("Contraseña de aplicación de Google (no se muestra): ").replace(" ", "")
    if "@" not in email or len(pw) != 16:
        sys.exit("correo inválido o la contraseña de aplicación no tiene 16 caracteres")
    old = {}
    if p.exists():
        old = dict(l.split("=", 1) for l in p.read_text().splitlines() if "=" in l)
    vals = {"NEXOOPS_ENV": "dev", "NEXOOPS_COOKIE_SECURE": "0", "NEXOOPS_MAIL_MODE": "smtp", "NEXOOPS_SMTP_HOST": "smtp.gmail.com", "NEXOOPS_SMTP_PORT": "465", "NEXOOPS_SMTP_USER": email,
            "NEXOOPS_SMTP_FROM": email, "NEXOOPS_SMTP_PASSWORD": pw, "NEXOOPS_ADMIN_EMAIL": email, "NEXOOPS_OTP_SECRET": old.get("NEXOOPS_OTP_SECRET") or secrets.token_urlsafe(48)}
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n")
    print(f"Guardado en {p} (0600). Contraseña no mostrada.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nexoops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-admin"); sub.add_parser("configure-smtp"); sub.add_parser("send-test-mail"); sub.add_parser("check-integrations"); sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8088)
    a = ap.parse_args(argv)
    if a.cmd == "configure-smtp":
        return configure_smtp()
    load_env_file()
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
