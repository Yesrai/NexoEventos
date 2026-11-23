"""Envío del OTP. `SmtpMailer` (proveedor transaccional por SMTP, credenciales solo en el servidor), `OutboxMailer` (SOLO dev: archivo 0600 local, nunca en producción) y `CaptureMailer` (pruebas).
Ningún mailer registra el cuerpo del mensaje en logs. El envío real NO está verificado hasta ejecutar `python -m nexoops send-test-mail` contra el proveedor configurado."""
from __future__ import annotations

import os
import smtplib
from .tls import trusted_context
from email.message import EmailMessage
from pathlib import Path

SUBJECT = "NexoOps — código de verificación"


def body(code: str) -> str:
    return (f"Tu código de verificación de NexoOps es: {code}\n\nCaduca en 5 minutos y solo sirve una vez.\n"
            "Si no intentaste iniciar sesión, ignora este mensaje y avisa al equipo de TI.\n")


class MailError(Exception):
    pass


class SmtpMailer:
    def __init__(self, cfg):
        if not (cfg.smtp_host and cfg.smtp_from):
            raise MailError("SMTP sin configurar (NEXOOPS_SMTP_HOST / NEXOOPS_SMTP_FROM)")
        self.c = cfg

    def send(self, to: str, code: str):
        m = EmailMessage(); m["From"], m["To"], m["Subject"] = self.c.smtp_from, to, SUBJECT; m.set_content(body(code))
        try:
            if self.c.smtp_port == 465:
                s = smtplib.SMTP_SSL(self.c.smtp_host, self.c.smtp_port, timeout=15, context=trusted_context())
            else:
                s = smtplib.SMTP(self.c.smtp_host, self.c.smtp_port, timeout=15)
                if self.c.smtp_starttls:
                    s.starttls(context=trusted_context())
            with s:
                if self.c.smtp_user:
                    s.login(self.c.smtp_user, self.c.smtp_password)
                s.send_message(m)
        except (OSError, smtplib.SMTPException) as e:
            raise MailError(f"fallo de envío ({type(e).__name__})") from None


class OutboxMailer:
    """SOLO desarrollo local: deja el código en un archivo 0600 para poder probar sin proveedor. NO es envío de correo."""
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, to: str, code: str):
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"to={to}\ncode={code}\n")


class CaptureMailer:
    def __init__(self): self.sent = []
    def send(self, to, code): self.sent.append((to, code))


def build(cfg):
    if cfg.mail_mode == "outbox":
        return OutboxMailer(cfg.data_dir / "dev-outbox.txt")
    return SmtpMailer(cfg)
