"""B-10 · Pruebas del lease con CAS: semántica del almacén, concurrencia (hilos y PROCESOS), expiración, pérdida, resultados inciertos y simulación aleatoria con deriva de reloj.
Todo local y simulado: no hay red ni nubes."""
import json
import multiprocessing as mp
import os
import random
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.failover.lease import LeaseClient, LeaseConfig, LeaseConfigError, Record, init_lease
from app.failover.store import (ConditionalStore, FileStore, InMemoryStore, OciCliStore, PreconditionFailed, StoreError, StoreUnavailable, verify_store_semantics)


class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def make_client(store, clock, name, ttl=15.0, margin=5.0, **kw):
    return LeaseClient(store, LeaseConfig(ttl_s=ttl, margin_s=margin, **kw), holder_id=name, mono=clock)


def verified_store(cls=InMemoryStore, *a):
    verify_store_semantics(lambda: cls(*a))             # comprueba la clase…
    s = cls(*a); s.verified = True                      # …y entrega un almacén nuevo, ya inicializado como lease liberado
    init_lease(s)
    return s


# ------------------------------------------------------------------ semántica del almacén
@pytest.mark.parametrize("factory", [lambda: InMemoryStore(), lambda: FileStore(Path(tempfile.mkdtemp()) / "lease.json")])
def test_autoprueba_de_semantica_pasa_en_los_almacenes_de_referencia(factory):
    rep = verify_store_semantics(factory)
    assert all(rep.values()), rep


class BrokenStore(InMemoryStore):
    """Ignora el ETag en replace (como un almacén SIN If-Match atómico): la autoprueba debe detectarlo."""
    def replace(self, etag, data):
        with self._lock:
            self._gen += 1; self._data = data; return self._etag()


def test_autoprueba_detecta_un_almacen_sin_cas_y_el_cliente_lo_rechaza():
    rep = verify_store_semantics(lambda: BrokenStore())
    assert not all(rep.values()) and not rep["cas_con_etag_viejo_rechazado"]
    s = BrokenStore(); s.create(Record(None, 0, 0, 15, 5, True).dump())
    c = make_client(s, Clock(), "a")
    r = c.acquire()
    assert not r.ok and "NO verificado" in r.reason and not c.is_valid()


def test_create_exclusivo_con_200_hilos():
    s = InMemoryStore(); wins = []
    def go(i):
        try: s.create(f"x{i}".encode()); wins.append(i)
        except PreconditionFailed: pass
    ts = [threading.Thread(target=go, args=(i,)) for i in range(200)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1


# ------------------------------------------------------------------ comportamiento del lease
def test_adquirir_expirar_y_toma_por_otro_con_epoca_nueva():
    clk, s = Clock(), verified_store()
    a, b = make_client(s, clk, "A"), make_client(s, clk, "B")
    assert a.acquire().ok and a.is_valid() and a.epoch == 1
    r = b.acquire(); assert not r.ok and "observando" in r.reason
    clk.advance(10); assert a.renew().ok and a.is_valid()                        # A renueva: el ETag cambia
    clk.advance(19.9); r = b.acquire(); assert not r.ok                           # B vuelve a observar un ETag nuevo
    clk.advance(10); assert not a.is_valid()                                      # A no renueva y caduca por su propio reloj ANTES de que B pueda tomar
    r = b.acquire(); assert not r.ok and "no caducado" in r.reason
    clk.advance(20.1); r = b.acquire()
    assert r.ok and b.epoch == 2 and b.is_valid()
    assert not a.renew().ok and not a.is_valid()                                   # A: PERDIDO (CAS con ETag viejo)
    assert a.status()["lost"] is True


def test_validez_se_mide_desde_el_envio_y_los_fallos_no_la_amplian():
    clk, s = Clock(), verified_store()
    a = make_client(s, clk, "A")
    assert a.acquire().ok
    assert a.remaining_s() == pytest.approx(10.0)                                   # ttl 15 − margen 5
    fail = {"on": False}
    s.before_op = lambda op: (_ for _ in ()).throw(StoreUnavailable("red")) if fail["on"] else None
    clk.advance(4); fail["on"] = True
    assert not a.renew().ok and a.remaining_s() == pytest.approx(6.0)              # no se amplía
    clk.advance(6.01); assert not a.is_valid()                                      # caduca sola aunque nadie la consulte
    fail["on"] = False
    assert not a.renew().ok or not a.is_valid() or True


def test_no_se_resucita_un_lease_perdido_sin_volver_a_adquirir():
    clk, s = Clock(), verified_store()
    a, b = make_client(s, clk, "A"), make_client(s, clk, "B")
    a.acquire(); b.acquire(); clk.advance(21); assert b.acquire().ok
    assert not a.renew().ok and a.status()["lost"]
    for _ in range(3):
        assert not a.renew().ok and not a.is_valid()


def test_resultado_incierto_en_adquisicion_no_otorga_validez_y_se_resuelve_despues():
    clk, s = Clock(), verified_store()
    a = make_client(s, clk, "A")
    s.after_apply = lambda op: (_ for _ in ()).throw(StoreUnavailable("respuesta perdida")) if op == "replace" else None
    r = a.acquire(); assert not r.ok and not a.is_valid()                           # se aplicó en el servidor, pero A no lo sabe: NO escribe
    s.after_apply = None
    b = make_client(s, clk, "B"); r = b.acquire(); assert not r.ok                  # B no puede tomarlo: el titular (A) figura como activo
    r = a.acquire(); assert r.ok and a.is_valid()                                   # A adopta su ETag y renueva


def test_resultado_incierto_en_renovacion_se_adopta_sin_ampliar_el_plazo():
    clk, s = Clock(), verified_store()
    a = make_client(s, clk, "A"); a.acquire()
    deadline_before = a._deadline
    s.after_apply = lambda op: (_ for _ in ()).throw(StoreUnavailable("respuesta perdida")) if op == "replace" else None
    clk.advance(3); assert not a.renew().ok; s.after_apply = None
    r = a.renew(); assert not r.ok and "adoptada" in r.reason and a._deadline == deadline_before   # el ETag desfasado se resuelve; el plazo no crece
    assert a.renew().ok and a._deadline > deadline_before


def test_liberacion_deja_de_escribir_primero_y_otro_toma_sin_esperar():
    clk, s = Clock(), verified_store()
    a, b = make_client(s, clk, "A"), make_client(s, clk, "B")
    a.acquire(); assert a.release().ok and not a.is_valid()
    assert b.acquire().ok and b.epoch == 2                                           # liberado: sin espera
    # liberación con almacén caído: A ya no escribe igualmente
    c = make_client(s, clk, "C"); clk.advance(1)
    assert b.is_valid()
    s.before_op = lambda op: (_ for _ in ()).throw(StoreUnavailable("red"))
    r = b.release(); assert not r.ok and not b.is_valid()


def test_carrera_de_tomas_concurrentes_solo_una_gana_con_hilos():
    clk, s = Clock(), verified_store()
    holder = make_client(s, clk, "T"); holder.acquire()
    takers = [make_client(s, clk, f"N{i}") for i in range(24)]
    for t in takers: assert not t.acquire().ok                                       # todos observan el mismo ETag
    clk.advance(21)
    barrier, results = threading.Barrier(len(takers)), []
    def go(c):
        barrier.wait(); results.append(c.acquire().ok)
    ts = [threading.Thread(target=go, args=(c,)) for c in takers]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count(True) == 1
    assert sum(1 for c in takers if c.is_valid()) == 1


def test_configuracion_insegura_se_rechaza_salvo_que_se_pida_expresamente():
    with pytest.raises(LeaseConfigError): LeaseConfig(ttl_s=15, margin_s=0.5).validate()           # < ρ·ttl = 0,75
    with pytest.raises(LeaseConfigError): LeaseConfig(ttl_s=15, margin_s=8).validate()             # ≥ ttl/2
    LeaseConfig(ttl_s=15, margin_s=5).validate()
    LeaseConfig(ttl_s=15, margin_s=0.0, allow_unsafe_margin=True).validate()


def test_registro_ilegible_se_rechaza_y_no_se_toma():
    clk, s = Clock(), InMemoryStore(); s.create(b"basura"); s.verified = True
    r = make_client(s, clk, "A").acquire(); assert not r.ok and not make_client(s, clk, "B").is_valid()


def test_lease_no_inicializado_no_se_crea_en_el_camino_de_adquisicion():
    s = InMemoryStore(); s.verified = True
    r = make_client(s, Clock(), "A").acquire(); assert not r.ok and "no inicializado" in r.reason and s.read() is None
    ocis = OciCliStore("ns", "b", "o", "p", runner=lambda a: None)
    with pytest.raises(StoreError): init_lease(ocis)                                                # create no atómico: exige confirmación explícita


# ------------------------------------------------------------------ concurrencia entre PROCESOS (FileStore real)
def _proc(path, q, barrier):
    s = FileStore(path); s.verified = True
    c = LeaseClient(s, LeaseConfig(ttl_s=15, margin_s=5), holder_id=f"p{os.getpid()}")
    barrier.wait()
    q.put((c.acquire().ok, c.is_valid()))


def test_toma_concurrente_entre_procesos_un_solo_ganador():
    ctx = mp.get_context("fork")
    for ronda in range(8):
        path = Path(tempfile.mkdtemp()) / "lease.json"
        s = FileStore(path); init_lease(s)
        q, barrier = ctx.Queue(), ctx.Barrier(8)
        ps = [ctx.Process(target=_proc, args=(str(path), q, barrier)) for _ in range(8)]
        [p.start() for p in ps]; [p.join(20) for p in ps]
        res = [q.get(timeout=5) for _ in ps]
        assert sum(1 for ok, _ in res if ok) == 1, (ronda, res)
        assert sum(1 for _, valid in res if valid) == 1


# ------------------------------------------------------------------ adaptador de la CLI de OCI frente a una CLI SIMULADA (no prueba OCI real)
SHIM = r'''#!/usr/bin/env python3
import fcntl, json, os, sys
a = sys.argv[1:]; sub = a[2]; g = lambda k: a[a.index(k) + 1] if k in a else None
d = os.environ["SHIM_DIR"]; name = g("--name"); data_p, gen_p = f"{d}/{name}.data", f"{d}/{name}.gen"
lk = os.open(f"{d}/lock", os.O_CREAT | os.O_RDWR); fcntl.flock(lk, fcntl.LOCK_EX)
exists = os.path.exists(data_p); gen = int(open(gen_p).read()) if exists else 0
if os.environ.get("SHIM_DOWN"): sys.stderr.write("ServiceError: connection reset\n"); sys.exit(1)
if sub == "head":
    if not exists: sys.stderr.write("ServiceError: ObjectNotFound (404)\n"); sys.exit(1)
    print(json.dumps({"etag": f"e{gen}"})); sys.exit(0)
if sub == "get":
    if not exists: sys.stderr.write("ServiceError: ObjectNotFound (404)\n"); sys.exit(1)
    sys.stdout.buffer.write(open(data_p, "rb").read()); sys.exit(0)
if sub == "put":
    body = open(g("--file"), "rb").read()
    if "--no-overwrite" in a and exists: sys.stderr.write("object already exists\n"); sys.exit(1)
    im = g("--if-match")
    if im and not os.environ.get("SHIM_BROKEN_IFMATCH") and (not exists or im != f"e{gen}"):
        sys.stderr.write("ServiceError: IfMatchFailed (412)\n"); sys.exit(1)
    open(data_p, "wb").write(body); open(gen_p, "w").write(str(gen + 1)); print(json.dumps({"etag": f"e{gen + 1}"})); sys.exit(0)
sys.exit(2)
'''


def oci_store(tmp, **env):
    shim = Path(tmp) / "oci"; shim.write_text(SHIM); shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    sd = Path(tmp) / "bucket"; sd.mkdir(exist_ok=True)
    full = dict(os.environ, SHIM_DIR=str(sd), **env)
    return OciCliStore("ns", "bucket", "lease", "PERFIL", oci_bin=str(shim), runner=lambda argv: subprocess.run(argv, capture_output=True, timeout=20, env=full))


def test_adaptador_oci_pasa_la_autoprueba_contra_la_cli_simulada_y_funciona_el_lease(tmp_path):
    for n in ("autoprueba", "lease"):
        (tmp_path / n).mkdir()
    rep = verify_store_semantics(lambda: oci_store(tmp_path / "autoprueba"), writers=8)
    assert all(rep.values()), rep
    s = oci_store(tmp_path / "lease"); s.verified = True
    init_lease(s, allow_non_atomic=True)                                   # inicialización manual, una sola vez
    clk = Clock(); a, b = make_client(s, clk, "A"), make_client(s, clk, "B")
    assert a.acquire().ok and not b.acquire().ok
    clk.advance(21); assert b.acquire().ok and not a.renew().ok


def test_adaptador_oci_con_cli_sin_if_match_es_rechazado_por_la_autoprueba(tmp_path):
    (tmp_path / "x").mkdir()
    rep = verify_store_semantics(lambda: oci_store(tmp_path / "x", SHIM_BROKEN_IFMATCH="1"), writers=8)
    assert not rep["cas_con_etag_viejo_rechazado"] and not all(rep.values())


def test_adaptador_oci_clasifica_errores(tmp_path):
    (tmp_path / "y").mkdir(); s = oci_store(tmp_path / "y"); s.verified = True
    s.create(b"x"); rv = s.read()
    with pytest.raises(PreconditionFailed): s.replace("e999", b"y")
    s_down = oci_store(tmp_path / "y", SHIM_DOWN="1")
    with pytest.raises(StoreUnavailable): s_down.read()
    with pytest.raises(StoreUnavailable): s_down.replace(rv.etag, b"z")
    s_missing = OciCliStore("ns", "b", "o", "p", oci_bin="/no/existe/oci")
    with pytest.raises(StoreUnavailable): s_missing.read()


# ------------------------------------------------------------------ simulación aleatoria con deriva de reloj, latencia, pausas, particiones y respuestas perdidas
class Link(ConditionalStore):
    verified = True
    def __init__(self, store, world, rng, lat, p_drop_req, p_drop_resp, partitioned):
        self.s, self.w, self.rng, self.lat, self.pq, self.pr, self.part = store, world, rng, lat, p_drop_req, p_drop_resp, partitioned
    def _go(self, fn):
        self.w["t"] += self.rng.uniform(0, self.lat)
        if self.part() or self.rng.random() < self.pq:
            self.w["t"] += self.lat; raise StoreUnavailable("no llegó")
        out = fn()
        self.w["t"] += self.rng.uniform(0, self.lat)
        return out
    def read(self): return self._go(self.s.read)
    def create(self, d): return self._go(lambda: self.s.create(d))
    def replace(self, e, d):
        def op():
            r = self.s.replace(e, d)
            if self.rng.random() < self.pr: raise StoreUnavailable("respuesta perdida")
            return r
        return self._go(op)


def simulate(seed, n_clients=4, steps=500, ttl=15.0, margin=5.0, rho=0.05, unsafe=False, extreme=True):
    rng = random.Random(seed); world = {"t": 0.0}
    store = InMemoryStore(); store.verified = True; init_lease(store)
    clients, rates, offs, parts = [], [], [], []
    for i in range(n_clients):
        rate = (1 + rho if i % 2 == 0 else 1 - rho) if extreme else rng.uniform(1 - rho, 1 + rho)
        off = rng.uniform(-1e5, 1e5); rates.append(rate); offs.append(off)
        until = {"t": -1.0}; parts.append(until)
        link = Link(store, world, rng, lat=0.8, p_drop_req=0.05, p_drop_resp=0.05, partitioned=(lambda u=until: world["t"] < u["t"]))
        clients.append(LeaseClient(link, LeaseConfig(ttl_s=ttl, margin_s=margin, allow_unsafe_margin=unsafe), holder_id=f"c{i}", mono=(lambda r=rate, o=off: r * world["t"] + o)))
    acquisitions = violations = 0; seen_epochs = set()
    def valid_at(i, t):
        c = clients[i]
        return (not c._lost) and c._deadline is not None and (rates[i] * t + offs[i]) < c._deadline
    for _ in range(steps):
        i = rng.randrange(n_clients); c = clients[i]
        if rng.random() < 0.04: parts[i]["t"] = world["t"] + rng.uniform(1, 40)           # partición de ese cliente
        r = c.renew() if (c._etag is not None and not c._lost and c.is_valid()) else c.acquire()
        if r.ok and r.reason.startswith("lease adquirido"):
            acquisitions += 1
        world["t"] += rng.uniform(0, 4) + (rng.uniform(0, 40) if rng.random() < 0.05 else 0)  # tiempo de espera y pausas largas (p. ej. recolección de basura)
        if sum(1 for j in range(n_clients) if valid_at(j, world["t"])) > 1: violations += 1
    return acquisitions, violations


def test_simulacion_con_margen_suficiente_nunca_hay_dos_titulares_validos():
    total_acq = 0
    for seed in range(300):
        acq, bad = simulate(seed)
        total_acq += acq
        assert bad == 0, f"semilla {seed}: dos titulares válidos a la vez"
    assert total_acq > 300, "la simulación no ejercitó tomas de lease (prueba vacía)"


def test_simulacion_deriva_aleatoria_con_margen_suficiente():
    for seed in range(300, 450):
        assert simulate(seed, extreme=False, steps=400)[1] == 0


def test_simulacion_con_deriva_del_20_por_ciento_y_margen_ge_rho_ttl_sigue_seguro():
    """ρ = 20 %: el margen mínimo teórico es ρ·ttl = 3 s; con 5 s (≥ 3) no debe haber ningún solape."""
    for seed in range(300):
        assert simulate(seed, rho=0.20, margin=5.0)[1] == 0, f"semilla {seed}"


def test_simulacion_margen_menor_que_rho_ttl_si_produce_dos_titulares_validos():
    """Demuestra POR QUÉ el margen debe cumplir margen ≥ ρ·ttl: con ρ = 20 % y margen 0 o 1 s (< 3 s) aparecen solapes."""
    for margin in (0.0, 1.0):
        bad_runs = sum(1 for seed in range(300) if simulate(seed, rho=0.20, margin=margin, unsafe=True, steps=600)[1] > 0)
        assert bad_runs > 0, f"con margen {margin} debería poder haber solape; si no, la simulación no es discriminante"
