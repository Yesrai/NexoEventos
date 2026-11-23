"""Identidades de SERVICIO/operador del centro de operaciones: tokens aleatorios (≥ 32 bytes) guardados solo como SHA-256 en un archivo 0600.
Roles (mínimo privilegio; ninguno puede ejecutar nada): viewer (leer) · requester (leer + solicitar/cancelar lo propio) · approver (leer + aprobar/denegar lo ajeno).
No reutiliza credenciales de AWS/OCI/Azure ni cuentas de la aplicación."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from pathlib import Path

ROLES = ("viewer", "requester", "approver")
PERMS = {"viewer": {"read"}, "requester": {"read", "request"}, "approver": {"read", "decide"}}


class IdentityError(Exception):
    pass


def new_token() -> str:
    return secrets.token_urlsafe(40)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load(path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise IdentityError("archivo de identidades ausente")
    if stat.S_IMODE(p.stat().st_mode) & 0o077:
        raise IdentityError("el archivo de identidades debe tener permisos 0600")
    data = json.loads(p.read_text())
    ids = {}
    for it in data.get("identities", []):
        if it.get("role") not in ROLES or not str(it.get("id", "")).strip() or len(str(it.get("token_sha256", ""))) != 64:
            raise IdentityError("identidad inválida (rol, id o hash)")
        if it["id"] in ids:
            raise IdentityError("identidad duplicada")
        ids[it["id"]] = {"role": it["role"], "token_sha256": it["token_sha256"]}
    if not ids:
        raise IdentityError("sin identidades: el servicio se niega a arrancar abierto")
    return ids


class Authenticator:
    """Comparación en tiempo constante contra TODAS las identidades; bloqueo temporal por origen tras fallos repetidos."""
    def __init__(self, identities: dict, max_failures=5, block_s=300, clock=time.monotonic):
        self.ids, self.max, self.block, self.clock = identities, max_failures, block_s, clock
        self.fail: dict[str, list] = {}

    def blocked(self, who: str) -> bool:
        n, until = self.fail.get(who, [0, 0.0])
        return n >= self.max and self.clock() < until

    def check(self, header: str | None, who: str = "?"):
        if self.blocked(who):
            return None, "bloqueado"
        found = None
        tok = header[7:].strip() if header and header.lower().startswith("bearer ") else ""
        h = hash_token(tok) if tok else ""
        for ident, rec in self.ids.items():
            if tok and hmac.compare_digest(h, rec["token_sha256"]):
                found = ident
        if found:
            self.fail.pop(who, None)
            return {"id": found, "role": self.ids[found]["role"]}, None
        n = self.fail.get(who, [0, 0.0])[0] + 1
        self.fail[who] = [n, self.clock() + self.block]
        return None, "credencial inválida"


def can(role: str, perm: str) -> bool:
    return perm in PERMS.get(role, set())
