"""Vallado en la CAPA DE DATOS (token de época monótono) y registro de promoción. Solo biblioteca estándar. LOCAL: no toca ninguna base real.

Por qué existe: un lease y una bandera local («puedo escribir») NO bastan como garantía. Un proceso pausado, con el reloj desviado o con un error puede seguir creyendo que
es el escritor. Aquí cada escritura lleva la ÉPOCA del lease con la que se hizo, y la propia base de datos la compara con la época vigente dentro de la MISMA transacción:
una época vieja (o una que nunca se instaló) se rechaza aunque el lease local, el reloj o la bandera digan lo contrario. Es el «fencing token» clásico.

Qué demuestra y qué NO (importante):
  - SÍ: si dos escritores comparten la MISMA base (p. ej. un standby viejo y uno nuevo promovidos sobre la base restaurada en OCI), solo la época mayor puede escribir.
  - NO: el RDS de AWS y la base restaurada en OCI son bases DISTINTAS; un token instalado en la base de OCI no impide que un primario vivo siga escribiendo en su RDS. Para el
    primario la única barrera es su AUTO-vallado (el lease caduca por su propio reloj y su compuerta rechaza escrituras en HTTP, en SQL y justo antes del COMMIT) y que esa compuerta
    esté activa (WRITE_GATE_MODE=enforce). Eso es una garantía condicionada a un proceso cooperante, no un vallado externo.
La tabla y el SQL son portables a PostgreSQL (UPDATE condicional dentro de la transacción).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path


class FencedOut(Exception):
    """La escritura se rechazó por vallado (época vieja, época no instalada o lease inválido)."""


class FencedDatabase:
    def __init__(self, path):
        self.path = str(path)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS fence (id INTEGER PRIMARY KEY CHECK (id = 1), epoch INTEGER NOT NULL)")
            c.execute("INSERT OR IGNORE INTO fence (id, epoch) VALUES (1, 0)")
            c.execute("CREATE TABLE IF NOT EXISTS writes (id INTEGER PRIMARY KEY AUTOINCREMENT, epoch INTEGER NOT NULL, writer TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextlib.contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            yield c
        finally:
            c.close()

    def epoch(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT epoch FROM fence WHERE id = 1").fetchone()[0]

    def raise_fence(self, epoch: int) -> None:
        """Instala la época del nuevo escritor. Monótono: nunca baja (repetir la misma es idempotente)."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("SELECT epoch FROM fence WHERE id = 1").fetchone()[0]
            if epoch < cur:
                c.execute("ROLLBACK")
                raise FencedOut(f"época {epoch} < vigente {cur}: el vallado no puede bajar")
            c.execute("UPDATE fence SET epoch = ? WHERE id = 1", (epoch,))
            c.execute("COMMIT")

    def write(self, epoch: int, writer: str, payload: str, still_valid=lambda: True) -> int:
        """Escritura vallada: lease válido ANTES, época igual a la vigente DENTRO de la transacción y lease válido otra vez justo antes del COMMIT."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                if not still_valid():
                    raise FencedOut("lease no válido antes de escribir")
                cur = c.execute("SELECT epoch FROM fence WHERE id = 1").fetchone()[0]
                if cur != epoch:
                    raise FencedOut(f"época {epoch} distinta de la vigente {cur}: escritor vallado")
                rid = c.execute("INSERT INTO writes (epoch, writer, payload) VALUES (?, ?, ?)", (epoch, writer, payload)).lastrowid
                if not still_valid():
                    raise FencedOut("el lease expiró durante la escritura: se revierte antes del COMMIT")
                c.execute("COMMIT")
                return rid
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    c.execute("ROLLBACK")
                raise

    def rows(self) -> list[tuple]:
        with self._conn() as c:
            return c.execute("SELECT id, epoch, writer, payload FROM writes ORDER BY id").fetchall()


class LedgerError(Exception):
    pass


class PromotionLedger:
    """Registro persistente (flock + reemplazo atómico) de la promoción: impide una SEGUNDA promoción automática y la ejecución simultánea de dos orquestadores.
    Estados: NONE → IN_PROGRESS → WRITER_ENABLED → PROMOTED | UNCERTAIN_DNS | DNS_REJECTED. Solo una persona puede volver a NONE (`clear`) tras revisar."""
    NONE, IN_PROGRESS, WRITER_ENABLED, PROMOTED, UNCERTAIN_DNS, DNS_REJECTED = "NONE", "IN_PROGRESS", "WRITER_ENABLED", "PROMOTED", "UNCERTAIN_DNS", "DNS_REJECTED"
    ALLOWED = {NONE: {IN_PROGRESS}, IN_PROGRESS: {NONE, WRITER_ENABLED}, WRITER_ENABLED: {PROMOTED, UNCERTAIN_DNS, DNS_REJECTED},
               PROMOTED: set(), UNCERTAIN_DNS: set(), DNS_REJECTED: set()}
    CLEAR_PHRASE = "LIBERAR PROMOCION TRAS REVISION HUMANA"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock_path = self.path.with_suffix(".lock")

    @contextlib.contextmanager
    def _locked(self):
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"state": self.NONE, "run_id": None, "epoch": None}
        except (OSError, ValueError):
            raise LedgerError("el registro de promoción es ilegible: se trata como promoción en curso (falla cerrado)")

    def _save(self, d: dict):
        d["updated_epoch"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def read(self) -> dict:
        with self._locked():
            return self._load()

    def state(self) -> str:
        try:
            return self.read()["state"]
        except LedgerError:
            return "CORRUPT"

    def begin(self, run_id: str) -> bool:
        with self._locked():
            d = self._load()
            if d["state"] != self.NONE:
                return False
            self._save({"state": self.IN_PROGRESS, "run_id": run_id, "epoch": None})
            return True

    def advance(self, run_id: str, new_state: str, epoch: int | None = None) -> None:
        with self._locked():
            d = self._load()
            if d.get("run_id") != run_id:
                raise LedgerError("el registro pertenece a otra ejecución")
            if new_state not in self.ALLOWED.get(d["state"], set()):
                raise LedgerError(f"transición no permitida: {d['state']} → {new_state}")
            d["state"] = new_state
            if epoch is not None:
                d["epoch"] = epoch
            self._save(d)

    def clear(self, confirm: str) -> None:
        """SOLO para una persona tras revisar. No lo llama ningún adaptador."""
        if confirm != self.CLEAR_PHRASE:
            raise LedgerError("confirmación incorrecta")
        with self._locked():
            self._save({"state": self.NONE, "run_id": None, "epoch": None})
