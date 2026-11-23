"""Vallado EXTERNO de la base de datos del primario (PostgreSQL): lo aplica un tercero (el orquestador, con credenciales de administrador) y lo hace cumplir el SERVIDOR, no el proceso
de la aplicación. Complementa —no sustituye— al auto-vallado (lease + compuerta): si la aplicación del primario está congelada, mal configurada (compuerta en `off`) o ignora su lease, el
servidor de base de datos igualmente rechaza sus escrituras.

Modos (el rol es el de la APLICACIÓN, nunca el administrador):
  nologin   ALTER ROLE <rol> NOLOGIN + terminar sus sesiones: la aplicación no puede conectarse ni escribir ni leer (falla cerrada). Reversible con unfence().
  readonly  REVOKE INSERT/UPDATE/DELETE/TRUNCATE sobre las tablas del esquema + terminar sesiones: puede leer, no escribir; el rol NO puede revertirlo (un `SET default_transaction_read_only`
            sería anulable por la propia sesión). unfence() restaura exactamente los privilegios registrados antes.
Requisitos y límites: hay que ALCANZAR la base del primario (si está aislada del orquestador solo queda el auto-vallado); una sesión de otro rol privilegiado (propietario/administrador) NO queda
vallada; se prueba contra un PostgreSQL local DESECHABLE, no contra RDS (RDS puede restringir privilegios del administrador: sin verificar).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class FenceError(Exception):
    pass


def _q(ident: str) -> str:
    if not _IDENT.match(ident or ""):
        raise FenceError("identificador de rol/esquema inválido")
    return '"' + ident + '"'


@dataclass
class DbFence:
    """`execute(sql, params=None) -> list[tuple]`: ejecutor con credenciales de administrador (en pruebas, un Engine desechable). `schema` y `role` validados."""
    execute: object
    role: str
    schema: str = "public"
    mode: str = "nologin"
    saved: dict = field(default_factory=dict)

    def __post_init__(self):
        _q(self.role), _q(self.schema)
        if self.mode not in ("nologin", "readonly"):
            raise FenceError("modo de vallado desconocido")

    def _terminate(self) -> int:
        rows = self.execute("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE usename = %(r)s AND pid <> pg_backend_pid()", {"r": self.role})
        return int(rows[0][0]) if rows else 0

    def fence(self) -> dict:
        """Idempotente. Devuelve {mode, sesiones_terminadas}. Cualquier error SQL se propaga como FenceError: el llamador NO debe asumir que quedó vallado."""
        try:
            if self.mode == "nologin":
                self.execute(f"ALTER ROLE {_q(self.role)} NOLOGIN")
            else:
                grants = self.execute("SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee = %(r)s AND table_schema = %(s)s "
                                      "AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE') ORDER BY 1, 2", {"r": self.role, "s": self.schema})
                if grants:                                          # solo se registra lo que realmente había (un segundo fence() no pisa lo guardado)
                    self.saved["grants"] = [(t, p) for t, p in grants]
                self.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA {_q(self.schema)} FROM {_q(self.role)}")
            return {"mode": self.mode, "sesiones_terminadas": self._terminate()}
        except FenceError:
            raise
        except Exception as e:  # noqa: BLE001
            raise FenceError(f"no se pudo aplicar el vallado ({type(e).__name__})")

    def unfence(self) -> None:
        """Solo para el failback decidido por una persona."""
        try:
            if self.mode == "nologin":
                self.execute(f"ALTER ROLE {_q(self.role)} LOGIN")
            else:
                for table, priv in self.saved.get("grants", []):
                    if not _IDENT.match(table):
                        raise FenceError("nombre de tabla inesperado en los privilegios guardados")
                    self.execute(f"GRANT {priv} ON {_q(self.schema)}.{_q(table)} TO {_q(self.role)}")
        except FenceError:
            raise
        except Exception as e:  # noqa: BLE001
            raise FenceError(f"no se pudo revertir el vallado ({type(e).__name__})")
