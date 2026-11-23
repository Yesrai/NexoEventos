"""Autenticación de dos pasos: contraseña (Argon2id) → OTP de 6 dígitos por correo → sesión. Estado en SQLite (0600). Roles: columna `role` (hoy solo SUPER_ADMIN_TI)."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import security as S
from .mailer import MailError

ROLE_ADMIN = "SUPER_ADMIN_TI"
OTP_TTL_S, OTP_MAX_ATTEMPTS, RESEND_MAX, RESEND_COOLDOWN_S = 300, 5, 3, 60
LOGIN_MAX_FAILS, LOGIN_WINDOW_S = 5, 900
SESSION_IDLE_S, SESSION_ABS_S = 30 * 60, 8 * 3600
GENERIC = "Credenciales inválidas"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, verifier TEXT NOT NULL, expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  resends INTEGER NOT NULL DEFAULT 0, last_sent REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL, last_seen REAL NOT NULL, csrf TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS attempts(ts REAL NOT NULL, email_hash TEXT NOT NULL, ip TEXT NOT NULL, ok INTEGER NOT NULL);
"""


class AuthError(Exception):
    def __init__(self, msg, code=401, retry_after=None):
        super().__init__(msg); self.code, self.retry_after = code, retry_after


def norm(email: str) -> str:
    return (email or "").strip().lower()


class AuthService:
    def __init__(self, cfg, mailer, audit, clock=lambda: datetime.now(timezone.utc)):
        self.cfg, self.mailer, self.audit, self.clock = cfg, mailer, audit, clock
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        self.path = Path(cfg.data_dir) / "nexoops.db"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        os.chmod(self.path, 0o600)
        self.db.executescript(SCHEMA)

    def now(self) -> float:
        return self.clock().timestamp()

    # ---- usuarios ----
    def create_user(self, email: str, password: str, role: str = ROLE_ADMIN):
        if len(password) < 12:
            raise ValueError("la contraseña debe tener al menos 12 caracteres")
        with self.lock:
            self.db.execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)", (norm(email), S.hash_password(password), role)); self.db.commit()
        self.audit.append("sistema", "usuario_creado", rol=role)

    def _user(self, email):
        return self.db.execute("SELECT * FROM users WHERE email=?", (norm(email),)).fetchone()

    # ---- limitación de intentos ----
    def _record(self, email, ip, ok):
        self.db.execute("INSERT INTO attempts VALUES(?,?,?,?)", (self.now(), S.sha256(norm(email)), ip, int(ok))); self.db.commit()

    def _locked(self, email, ip) -> int | None:
        since = self.now() - LOGIN_WINDOW_S
        for col, val in (("email_hash", S.sha256(norm(email))), ("ip", ip)):
            rows = self.db.execute(f"SELECT ts FROM attempts WHERE {col}=? AND ok=0 AND ts>? ORDER BY ts", (val, since)).fetchall()
            if len(rows) >= LOGIN_MAX_FAILS:
                return int(rows[0]["ts"] + LOGIN_WINDOW_S - self.now()) + 1
        return None

    # ---- paso 1: contraseña ----
    def login(self, email: str, password: str, ip: str = "?") -> dict:
        with self.lock:
            wait = self._locked(email, ip)
            if wait:
                self.audit.append("anonimo", "login_bloqueado", ip=ip)
                raise AuthError("Demasiados intentos; espera e inténtalo de nuevo", 429, wait)
            u = self._user(email)
            ok = S.verify_password(u["password_hash"] if u and u["active"] else None, password or "")
            self._record(email, ip, ok)
            if not ok:
                self.audit.append("anonimo", "login_fallido", ip=ip, resultado="credenciales")
                raise AuthError(GENERIC)
            cid = S.new_token(24)
            code = S.new_otp()
            t = self.now()
            self.db.execute("INSERT INTO challenges(id,user_id,verifier,expires_at,last_sent) VALUES(?,?,?,?,?)", (cid, u["id"], S.otp_verifier(self.cfg.otp_secret, cid, code), t + OTP_TTL_S, t))
            self.db.commit()
            self._send(u, cid, code)
            self.audit.append(u["email"], "login_paso1_ok", rol=u["role"], ip=ip)
            return {"challenge_id": cid, "expires_in": OTP_TTL_S}

    def _send(self, user, cid, code):
        try:
            self.mailer.send(user["email"], code)
        except MailError as e:
            self.audit.append(user["email"], "otp_envio_fallido", resultado=str(e))
            raise AuthError("No se pudo enviar el código de verificación", 502) from None

    # ---- reenvío ----
    def resend(self, cid: str) -> dict:
        with self.lock:
            c = self._challenge(cid)
            t = self.now()
            if c["resends"] >= RESEND_MAX:
                raise AuthError("Límite de reenvíos alcanzado; inicia sesión de nuevo", 429)
            if t - c["last_sent"] < RESEND_COOLDOWN_S:
                raise AuthError("Espera antes de pedir otro código", 429, int(RESEND_COOLDOWN_S - (t - c["last_sent"])) + 1)
            u = self.db.execute("SELECT * FROM users WHERE id=?", (c["user_id"],)).fetchone()
            code = S.new_otp()
            self.db.execute("UPDATE challenges SET verifier=?, expires_at=?, attempts=0, resends=resends+1, last_sent=? WHERE id=?", (S.otp_verifier(self.cfg.otp_secret, cid, code), t + OTP_TTL_S, t, cid))
            self.db.commit()
            self._send(u, cid, code)
            self.audit.append(u["email"], "otp_reenviado")
            return {"expires_in": OTP_TTL_S}

    def _challenge(self, cid):
        c = self.db.execute("SELECT * FROM challenges WHERE id=?", (cid or "",)).fetchone()
        if not c or c["consumed"]:
            raise AuthError("Verificación no válida; inicia sesión de nuevo")
        return c

    # ---- paso 2: OTP ----
    def verify_otp(self, cid: str, code: str, ip: str = "?") -> dict:
        with self.lock:
            c = self._challenge(cid)
            u = self.db.execute("SELECT * FROM users WHERE id=?", (c["user_id"],)).fetchone()
            if self.now() > c["expires_at"]:
                self.db.execute("UPDATE challenges SET consumed=1 WHERE id=?", (cid,)); self.db.commit()
                self.audit.append(u["email"], "otp_vencido")
                raise AuthError("El código venció; inicia sesión de nuevo")
            if c["attempts"] >= OTP_MAX_ATTEMPTS:
                self.db.execute("UPDATE challenges SET consumed=1 WHERE id=?", (cid,)); self.db.commit()
                raise AuthError("Demasiados intentos; inicia sesión de nuevo", 429)
            ok = S.ct_equal(S.otp_verifier(self.cfg.otp_secret, cid, str(code or "").strip()), c["verifier"])
            if not ok:
                self.db.execute("UPDATE challenges SET attempts=attempts+1 WHERE id=?", (cid,)); self.db.commit()
                self._record(u["email"], ip, False)
                self.audit.append(u["email"], "otp_incorrecto", intento=c["attempts"] + 1)
                raise AuthError("Código incorrecto")
            self.db.execute("UPDATE challenges SET consumed=1 WHERE id=?", (cid,))       # un solo uso
            tok, csrf, t = S.new_token(), S.new_token(16), self.now()
            self.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,0)", (S.sha256(tok), u["id"], t, t, csrf)); self.db.commit()
            self.audit.append(u["email"], "login_ok", rol=u["role"], ip=ip)
            return {"token": tok, "csrf": csrf, "user": {"email": u["email"], "role": u["role"]}}

    # ---- sesión ----
    def session(self, token: str | None):
        if not token:
            return None
        with self.lock:
            s = self.db.execute("SELECT * FROM sessions WHERE token_hash=?", (S.sha256(token),)).fetchone()
            t = self.now()
            if not s or s["revoked"] or t - s["last_seen"] > SESSION_IDLE_S or t - s["created"] > SESSION_ABS_S:
                return None
            u = self.db.execute("SELECT * FROM users WHERE id=? AND active=1", (s["user_id"],)).fetchone()
            if not u:
                return None
            self.db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, s["token_hash"])); self.db.commit()
            return {"email": u["email"], "role": u["role"], "csrf": s["csrf"]}

    def logout(self, token: str | None, actor="?"):
        if token:
            with self.lock:
                self.db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (S.sha256(token),)); self.db.commit()
            self.audit.append(actor, "logout")

    def revoke_all(self, email: str):
        with self.lock:
            u = self._user(email)
            if u:
                self.db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (u["id"],)); self.db.commit()
        self.audit.append(email, "sesiones_invalidadas")
