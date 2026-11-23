"""Configuración por variables de entorno. Ningún secreto se escribe en el código ni se envía al navegador."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _b(v, default=False):
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes", "si", "sí")


@dataclass
class Config:
    data_dir: Path
    ops_state_dir: Path                     # estado del centro de operaciones existente (solo lectura)
    env: str = "production"                 # «dev» habilita el buzón local de OTP; en producción solo SMTP real
    cookie_secure: bool = True
    otp_secret: bytes = b""                 # clave HMAC de los verificadores OTP (NEXOOPS_OTP_SECRET)
    mail_mode: str = "smtp"                 # smtp | outbox (solo dev)
    base_path: str = ""                     # subruta detrás de Nginx (p. ej. /nexoops); vacío = raíz
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    grafana_url: str = ""
    grafana_token: str = ""
    grafana_embed: bool = False
    grafana_cafile: str = ""
    zabbix_cafile: str = ""
    zabbix_auth: str = "bearer"            # bearer (Zabbix ≥ 7.0) | body (6.x: parámetro «auth»)
    zabbix_url: str = ""
    zabbix_token: str = ""
    aws_region: str = ""
    aws_asg_names: list = field(default_factory=list)
    llm_provider: str = ""                  # vacío ⇒ diagnóstico determinista
    env_raw: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env=None):
        e = dict(os.environ if env is None else env)
        dd = Path(e.get("NEXOOPS_DATA_DIR", "work/nexoops"))
        envn = e.get("NEXOOPS_ENV", "production")
        secret = e.get("NEXOOPS_OTP_SECRET", "")
        return cls(data_dir=dd, ops_state_dir=Path(e.get("OPS_CENTER_STATE_DIR", "work/ops-center")), env=envn,
                   cookie_secure=_b(e.get("NEXOOPS_COOKIE_SECURE"), envn != "dev"), otp_secret=secret.encode(),
                   mail_mode=e.get("NEXOOPS_MAIL_MODE", "smtp"), smtp_host=e.get("NEXOOPS_SMTP_HOST", ""), smtp_port=int(e.get("NEXOOPS_SMTP_PORT", "587")),
                   smtp_user=e.get("NEXOOPS_SMTP_USER", ""), smtp_password=e.get("NEXOOPS_SMTP_PASSWORD", ""), smtp_from=e.get("NEXOOPS_SMTP_FROM", ""),
                   smtp_starttls=_b(e.get("NEXOOPS_SMTP_STARTTLS"), True),
                   grafana_url=e.get("GRAFANA_URL", "").rstrip("/"), grafana_token=e.get("GRAFANA_TOKEN", ""), grafana_embed=_b(e.get("NEXOOPS_GRAFANA_EMBED")), grafana_cafile=e.get("GRAFANA_CAFILE", ""), zabbix_cafile=e.get("ZABBIX_CAFILE", ""), zabbix_auth=e.get("ZABBIX_AUTH_MODE", "bearer"),
                   zabbix_url=e.get("ZABBIX_URL", "").rstrip("/"), zabbix_token=e.get("ZABBIX_TOKEN", ""),
                   aws_region=e.get("NEXOOPS_AWS_REGION", ""), aws_asg_names=[x for x in e.get("NEXOOPS_AWS_ASG_NAMES", "").split(",") if x.strip()],
                   llm_provider=e.get("NEXOOPS_LLM_PROVIDER", ""), base_path=e.get("NEXOOPS_BASE_PATH", "").rstrip("/"), env_raw=e)

    def validate(self):
        if len(self.otp_secret) < 32:
            raise ValueError("NEXOOPS_OTP_SECRET debe tener al menos 32 caracteres")
        if self.mail_mode == "outbox" and self.env != "dev":
            raise ValueError("el buzón local de OTP solo existe con NEXOOPS_ENV=dev")
        if self.env != "dev" and not self.cookie_secure:
            raise ValueError("las cookies deben ser Secure fuera de dev")
        if self.base_path and not re.fullmatch(r"/[a-z0-9][a-z0-9-]{0,30}", self.base_path):
            raise ValueError("NEXOOPS_BASE_PATH debe ser /<letras-minúsculas-dígitos-guiones>")
