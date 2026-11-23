"""Carrera de ADQUISICIÓN del lease sobre un almacén condicional (real o falso): comprueba la exclusividad de `LeaseClient.acquire()`, no solo la del CAS.
Cada ronda: N clientes NUEVOS (ninguno es «el titular anterior») observan el mismo ETag, esperan ttl+margen y, tras una barrera, llaman a `acquire()` a la vez.
Propiedades exigidas en CADA ronda (cualquier violación se registra y el resultado es FALLO, no se promedia):
  P1 exactamente un cliente obtiene el lease · P2 como máximo un cliente reporta `is_valid()` · P3 el registro final nombra a ese cliente y su época = anterior + 1 (nunca retrocede ni se repite)
  P4 los demás reciben una negativa explícita (nunca un éxito) · P5 un resultado distinto de éxito/negativa (timeout, error) es INCONCLUSO y la ronda no cuenta como aprobada.
Sin dependencias de nube: el almacén lo pone quien llama (en T1, el PAR real de OCI; en las pruebas, un servidor HTTP local con y sin If-Match efectivo)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.failover.lease import LeaseClient, LeaseConfig, Record  # noqa: E402
from app.failover.store import StoreError  # noqa: E402


def race_once(store_factory, round_no: int, contenders: int, cfg: LeaseConfig, prev_epoch: int, clock=time.monotonic, sleep=time.sleep) -> dict:
    clients = [LeaseClient(store_factory(), cfg, f"R{round_no}-{i}", clock) for i in range(contenders)]
    res: dict[int, object] = {}
    bar = threading.Barrier(contenders)
    # fase 1: todos observan el mismo registro (acquire devuelve «observando»)
    obs = [c.acquire() for c in clients]
    early = [i for i, r in enumerate(obs) if getattr(r, "ok", False) is True]     # nadie debe poder tomar un lease aún vigente durante la observación
    need = cfg.ttl_s + cfg.margin_s
    sleep(need + 0.15)
    def go(i):
        try:
            bar.wait(timeout=10); res[i] = clients[i].acquire()
        except Exception as exc:  # noqa: BLE001 — cualquier excepción es resultado INCONCLUSO, nunca éxito
            res[i] = exc
    ts = [threading.Thread(target=go, args=(i,)) for i in range(contenders)]; [t.start() for t in ts]; [t.join(30) for t in ts]
    wins = [i for i, r in res.items() if getattr(r, "ok", False) is True]
    refused = [i for i, r in res.items() if getattr(r, "ok", None) is False]
    inconcl = [i for i in range(contenders) if i not in res or isinstance(res[i], Exception)]
    valid = [i for i, c in enumerate(clients) if c.is_valid()]
    final_holder = final_epoch = None
    try:
        rv = store_factory().read(); rec = Record.load(rv.data); final_holder, final_epoch = rec.holder, rec.epoch
    except (StoreError, Exception):  # noqa: BLE001
        pass
    viol = []
    if early: viol.append(f"P0: {len(early)} clientes tomaron el lease durante la observación (toma inmediata inesperada)")
    if len(wins) != 1: viol.append(f"P1: {len(wins)} clientes obtuvieron el lease")
    if len(valid) > 1: viol.append(f"P2: {len(valid)} clientes válidos a la vez")
    if len(wins) == 1 and (final_holder != clients[wins[0]].holder_id or final_epoch != prev_epoch + 1): viol.append(f"P3: registro final ({final_holder}, época {final_epoch}) ≠ ganador, época {prev_epoch + 1}")
    if len(refused) != contenders - len(wins) - len(inconcl): viol.append("P4: respuestas no clasificadas")
    return {"ronda": round_no, "ganadores": len(wins), "validos": len(valid), "negativas": len(refused), "inconclusos": len(inconcl), "epoca_final": final_epoch,
            "violaciones": viol, "aprobada": not viol and not inconcl, "razones_negativas": sorted({getattr(res[i], "reason", "")[:40] for i in refused})}


def current_epoch(store_factory) -> int | None:
    try:
        return Record.load(store_factory().read().data).epoch
    except Exception:  # noqa: BLE001
        return None


def run_race(store_factory, rounds: int, contenders: int, cfg: LeaseConfig, deadline_s: float | None = None, clock=time.monotonic) -> dict:
    """Parte de un lease YA TOMADO por un cliente «primer» (el registro recién inicializado está liberado y admite una toma inmediata legítima que contaminaría la ronda 0)."""
    primer = LeaseClient(store_factory(), cfg, "primer", clock).acquire()
    prev = current_epoch(store_factory)
    if prev is None:
        return _summary([], rounds, contenders, cfg, f"no se pudo leer el lease inicial (primer: {getattr(primer, 'reason', primer)})")
    t0, out = clock(), []
    for r in range(rounds):
        if deadline_s is not None and clock() - t0 > deadline_s:
            return _summary(out, rounds, contenders, cfg, f"detenido por plazo ({deadline_s:.0f} s) tras {len(out)} rondas")
        row = race_once(store_factory, r, contenders, cfg, prev, clock); out.append(row)
        if row["ganadores"] == 1 and row["epoca_final"] is not None: prev = row["epoca_final"]
        elif row["violaciones"] or row["inconclusos"]: break
    return _summary(out, rounds, contenders, cfg, None)


def _summary(rows, rounds, contenders, cfg, stopped) -> dict:
    ok_rounds = sum(1 for r in rows if r["aprobada"])
    return {"rondas_pedidas": rounds, "rondas_ejecutadas": len(rows), "rondas_aprobadas": ok_rounds, "contendientes": contenders, "ttl_s": cfg.ttl_s, "margin_s": cfg.margin_s,
            "rondas_con_mas_de_un_ganador": sum(1 for r in rows if r["ganadores"] > 1), "rondas_sin_ganador": sum(1 for r in rows if r["ganadores"] == 0),
            "rondas_con_validos_simultaneos": sum(1 for r in rows if r["validos"] > 1), "inconclusos": sum(r["inconclusos"] for r in rows), "detenido": stopped,
            "exclusividad_demostrada": bool(rows) and ok_rounds == rounds and len(rows) == rounds, "detalle": rows}
