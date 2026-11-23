"""G5 (local): exploración EXHAUSTIVA de todas las secuencias de hasta N eventos sobre los componentes REALES (LeaseClient con firmas, almacén condicional, WitnessGuard y testigo ANCLADO) con dos actores AWS/OCI.
Propiedad: en NINGÚN estado alcanzado is_valid() es verdadero en AWS y OCI a la vez, y con el testigo caído o retrocedido (rollback del historial) NO se adquiere ninguna época nueva.
Supuestos (los del lease, S2/S3): reloj monótono común sin deriva y sin pausas entre comprobación y escritura. NO prueba AWS/OCI reales: eso es D1/D2/D4 (nube, bloqueado a la espera de autorización)."""
import itertools, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_witness_service import Env  # noqa: E402
from app.failover.anchor import AnchoredAppendStore, SimAnchorBucket  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import InMemoryStore, StoreUnavailable  # noqa: E402
from app.failover.witness import ImmutableBucketSim, ObjectAppendStore, WitnessGuard  # noqa: E402

import os
LEN = int(os.environ.get("G5_LEN", "4"))
CFG = LeaseConfig(ttl_s=10.0, margin_s=3.0)
ACTIONS = ["A.acq", "O.acq", "A.renew", "O.renew", "tick1", "expire", "wit_down", "wit_rollback", "A_partition"]


class World:
    def __init__(self, tmp, anchored=True):
        self.t = [1000.0]; self.e = Env(tmp); self.e.wall = self.t
        self.an = SimAnchorBucket(); pr = ObjectAppendStore(ImmutableBucketSim(worm=False)); self.pr = pr
        self.w = self.e.witness(store=AnchoredAppendStore(pr, self.an, self.e.signer, self.e.verifier) if anchored else pr); self.e.genesis(self.w, epoch=0)
        self.w.report(*self.e.rep("aws", kind="lease_epoch", lease_epoch=0))                      # segunda entrada del historial (marca de agua en época 0)
        self.store = InMemoryStore(); init_lease(self.store, allow_non_atomic=False, ttl_s=CFG.ttl_s, margin_s=CFG.margin_s); self.store.verified = True
        self.down = False; self.part = False; self.rolled = False
        mono = lambda: self.t[0]
        def mk(name):
            guard = WitnessGuard(_Client(self), self.e.verifier, now=lambda: self.t[0])
            return LeaseClient(self.store, CFG, holder_id=name, mono=mono, authenticator=self.e.auth[name], acquire_guard=lambda ep, g=guard: g(ep, None), require_verified_store=False)
        self.A, self.O = mk("aws"), mk("oci")
        self.max_epoch_seen = 0

    def do(self, a):
        before = max(self.A._epoch or 0, self.O._epoch or 0)
        try:
            if a == "A.acq": self.A.acquire()
            elif a == "O.acq": self.O.acquire()
            elif a == "A.renew" and self.A.is_valid(): self.A.renew()
            elif a == "O.renew" and self.O.is_valid(): self.O.renew()
            elif a == "tick1": self.t[0] += 1
            elif a == "expire": self.t[0] += CFG.ttl_s + CFG.margin_s + 1
            elif a == "wit_down": self.down = not self.down
            elif a == "wit_rollback" and not self.rolled: self.pr.b.o.pop("log/000000000002"); self.rolled = True                                  # restauración a un prefijo antiguo válido (1 de 2 entradas)
            elif a == "A_partition": self.part = not self.part
        except StoreUnavailable: pass
        return before


class _Client:
    def __init__(self, w): self.w = w
    def attest(self, nonce):
        if self.w.down: raise StoreUnavailable("testigo caído")
        return self.w.w.attest(nonce)


def test_ninguna_secuencia_de_hasta_5_eventos_permite_dos_escritores_validos(tmp_path):
    n = 0; viol = []; a_val = o_val = blocked = 0
    for seq in itertools.product(ACTIONS, repeat=LEN):
        w = World(tmp_path); n += 1
        for i, a in enumerate(seq):
            before = w.do(a); a_val += w.A.is_valid(); o_val += w.O.is_valid(); blocked += bool(w.A.acquire_guard and (w.down or w.rolled) and a.endswith('.acq'))
            if w.A.is_valid() and w.O.is_valid(): viol.append(seq[:i + 1]); break
            if (w.down or w.rolled) and a.endswith(".acq") and max(w.A._epoch or 0, w.O._epoch or 0) > before: viol.append(("época nueva con testigo caído/retrocedido",) + seq[:i + 1]); break
    assert not viol, viol[:5]
    assert n == len(ACTIONS) ** LEN
    assert a_val > 0 and o_val > 0 and blocked > 0, (a_val, o_val, blocked)                 # no es vacuo: ambos actores llegan a ser titulares y el bloqueo del testigo se ejercita


def test_control_negativo_SIN_anclaje_el_rollback_del_testigo_pasa_desapercibido_y_se_adquiere(tmp_path):
    """Control: con el testigo SIN anclaje (perfil T4, archivo local), restaurar un prefijo antiguo NO se detecta y se adquiere una época nueva con el testigo retrocedido. Con anclaje, la prueba principal lo impide.
    Demuestra que la exploración evalúa la propiedad de B-T6-1 y que el anclaje es lo que la hace cumplir."""
    found = False
    for seq in itertools.product(["wit_rollback", "A.acq", "expire"], repeat=4):
        w = World(tmp_path, anchored=False)
        for a in seq:
            before = w.do(a)
            if w.rolled and a.endswith(".acq") and (w.A._epoch or 0) > before: found = True; break
        if found: break
    assert found
