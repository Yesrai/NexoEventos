"""Standby REAL sobre PostgreSQL: sustituye al StandbyService simulado (adapters_standby.py) con la misma interfaz, pero la autoridad de escritura vive en la BASE (pg_fence) y no solo en
un archivo local o en la memoria del proceso. Pensado para ejecutarse en el sitio de recuperación junto a la API (WRITE_GATE_MODE=enforce, WRITE_GATE_ROLE=standby, mismo WRITE_GATE_HOLDER_ID).

Orden de la promoción (idempotente y reanudable; cada paso se puede repetir):
  1. lease válido y de la época indicada (si no, FencedOut)            3. se escribe el archivo de promoción (atómico; una época MAYOR lo reemplaza, una MENOR se rechaza)
  2. la BASE concede autoridad a esa época (grant_authority)           4. la API (guardián) adopta el lease por su holder_id y renueva la autoridad de la base
Si el proceso muere entre 2 y 3, repetir `enable` termina el trabajo; si muere después de 3, la API sigue renovando. Sin renovaciones, la autoridad de la base CADUCA SOLA (reloj de la base).
`disable` hace lo contrario en orden inverso de riesgo: primero revoca la autoridad en la base, después retira el archivo.
`write` hace una escritura REAL (tabla nexo_fence.write_probe) con el rol de la APLICACIÓN y la época de su lease: la base la acepta o la rechaza al COMMIT.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

from fenced_db import FencedOut  # noqa: E402


class PsycopgExecutor:
    """Ejecutor con psycopg 3 (una conexión por llamada, autocommit). `dsn` con las credenciales del rol correspondiente (guardián o aplicación)."""
    def __init__(self, **conn_kw):
        self.kw = conn_kw

    def __call__(self, sql: str, params=None) -> list[tuple]:
        import psycopg
        with psycopg.connect(**self.kw, autocommit=True) as c, c.cursor() as cur:
            cur.execute(sql, params)
            rows: list[tuple] = []
            while True:                                       # varias sentencias (precheck): se devuelve el ÚLTIMO resultado con filas
                if cur.description:
                    rows = [tuple(r) for r in cur.fetchall()]
                if not cur.nextset():
                    break
            return rows

    def tx_insert_probe(self, epoch: int, payload: str, sleep_s: float = 0.0) -> int:
        """Transacción como la de la API: declara la época de SU lease, escribe y hace COMMIT (que es donde la base decide)."""
        import psycopg
        with psycopg.connect(**self.kw) as c:
            with c.cursor() as cur:
                cur.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(int(epoch or 0)),))
                cur.execute("INSERT INTO nexo_fence.write_probe (epoch, payload) VALUES (%s, %s) RETURNING id", (int(epoch or 0), payload[:200]))
                rid = cur.fetchone()[0]
                if sleep_s:
                    cur.execute("SELECT pg_sleep(%s)", (sleep_s,))
            c.commit()
            return int(rid)


class PgStandby:
    def __init__(self, lease, fence, promote_file, app_exec: PsycopgExecutor, name: str = "standby"):
        self.lease, self.fence, self.promote_file, self.app_exec, self.name = lease, fence, Path(promote_file), app_exec, name
        self._last_epoch: int | None = None

    # --- archivo de promoción (solo un PERMISO adicional; la autoridad real está en la base)
    def promote_epoch(self) -> int | None:
        try:
            v = int(self.promote_file.read_text().strip())
            return v if v > 0 else None
        except (OSError, ValueError):
            return None

    def promote_permitted(self) -> bool:
        return self.promote_epoch() is not None

    def holds_lease_object(self) -> bool:
        return self.lease._etag is not None and not self.lease._lost

    def _db_status(self):
        try:
            return self.fence.status()
        except Exception:  # noqa: BLE001 — la base no responde: no se asume autoridad
            return None

    def writes_permitted(self) -> bool:
        """Verdad de LA BASE: lease válido + permiso de promoción + autoridad vigente de ESA época en la base. Cualquier duda = False."""
        pe, ep = self.promote_epoch(), self.lease.epoch
        if pe is None or ep is None or pe != ep or not self.lease.is_valid():
            return False
        st = self._db_status()
        return bool(st and st["valid"] and st["epoch"] == ep)

    def keeper_step(self) -> None:
        """Renueva el lease y refleja el plazo restante en la base. Si no hay lease válido o permiso, revoca."""
        if self.holds_lease_object():
            self.lease.renew()
        self._sync()

    def _sync(self) -> None:
        try:
            if self.promote_permitted() and self.lease.is_valid() and self.lease.epoch == self.promote_epoch() and self.lease.remaining_s() > 0.05:
                self._last_epoch = self.lease.epoch
                self.fence.grant(self.lease.epoch, self.lease.holder_id, self.lease.remaining_s())
            elif self._last_epoch is not None:
                self.fence.revoke(self._last_epoch)
        except Exception:  # noqa: BLE001 — sin sincronizar, la autoridad de la base caduca sola
            pass

    def enable(self, epoch: int) -> None:
        if not self.lease.is_valid() or self.lease.epoch != epoch:
            raise FencedOut("el lease no es válido o no es de la época indicada: no se habilita")
        cur = self.promote_epoch()
        if cur is not None and cur > epoch:
            raise FencedOut("existe una promoción de una época posterior: no se retrocede")
        try:
            self.fence.grant(epoch, self.lease.holder_id, self.lease.remaining_s())     # 1.º la autoridad en la BASE (idempotente; la época solo sube)
        except Exception as e:  # noqa: BLE001
            raise FencedOut(f"la base rechazó o no pudo conceder la autoridad ({type(e).__name__})")
        self._last_epoch = epoch
        tmp = self.promote_file.with_name(self.promote_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(str(epoch))
        os.replace(tmp, self.promote_file)                                               # 2.º el permiso, atómico (repetible)

    def disable(self) -> None:
        ep = self.promote_epoch() or self._last_epoch or self.lease._epoch
        if ep:
            try:
                self.fence.revoke(ep)                                                    # 1.º se quita la autoridad en la base…
            except Exception:  # noqa: BLE001
                pass                                                                     # …si falla, caduca sola
        self.promote_file.unlink(missing_ok=True)                                        # 2.º se retira el permiso

    def write(self, payload: str) -> int:
        ep = self.lease.epoch
        if ep is None or not self.lease.is_valid():
            raise FencedOut("sin lease válido: la escritura ni se intenta")
        try:
            return self.app_exec.tx_insert_probe(ep, payload)
        except Exception as e:  # noqa: BLE001 — incluye el rechazo de la base al COMMIT
            if "NEXO_FENCE" in str(e) or getattr(getattr(e, "sqlstate", None), "__str__", lambda: "")() == "NX001":
                raise FencedOut("la base rechazó la escritura (sin autoridad vigente)")
            raise FencedOut(f"escritura no confirmada ({type(e).__name__})")

    def status(self) -> dict:
        st = self._db_status() or {}
        return {"mode": "enforce", "role": "standby", "holds_lease": self.lease.is_valid(), "epoch": self.lease.epoch, "promote_permitted": self.promote_permitted(),
                "fence_epoch": st.get("epoch"), "db_authority_valid": bool(st.get("valid")), "db_authority_remaining_s": st.get("remaining_s")}
