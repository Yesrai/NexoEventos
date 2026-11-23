#!/usr/bin/env python3
"""Sonda de ESCRITOR (se ejecuta junto a una base: en la EC2 para el primario, en el equipo local para el standby). Escribe en `nexo_fence.write_probe` con el rol de la APLICACIÓN y la época de su
lease, y registra SOLO resultados (hora UTC en ms, época, aceptada/rechazada): ningún dato de negocio, ninguna credencial. Modos:
  --once EPOCA                      un intento
  --loop EPOCA --seconds N          intenta cada 100 ms durante N segundos (para medir solapamientos con la del otro lado)
  --hold EPOCA --hold-seconds N     «escritor anterior»: abre la transacción CON autoridad, la deja abierta N segundos (más que la autoridad) y confirma: la base debe RECHAZAR el commit
Salida: JSONL en --out (0600). El DSN va en un archivo 0600."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def attempt(conninfo: str, epoch: int, hold_s: float = 0.0) -> dict:
    import psycopg
    t0 = now_ms()
    try:
        with psycopg.connect(conninfo) as c:
            cur = c.cursor()
            cur.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(int(epoch)),))
            cur.execute("INSERT INTO nexo_fence.write_probe (epoch, payload) VALUES (%s, 'sonda') RETURNING id", (int(epoch),))
            if hold_s:
                cur.execute("SELECT pg_sleep(%s)", (hold_s,))
            c.commit()
        return {"t_start": t0, "t_end": now_ms(), "epoch": int(epoch), "accepted": True}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        return {"t_start": t0, "t_end": now_ms(), "epoch": int(epoch), "accepted": False, "reason": "NEXO_FENCE" if "NEXO_FENCE" in msg else type(e).__name__}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", type=int); g.add_argument("--loop", type=int); g.add_argument("--hold", type=int)
    ap.add_argument("--seconds", type=float, default=10.0); ap.add_argument("--hold-seconds", type=float, default=5.0)
    ap.add_argument("--dsn-file", required=True); ap.add_argument("--out", required=True); ap.add_argument("--side", default="?")
    a = ap.parse_args(argv)
    p = Path(a.dsn_file)
    if not p.is_file() or p.stat().st_mode & 0o077:
        print("ERROR: el DSN debe estar en un archivo 0600", file=sys.stderr); return 2
    dsn = p.read_text().strip()
    out = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    def emit(r):
        os.write(out, (json.dumps({**r, "side": a.side}) + "\n").encode())
    if a.once is not None:
        emit(attempt(dsn, a.once))
    elif a.hold is not None:
        emit({**attempt(dsn, a.hold, a.hold_seconds), "mode": "hold"})
    else:
        end = time.monotonic() + a.seconds
        while time.monotonic() < end:
            emit(attempt(dsn, a.loop)); time.sleep(0.1)
    os.close(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
