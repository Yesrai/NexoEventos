"""Regresión (22-nov): una MISMA instancia de Witness usada por varios hilos rompía la cadena (se leía «secuencia nueva + hash viejo»). La instancia debe ser segura entre hilos; las
instancias distintas siguen coordinándose por la precondición del almacén. Se repite varias veces porque el fallo era intermitente."""
import json, random, sys, threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_witness_service import Env  # noqa: E402
from app.failover.witness import FileAppendStore  # noqa: E402


def chain_ok(store):
    prev = "0" * 64
    for line in store.lines():
        e = json.loads(line); assert e["prev"] == prev, "cadena rota"; prev = e["hash"]


@pytest.mark.parametrize("ronda", range(25))
def test_una_misma_instancia_entre_hilos_no_rompe_la_cadena(tmp_path, ronda):
    e = Env(tmp_path); store = FileAppendStore(tmp_path / "c.jsonl"); w = e.witness(store=store, max_epoch_jump=1000); e.genesis(w)
    eps = list(range(1, 41)); random.Random(ronda).shuffle(eps); res, lock = [], threading.Lock()
    def worker(chunk):
        for ep in chunk:
            r = w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))
            with lock: res.append((ep, r[0]))
    ths = [threading.Thread(target=worker, args=(eps[i::8],)) for i in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
    chain_ok(store); final = e.witness(store=store, max_epoch_jump=1000)
    assert final.wm["lease_epoch"] == 40 and final.entries == 1 + sum(1 for _, ok in res if ok)


@pytest.mark.parametrize("ronda", range(10))
def test_cuatro_instancias_con_hilos_compartidos_tampoco_rompen_la_cadena(tmp_path, ronda):
    e = Env(tmp_path); store = FileAppendStore(tmp_path / "c.jsonl"); inst = [e.witness(store=store, max_epoch_jump=1000) for _ in range(4)]; e.genesis(inst[0])
    eps = list(range(1, 41)); random.Random(100 + ronda).shuffle(eps)
    def worker(i, chunk):
        for ep in chunk: inst[i % 4].report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))
    ths = [threading.Thread(target=worker, args=(i, eps[i::8])) for i in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
    chain_ok(store); assert e.witness(store=store, max_epoch_jump=1000).wm["lease_epoch"] == 40
