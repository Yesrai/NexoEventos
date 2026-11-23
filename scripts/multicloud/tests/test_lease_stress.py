"""Estrés del lease: muchos controladores compiten por la misma autoridad con un almacén CAS atómico (hilos, reloj real, TTL corto). Propiedades:
(1) en ningún instante hay dos controladores con lease VÁLIDO a la vez; (2) cada época la ostenta un solo titular y las épocas solo crecen;
(3) CONTROL NEGATIVO: con un almacén que NO es atómico (replace sin comprobar ETag) la misma prueba SÍ detecta dos titulares válidos (si no lo detectara, la prueba no valdría nada)."""
import sys, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import InMemoryStore, ObjectVersion  # noqa: E402


class BrokenStore(InMemoryStore):
    """NO atómico: acepta cualquier replace (lo que pasaría con un almacén sin If-Match efectivo)."""
    def replace(self, etag, data):
        with self._lock:
            self._gen += 1; self._data = data; return self._etag()


def correr(store, n=8, secs=4.0):
    init_lease(store, ttl_s=1.0, margin_s=0.2)
    cfg = LeaseConfig(ttl_s=1.0, margin_s=0.2)
    clientes = [LeaseClient(store, cfg, holder_id=f"c{i}", require_verified_store=False) for i in range(n)]
    stop = time.monotonic() + secs
    epocas: dict[int, set] = {}; lock = threading.Lock(); violaciones = []

    def bucle(c):
        while time.monotonic() < stop:
            r = c.renew() if c.is_valid() else c.acquire()
            if c.is_valid():
                with lock: epocas.setdefault(c.epoch, set()).add(c.holder_id)
            time.sleep(0.02 + (hash(c.holder_id) % 7) / 200)

    def observador():
        while time.monotonic() < stop:
            validos = [c.holder_id for c in clientes if c.is_valid()]
            if len(validos) > 1: violaciones.append(validos)
            time.sleep(0.005)
    hs = [threading.Thread(target=bucle, args=(c,)) for c in clientes] + [threading.Thread(target=observador)]
    [h.start() for h in hs]; [h.join() for h in hs]
    return epocas, violaciones


class LeaseStress(unittest.TestCase):
    def test_con_cas_atomico_nunca_hay_dos_titulares_validos_y_cada_epoca_tiene_un_solo_titular(self):
        epocas, viol = correr(InMemoryStore())
        self.assertTrue(epocas, "nadie llegó a ostentar el lease")
        self.assertEqual(viol, [], f"dos controladores válidos a la vez: {viol[:3]}")
        self.assertTrue(all(len(h) == 1 for h in epocas.values()), epocas)
        self.assertEqual(sorted(epocas), list(range(min(epocas), max(epocas) + 1)) if len(epocas) < 2 else sorted(epocas))

    def _toma_simultanea(self, store, n=12):
        """Muere el titular; todos los demás observan el mismo registro, esperan ttl+margen y toman EXACTAMENTE a la vez (barrera)."""
        init_lease(store, ttl_s=1.0, margin_s=0.2); cfg = LeaseConfig(ttl_s=1.0, margin_s=0.2)
        muerto = LeaseClient(store, cfg, holder_id="muerto", require_verified_store=False); self.assertTrue(muerto.acquire().ok)
        otros = [LeaseClient(store, cfg, holder_id=f"o{i}", require_verified_store=False) for i in range(n)]
        for c in otros: c.acquire()                                  # empiezan a observar (aún no pueden tomar)
        time.sleep(1.5)
        barrera = threading.Barrier(n); res = []
        # Todos LEEN el mismo registro antes de que nadie escriba: es el entrelazado más adverso (leer→escribir) y lo fuerza, no lo espera.
        store.after_apply = lambda op: barrera.wait(10) if op == "read" else None
        def tomar(c):
            res.append((c.holder_id, c.acquire().ok))
        hs = [threading.Thread(target=tomar, args=(c,)) for c in otros]; [h.start() for h in hs]; [h.join() for h in hs]
        store.after_apply = None
        return [h for h, ok in res if ok], [c.holder_id for c in otros if c.is_valid()]

    def test_toma_simultanea_con_cas_atomico_solo_uno_gana(self):
        for _ in range(5):
            ganadores, validos = self._toma_simultanea(InMemoryStore())
            self.assertEqual(len(ganadores), 1, ganadores); self.assertEqual(len(validos), 1, validos)

    def test_control_negativo_un_almacen_no_atomico_SI_produce_varios_titulares(self):
        hallado = any(len(self._toma_simultanea(BrokenStore())[1]) > 1 for _ in range(5))
        self.assertTrue(hallado, "el almacén roto no produjo doble titularidad: la prueba de estrés no discrimina")


if __name__ == "__main__":
    unittest.main()
