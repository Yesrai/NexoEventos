"""Registro de auditoría de solo-añadir con cadena de hashes (cada entrada incluye el SHA-256 de la anterior). Detecta ediciones, borrados y reordenamientos
de entradas intermedias; NO impide que quien tenga el archivo lo reescriba entero (por eso se recomienda copiar el último hash fuera del servidor)."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
_SECRETISH = ("token", "password", "secret", "clave", "key")


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _clean(v, depth=0):
    if isinstance(v, dict):
        return {str(k)[:48]: ("[omitido]" if any(s in str(k).lower() for s in _SECRETISH) else _clean(x, depth + 1)) for k, x in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [_clean(x, depth + 1) for x in list(v)[:40]]
    if isinstance(v, str):
        return v[:300]
    return v if isinstance(v, (int, float, bool)) or v is None else str(v)[:300]


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)

    def append(self, actor: str, event: str, **data) -> dict:
        with open(self.path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0); n, h = 0, GENESIS
                for line in f.read().splitlines():
                    if line.strip():
                        e = json.loads(line); n, h = e["seq"], e["hash"]
                body = {"seq": n + 1, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "actor": str(actor)[:64], "event": str(event)[:48], "data": _clean(data), "prev": h}
                body["hash"] = hashlib.sha256(_canon(body)).hexdigest()
                f.seek(0, os.SEEK_END); f.write(json.dumps(body, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
                return body
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def entries(self, limit: int = 200) -> list[dict]:
        out = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        return out[-limit:]

    def verify(self) -> dict:
        prev, n = GENESIS, 0
        for i, line in enumerate(self.path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                return {"ok": False, "entradas": n, "error": f"línea {i} ilegible"}
            h = e.pop("hash", None)
            if e.get("prev") != prev or e.get("seq") != n + 1 or hashlib.sha256(_canon(e)).hexdigest() != h:
                return {"ok": False, "entradas": n, "error": f"cadena rota en la entrada {n + 1}"}
            prev, n = h, n + 1
        return {"ok": True, "entradas": n, "ultimo_hash": prev}
