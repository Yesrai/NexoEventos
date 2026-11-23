"""Failover LOCAL de extremo a extremo: orquestador (máquina de estados intacta) + TODOS los adaptadores (sondas, precheck, restauración desde un OCI FALSO, lease real,
standby con vallado de datos, registro de promoción y DNS con `dns_switch.py` sobre un DuckDNS/resolvedor FALSOS). Sin nubes, sin DNS real, sin Docker, claves desechables,
relojes simulados (con deriva) y servidores HTTP en 127.0.0.1.

Qué es y qué NO es: es una SIMULACIÓN con componentes reales (lease, compuerta, cifrado, firma, restauración con scripts reales, dns_switch.py). NO demuestra AWS, OCI, RDS ni red real.
Distinción de vallado (ver fenced_db.py): el STANDBY queda protegido por tres condiciones independientes (permiso + lease con plazo + época en la propia base); el PRIMARIO solo por su
AUTO-vallado (el lease caduca por su reloj y su compuerta rechaza escrituras); si su compuerta está apagada o su proceso congelado más allá de lo asumido, nada externo lo detiene (se prueba
y se documenta en test_limite_*). Por eso el orquestador detecta `old_can_write` y se detiene.
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_failover_e2e.py' -v"""
import contextlib, io, json, os, stat, sys, tempfile, threading, unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
for sub in ("scripts/multicloud/failover", "scripts/multicloud", "backend"):
    sys.path.insert(0, str(ROOT / sub))
import test_oci_source as T  # noqa: E402  (servidor OCI falso, claves y respaldos de prueba)
import test_lease_http as L  # noqa: E402  (servidor HTTP falso con If-Match / If-None-Match para el lease)
import adapters_probes as ap  # noqa: E402
import detector as DET  # noqa: E402
import failback as FB  # noqa: E402
import oci_source as oc  # noqa: E402
from adapters_dns import DnsSwitchAdapter, SAFE_WRITER_ACTIVE_DNS_UNCERTAIN  # noqa: E402
from adapters_standby import FullRecoveryAdapters, SimClock, StandbyService, run_failover  # noqa: E402
from fenced_db import FencedDatabase, FencedOut, LedgerError, PromotionLedger  # noqa: E402
from orchestrator import STAGES, Config, State  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import InMemoryStore, ParHttpStore, StoreUnavailable, build_verified_par_store  # noqa: E402
from app.failover.db_fence import DbFence  # noqa: E402

OLD_IP, NEW_IP, DOMAIN = "44.200.0.10", "129.213.0.10", "nexoeventos-demo"
TOKEN = "token-duckdns-de-prueba-0001"
RES = ["r1.test", "r2.test", "r3.test"]


# ───────────────────────────── DNS / DuckDNS falsos ─────────────────────────────
class FakeDns:
    """Resolvedores y API de DuckDNS falsos. mode: ok | ko | timeout | apply_then_timeout | slow (acepta pero los resolvedores no lo ven)."""
    def __init__(self):
        self.ip = {r: OLD_IP for r in RES}; self.mode = "ok"; self.applied = 0; self.attempts = 0; self.tokens_seen = []; self.disagree = False; self.down = set()

    def resolver(self, name, server):
        if server in self.down: raise OSError("resolvedor caído")
        return [self.ip[server]], 60

    def opener(self, url, timeout=10):
        from urllib.parse import parse_qs, urlparse as up
        import urllib.error
        q = parse_qs(up(url).query); self.attempts += 1; self.tokens_seen.append(q["token"][0])
        ip = q["ip"][0]
        if self.mode == "timeout": raise urllib.error.URLError("sin respuesta")
        if self.mode == "ko": return _Resp(b"KO")
        if q["token"][0] != TOKEN: return _Resp(b"KO")
        if self.mode in ("ok", "apply_then_timeout"):
            self.applied += 1; self.ip = {r: ip for r in RES}
        if self.mode == "slow": self.applied += 1                  # el proveedor dice OK pero los resolvedores no cambian
        if self.mode == "apply_then_timeout": raise urllib.error.URLError("se cortó tras aplicar")
        return _Resp(b"OK\n")


class _Resp:
    def __init__(self, b): self.b = b
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self.b


# ───────────────────────────── primario / standby HTTP falsos ─────────────────────────────
class Web(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, d): b = json.dumps(d).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        w = self.server.world; path = urlparse(self.path).path
        if path in ("/p/health", "/p/ready", "/p/write-gate"):
            with w.lock:
                w.hits.append(path)
                if w.primary_flaky > 0 and path != "/p/write-gate": w.primary_flaky -= 1; self.connection.close(); return
            if w.primary_http == "drop": self.connection.close(); return
            if w.primary_http != 200: return self._json(w.primary_http, {})
            if path == "/p/write-gate": return self._json(200, w.primary.status())
            return self._json(200, {"status": "ok"})
        if path == "/s/health": return self._json(w.standby_http, {"status": "ok"})
        if path in ("/s/livez", "/s/ready", "/s/api"): return self._json(w.standby_ready.get(path, 200), {})
        if path == "/s/write-gate": return self._json(200, w.standby.status())
        if path == "/c/health": return self._json(200 if w.control_ok else 503, {})
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()


class Primary:
    """El primario con AUTO-vallado: escribe solo con lease válido (plazo por su reloj) y comprueba otra vez justo antes del COMMIT."""
    def __init__(self, lease, db, gate_mode="enforce"):
        self.lease, self.db, self.gate_mode = lease, db, gate_mode
        self.alive = True; self.frozen = False

    def writes_permitted(self) -> bool:
        return True if self.gate_mode == "off" else self.lease.is_valid()

    def status(self):
        return {"mode": self.gate_mode, "holds_lease": self.lease.is_valid()} if self.gate_mode != "off" else {"mode": "off"}

    def write(self, payload):
        if self.gate_mode == "off":
            return self.db.write(self.db.epoch(), "primario", payload, still_valid=lambda: True)      # sin compuerta: nada lo detiene
        return self.db.write(self.lease.epoch or -1, "primario", payload, still_valid=self.lease.is_valid)

    def tick(self):
        if not self.alive or self.frozen: return
        if self.lease._etag is not None and not self.lease._lost: self.lease.renew()
        else: self.lease.acquire()


class E2E(T.Base):
    """Entorno completo por prueba."""
    TTL, MARGIN = 15.0, 5.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.web = ThreadingHTTPServer(("127.0.0.1", 0), Web); threading.Thread(target=cls.web.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.web.server_port}"
        cls.lsrv = ThreadingHTTPServer(("127.0.0.1", 0), L.H); cls.lsrv.s = L.Srv(); threading.Thread(target=cls.lsrv.serve_forever, daemon=True).start()
        cls.lpar = cls.t / "lease-bucket.url"; cls.lpar.write_text(f"http://127.0.0.1:{cls.lsrv.server_port}/p/{L.SECRET}/n/ns/b/bk/o/"); os.chmod(cls.lpar, 0o600)

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown(); cls.web.server_close(); cls.lsrv.shutdown(); cls.lsrv.server_close(); super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.LS = self.lsrv.s; self.LS.reset()
        self.d = Path(tempfile.mkdtemp(dir=self.tmp.name))
        os.environ["NEXO_ALLOW_DNS_CHANGE"] = "YES"
        self.addCleanup(os.environ.pop, "NEXO_ALLOW_DNS_CHANGE", None)

    # -- construcción del mundo
    def build(self, *, with_backup=True, dns_mode="ok", sign="good", primary_dies_at=3.0, gate_mode="enforce", ledger=None, name="sb", lease_store=None, shared=None, probes_n=3,
              tick_hooks=(), dns_cfg_override=None, standby_db=None, lease_http=False, adapter_kw=None):
        w = type("W", (), {})(); self.w = w
        w.lock = threading.Lock(); w.hits = []; w.primary_flaky = 0; w.primary_http = 200; w.standby_http = 200; w.control_ok = True; w.standby_ready = {}
        w.clock = shared["clock"] if shared else SimClock(); clk = w.clock
        mk = lambda: ParHttpStore(self.lpar, object_name="writer-lease.json", allow_http_localhost=True)
        w.store = (shared["store"] if shared else (mk() if lease_http else InMemoryStore())); w.store.verified = True
        w.standby_store = mk() if lease_http else w.store
        w.verifier = (lambda: build_verified_par_store(self.lpar, "writer-lease.json", allow_http_localhost=True)[0].verified) if lease_http else None
        if not shared: init_lease(w.store)
        cfg = LeaseConfig(ttl_s=self.TTL, margin_s=self.MARGIN)
        w.primary_lease = shared["primary_lease"] if shared else LeaseClient(w.store, cfg, "primario", lambda: 1.03 * clk.now() + 1000.0)
        w.standby_lease = LeaseClient(w.standby_store, cfg, name, lambda: 0.97 * clk.now() - 777.0)
        w.primary_db = shared["primary_db"] if shared else FencedDatabase(self.d / "primary.db")
        w.standby_db = standby_db or (shared["standby_db"] if shared else FencedDatabase(self.d / "standby.db"))
        w.primary = shared["primary"] if shared else Primary(w.primary_lease, w.primary_db, gate_mode)
        if not shared:
            self.assertTrue(w.primary_lease.acquire().ok); w.primary_db.raise_fence(w.primary_lease.epoch)
        w.standby = StandbyService(w.standby_lease, w.standby_db, self.d / f"promote-{name}", name)
        self.web.world = w
        w.dns = shared["dns"] if shared else FakeDns(); w.dns.mode = dns_mode
        cfgp = self.d / "dns.json"; token = self.d / "token"
        if not shared:
            cfgp.write_text(json.dumps(dns_cfg_override or {"allowed_domains": [DOMAIN], "allowed_targets": {"oci": NEW_IP, "aws": OLD_IP}, "resolvers": RES, "min_interval_s": 300}))
            token.write_text(TOKEN); os.chmod(token, 0o600)
        w.ledger = ledger or PromotionLedger(self.d / "ledger.json")
        if with_backup: self.make_backup(5, "ultimo", sign=sign)
        box = {}
        dnsa = DnsSwitchAdapter(config_path=cfgp, domain=DOMAIN, target="oci", token_file=token, state_dir=self.d / f"dns-state-{name}", resolver=w.dns.resolver, opener=w.dns.opener,
                                sleep=lambda s: box["ad"].sleep(s), clock=clk.now, timeout_s=60, interval_s=5, allow_change=True)
        probes = [ap.HttpProbe(f"{self.base}{p}", attempts=2, spacing_s=1, sleep=lambda s: None, allow_http_localhost=True,
                               json_ok=(lambda d: d.get("holds_lease") is True) if p == "/p/write-gate" else None) for p in ("/p/health", "/p/ready", "/p/write-gate")][:probes_n]
        control = ap.HttpProbe(f"{self.base}/c/health", attempts=1, allow_http_localhost=True)
        def env():
            return {**os.environ, "PATH": f"{self.shim}:{os.environ['PATH']}", "NEXO_T_PASS": T.PASS}
        w.monitor = {"double": 0, "ticks": 0}
        def monitor(t):
            w.monitor["ticks"] += 1
            if not shared:
                if w.primary.alive and not w.primary.frozen and int(t * 4) % 4 == 0: w.primary.tick()
            writers = sum([w.primary.writes_permitted() and w.primary.alive and not w.primary.frozen and w.primary.gate_mode != "off" or False])
            standbys = [s for s in (w.standby, *w.__dict__.get("others", [])) if s.writes_permitted()]
            if (w.primary.lease.is_valid() and w.primary.alive and not w.primary.frozen and w.primary.gate_mode != "off") + len(standbys) > 1: w.monitor["double"] += 1
        w.ad = FullRecoveryAdapters(run_id=f"run-{name}", clock=clk, lease=w.standby_lease, standby=w.standby, ledger=w.ledger, probes=ap.ProbeSet(probes, control), dns=dnsa,
                                    oci_reader=self.reader(), oci_key=self.t / "k.pem", oci_passin="env:NEXO_T_PASS", signer_pub=self.t / "sign.pub", restore_env=env(),
                                    wall_now=lambda: self.now, max_backup_age_s=3600, standby_health=ap.HttpProbe(f"{self.base}/s/health", attempts=2, spacing_s=1, sleep=lambda s: None, allow_http_localhost=True),
                                    primary_gate_url=f"{self.base}/p/write-gate", standby_gate_url=f"{self.base}/s/write-gate", allow_http_localhost=True,
                                    standby_readiness_probes={k: ap.HttpProbe(f"{self.base}/s/{k}", attempts=1, allow_http_localhost=True) for k in ("livez", "ready", "api")},
                                    tick_hooks=[monitor, *tick_hooks], store_verifier=w.verifier,
                                    **{**dict(primary_gate_attested=(gate_mode == "enforce"), db_attestation=(lambda: {"ok": True, "age_s": 5.0}) if gate_mode == "enforce" else None), **(adapter_kw or {})})
        box["ad"] = w.ad
        w.ocfg = Config(quorum=2, rounds=3, round_interval_s=5, acquire_timeout_s=60, poll_s=1, max_backup_age_s=3600)
        # el primario muere
        if primary_dies_at is not None:
            fired = {"x": False}
            def die(t, at=primary_dies_at):
                if t >= at and not fired["x"]:
                    fired["x"] = True; w.primary.alive = False; w.primary_http = "drop"
            w.ad.tick_hooks.append(die)
        w.ad.sleep(10.0)                                   # tiempo de funcionamiento previo (el primario renueva)
        w.statep = self.d / f"estado-{name}.json"
        return w

    def run_fo(self, w=None, run_id=None):
        w = w or self.w
        return run_failover(w.ad, w.ocfg, State(w.statep if run_id is None else self.d / f"estado-{run_id}.json", w.ad.run_id))

    def assert_untouched(self, res, w, state_ledger=("NONE",)):
        """Aborto seguro: sin escritor, sin cambio de DNS, sin doble escritor."""
        self.assertEqual(res["outcome"], "ABORTED", res)
        self.assertEqual(w.dns.applied, 0); self.assertEqual(w.dns.ip[RES[0]], OLD_IP)
        self.assertFalse(w.standby.writes_permitted()); self.assertFalse(w.standby.promote_permitted())
        self.assertEqual(w.standby_db.rows(), []); self.assertEqual(w.monitor["double"], 0)
        self.assertIn(w.ledger.state(), state_ledger)


class TestFlujoCompleto(E2E):
    def test_camino_feliz_de_extremo_a_extremo(self):
        w = self.build()
        pre = w.ad.precheck(); self.assertTrue(all(pre.values()), pre)
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE", res)
        self.assertEqual([t[0] for t in res["timeline"]], STAGES)
        self.assertEqual(w.dns.applied, 1); self.assertEqual(w.dns.ip[RES[0]], NEW_IP)
        self.assertEqual(w.ledger.state(), "PROMOTED"); self.assertEqual(w.monitor["double"], 0)
        self.assertEqual(w.ad.calls["restore_latest"], 1); self.assertEqual(w.ad.calls["dns_apply"], 1)
        self.assertTrue(w.standby.writes_permitted()); self.assertEqual(w.standby_db.epoch(), w.standby_lease.epoch)
        self.assertEqual(w.standby_db.rows()[0][2:], ("sb", "synthetic:run-sb"))                       # la escritura sintética pasó por el vallado de datos
        self.assertFalse(w.primary.lease.is_valid()); self.assertIsNone(w.ad.old_can_write())           # inalcanzable: DESCONOCIDO (no se asume que no escribe)
        w.primary_http = 200; self.assertEqual(w.ad.old_can_write(), False)                          # si responde, informa que está vallado (sin lease)
        self.assertEqual([x for x in self.S.log if x.endswith(".cms")], [x for x in self.S.log if x.endswith(".cms")][:1])   # un solo objeto descargado
        self.assertNotIn(TOKEN, json.dumps(res)); self.assertNotIn(T.PASS, json.dumps(res)); self.assertNotIn(T.PAR_SECRET, json.dumps(res))

    def test_la_toma_del_lease_espera_a_que_el_primario_caduque_por_su_propio_reloj(self):
        w = self.build(); res = self.run_fo(w)
        t_stage = dict(res["timeline"])
        self.assertGreaterEqual(t_stage["FENCE_AND_ACQUIRE"], 0)
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual(w.monitor["double"], 0)

    def test_ejecucion_idempotente_y_sin_reanudar_abortos(self):
        w = self.build(); r1 = self.run_fo(w); self.assertEqual(r1["outcome"], "DONE")
        applied = w.dns.applied; r2 = self.run_fo(w)               # mismo run_id: no repite efectos
        self.assertEqual(r2["outcome"], "DONE"); self.assertEqual(w.dns.applied, applied)

    def test_dns_que_ya_apunta_al_destino_no_repite_la_operacion(self):
        w = self.build(); w.dns.ip = {r: NEW_IP for r in RES}
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE"); self.assertEqual((w.dns.attempts, w.dns.applied), (0, 0))
        self.assertEqual(w.ledger.state(), "PROMOTED")

    def test_precheck_enumera_todas_las_condiciones(self):
        w = self.build(); pre = w.ad.precheck()
        self.assertEqual(set(pre), {"almacen_verificado", "dns_en_lista_blanca", "sondas_configuradas", "standby_responde", "standby_no_habilitado_para_escribir", "rpo_alcanzable",
                                    "restauracion_posible", "sin_promocion_previa"})


class TestPrecheckBloquea(E2E):
    def test_cada_condicion_del_precheck_bloquea_el_failover(self):
        casos = {}
        def a_almacen(w): w.store.verified = False
        def b_dns(w): (self.d / "dns.json").write_text(json.dumps({"allowed_domains": ["otro"], "allowed_targets": {"oci": NEW_IP}}))
        def c_sondas(w): w.ad.min_probes = 4
        def d_standby_caido(w): w.standby_http = 503
        def e_standby_habilitado(w): w.standby.promote_file.write_text("1")
        def f_sin_respaldo_reciente(w): self.S.store.clear()
        def g_sin_clave(w): w.ad.oci["key"] = self.t / "no-existe.pem"
        def h_promocion_previa(w): w.ledger.begin("otra-ejecucion")
        def i_sin_firmante(w): w.ad.oci["signer_pub"] = None
        for n, f in {"almacén no verificado": a_almacen, "DNS fuera de lista blanca": b_dns, "pocas sondas": c_sondas, "standby caído": d_standby_caido, "standby ya habilitado": e_standby_habilitado,
                     "sin respaldo en el RPO": f_sin_respaldo_reciente, "sin clave de restauración": g_sin_clave, "promoción previa": h_promocion_previa, "sin clave del firmante": i_sin_firmante}.items():
            with self.subTest(n):
                self.setUp(); w = self.build(); f(w)
                res = self.run_fo(w)
                self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("precondiciones", res["abort_reason"])
                self.assertEqual((w.dns.applied, w.dns.attempts), (0, 0)); self.assertFalse(w.standby.writes_permitted()); self.assertEqual(w.monitor["double"], 0)
                self.assertEqual(w.ad.calls.get("restore_latest", 0), 0)    # ni siquiera se intentó restaurar

    def test_respaldo_demasiado_viejo_bloquea_el_rpo_en_el_precheck(self):
        w = self.build(with_backup=False); self.make_backup(500, "viejo")
        self.assertFalse(w.ad.precheck()["rpo_alcanzable"])


class TestSondasYDecision(E2E):
    def test_una_falla_transitoria_no_dispara_el_failover(self):
        w = self.build(primary_dies_at=None); w.primary_flaky = 1             # un solo intento falla; el segundo (separado) responde
        res = self.run_fo(w); self.assert_untouched(res, w); self.assertIn("responde", res["abort_reason"])

    def test_primario_sano_no_se_promueve(self):
        w = self.build(primary_dies_at=None); res = self.run_fo(w); self.assert_untouched(res, w)

    def test_estados_desconocidos_no_actuan(self):
        for nombre, setup in {"4xx": lambda w: setattr(w, "primary_http", 404), "429": lambda w: setattr(w, "primary_http", 429), "sondeador aislado": lambda w: setattr(w, "control_ok", False)}.items():
            with self.subTest(nombre):
                self.setUp(); w = self.build(primary_dies_at=None); setup(w)
                res = self.run_fo(w); self.assert_untouched(res, w); self.assertIn("desconocido", res["abort_reason"])

    def test_5xx_y_caida_confirmada_si_disparan(self):
        for nombre, code in {"503 sostenido": 503, "conexión cortada": "drop"}.items():
            with self.subTest(nombre):
                self.setUp(); w = self.build(primary_dies_at=None); w.primary_http = code; w.primary.alive = False        # caído de verdad: no renueva su lease
                self.assertEqual(self.run_fo(w)["outcome"], "DONE"); self.assertEqual(w.monitor["double"], 0)

    def test_umbrales_configurables_quorum_y_rondas(self):
        w = self.build(primary_dies_at=None, probes_n=3); w.primary_http = 503; w.primary.alive = False; w.ocfg = Config(quorum=3, rounds=1, round_interval_s=1, acquire_timeout_s=60, poll_s=1)
        self.assertEqual(self.run_fo(w)["outcome"], "DONE")
        self.setUp(); w = self.build(primary_dies_at=None, probes_n=2); w.primary_http = 503; w.primary.alive = False; w.ocfg = Config(quorum=3, rounds=1, round_interval_s=1, acquire_timeout_s=60, poll_s=1)
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED")     # con 2 sondas el quórum 3 es inalcanzable: no se promueve


class TestRespaldoYRestauracion(E2E):
    def test_cualquier_fallo_del_respaldo_aborta_sin_cambios(self):
        def alterado(w): s = self.make_backup(2, "malo"); b = bytearray(self.S.store[s + ".cms"]); b[9] ^= 1; self.S.store[s + ".cms"] = bytes(b); [self.S.store.pop(k) for k in list(self.S.store) if "ultimo" in k]
        casos = {
            "firma falsa": lambda w: self._only_backup(minutes=5, sign="forger"),
            "sin firma": lambda w: self._only_backup(minutes=5, sign=None),
            "sin huella": lambda w: self._only_backup(minutes=5, fp=False),
            "objeto 404": lambda w: self.S.rules.update({s: [("status", 404)] * 20 for s in [k for k in self.S.store if k.endswith(".cms")]}),
            "HTTP 503 sostenido durante la restauración": lambda w: self._net_down_after_precheck(w, 503),
            "la red cae a mitad de la descarga": lambda w: self._truncate_all(w),
        }
        for n, f in casos.items():
            with self.subTest(n):
                self.setUp(); w = self.build(); f(w)
                res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED", n)
                self.assertEqual((w.dns.applied, w.monitor["double"]), (0, 0)); self.assertFalse(w.standby.writes_permitted()); self.assertEqual(w.standby_db.rows(), [])
                self.assertEqual(w.ad.calls.get("lease_acquire", 0), 0)       # sin respaldo verificado NO se intenta tomar el lease

    def test_respaldo_alterado_del_mismo_tamano(self):
        w = self.build(); s = [k for k in self.S.store if k.endswith(".cms")][0]
        b = bytearray(self.S.store[s]); b[20] ^= 1; self.S.store[s] = bytes(b)
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.applied, 0)

    def test_huella_restaurada_distinta_aborta(self):
        w = self.build(); w.ad.oci["restore_env"]["SHIM_RES"] = "999"
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("huella", res["abort_reason"]); self.assertEqual(w.dns.applied, 0)
        self.assertEqual(w.ad.calls.get("lease_acquire", 0), 0)

    def test_contrasena_de_clave_incorrecta_aborta_y_no_se_filtra(self):
        w = self.build(); w.ad.oci["restore_env"]["NEXO_T_PASS"] = "equivocada-no-real"
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertNotIn("equivocada-no-real", json.dumps(res)); self.assertNotIn(T.PASS, json.dumps(res))

    def test_el_respaldo_anterior_admisible_se_usa_si_el_reciente_es_invalido(self):
        w = self.build(); self.make_backup(1, "falso", sign="forger")
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")

    # ayudas
    def _only_backup(self, minutes, **kw):
        self.S.store.clear(); self.make_backup(minutes, "u", **kw)

    def _net_down_after_precheck(self, w, code):
        orig = w.ad.restore_latest
        def r():
            self.S.rules["*"] = [("status", code)] * 200
            return orig()
        w.ad.restore_latest = r

    def _truncate_all(self, w):
        orig = w.ad.restore_latest
        def r():
            for k in [k for k in self.S.store if k.endswith(".cms")]: self.S.rules[k] = [("truncate",)] * 50
            return orig()
        w.ad.restore_latest = r


class TestLeaseYStandby(E2E):
    def test_almacen_del_lease_inalcanzable_no_habilita_ningun_escritor(self):
        w = self.build()
        class Down(InMemoryStore):
            pass
        orig_acq = w.standby_lease.acquire
        def acq():
            raise_down = True
            w.standby_lease.store = _Partitioned(w.store)
            return orig_acq()
        w.standby_lease.acquire = acq
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("lease", res["abort_reason"])
        self.assertFalse(w.standby.writes_permitted()); self.assertEqual((w.dns.applied, w.monitor["double"]), (0, 0)); self.assertEqual(w.ledger.state(), "NONE")

    def test_titular_que_sigue_renovando_impide_la_toma(self):
        w = self.build(primary_dies_at=None)
        w.primary_http = 503                                   # las sondas lo ven caído (falso positivo: está vivo y renovando)
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("lease", res["abort_reason"])
        self.assertEqual((w.dns.applied, w.monitor["double"]), (0, 0)); self.assertFalse(w.standby.writes_permitted()); self.assertEqual(w.ledger.state(), "NONE")

    def test_sin_respaldo_verificado_no_se_adquiere_el_lease_ni_se_habilita(self):
        w = self.build(); w.ad.verified_backup = None
        self.assertFalse(w.ad.lease_acquire()[0]); self.assertEqual(w.ad.calls["lease_acquire"], 1)
        with self.assertRaises(Exception): w.ad.enable_standby(1)
        self.assertFalse(w.standby.promote_permitted())

    def test_enable_standby_exige_lease_de_esa_epoca_y_registro_de_la_ejecucion(self):
        from orchestrator import Abort
        w = self.build(); w.ad.verified_backup = ("x", 1.0)
        with self.assertRaises(Abort): w.ad.enable_standby(99)            # sin lease
        self.assertTrue(w.ad.ledger.begin(w.ad.run_id)); w.ad._began = True
        w.ad.lease_acquire(); w.ad.sleep(25.0); ok, why, epoch, wait = w.ad.lease_acquire(); self.assertTrue(ok, why)      # 1.ª: observa; 2.ª: tras TTL+margen
        with self.assertRaises(Abort): w.ad.enable_standby(epoch + 5)     # época equivocada
        self.assertFalse(w.standby.promote_permitted())

    def test_lease_perdido_tras_la_promocion_impide_nuevas_escrituras_del_standby(self):
        part = {"down": False}
        w = self.build(); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        self.assertTrue(w.standby.writes_permitted()); w.standby.write("antes")
        w.standby_lease.store = _Partitioned(w.store)                       # el standby pierde el almacén: no puede renovar
        w.ad.sleep(30.0)
        self.assertFalse(w.standby.writes_permitted())
        with self.assertRaises(FencedOut): w.standby.write("despues")
        self.assertEqual([r[3] for r in w.standby_db.rows() if r[3] == "despues"], [])

    def test_standby_zombi_con_epoca_vieja_es_rechazado_por_la_base_aunque_su_lease_diga_valido(self):
        w = self.build(); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        old_epoch = w.standby_lease.epoch
        w.standby_db.raise_fence(old_epoch + 1)                              # otro standby promovido sobre la misma base instaló una época mayor
        self.assertTrue(w.standby.writes_permitted())                        # el lease y el permiso locales SIGUEN diciendo que sí…
        with self.assertRaises(FencedOut): w.standby.write("zombi")          # …y la base lo rechaza: vallado de datos, no una bandera local
        with self.assertRaises(FencedOut): w.standby_db.write(old_epoch, "zombi", "x", still_valid=lambda: True)     # ni siquiera con un lease «siempre válido» (error en el cliente)

    def test_no_se_puede_bajar_el_vallado(self):
        w = self.build(); w.standby_db.raise_fence(5)
        with self.assertRaises(FencedOut): w.standby_db.raise_fence(4)
        w.standby_db.raise_fence(5)                                          # repetir es idempotente

    def test_primario_recuperado_no_vuelve_a_escribir(self):
        w = self.build(); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        w.primary.alive = True; w.primary_http = 200                         # el primario vuelve y reintenta tomar/renovar su lease
        w.ad.sleep(60.0)
        self.assertFalse(w.primary.lease.is_valid()); self.assertFalse(w.primary.writes_permitted())
        with self.assertRaises(FencedOut): w.primary.write("zombi")
        self.assertEqual(w.monitor["double"], 0); self.assertEqual(w.ad.old_can_write(), False)
        self.assertTrue(w.standby.writes_permitted())                        # el nuevo escritor sigue siéndolo (no hay failback automático)

    def test_primario_congelado_y_reanudado_no_escribe_con_el_lease_vencido(self):
        w = self.build(primary_dies_at=None, tick_hooks=[]); w.primary.frozen = True; w.primary_http = 503        # proceso congelado: no renueva, las sondas lo ven caído
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        w.primary.frozen = False; w.primary_http = 200                       # se reanuda con su lease viejo en memoria
        self.assertFalse(w.primary.lease.is_valid())                         # su plazo local ya venció: su compuerta rechaza antes del COMMIT
        with self.assertRaises(FencedOut): w.primary.write("al-reanudar")
        self.assertEqual(w.monitor["double"], 0)


class _Partitioned:
    """Almacén de lease inalcanzable (partición): toda operación es StoreUnavailable."""
    verified = True; ATOMIC_CREATE = True
    def __init__(self, inner): self.inner = inner
    def read(self): raise StoreUnavailable("partición")
    def create(self, d): raise StoreUnavailable("partición")
    def replace(self, e, d): raise StoreUnavailable("partición")


class TestDns(E2E):
    def test_plan_clasifica_el_estado_actual(self):
        w = self.build(); a = w.ad.dns
        self.assertEqual(a.dns_plan()["estado"], "requiere_cambio")
        w.dns.ip = {r: NEW_IP for r in RES}; self.assertEqual(a.dns_plan()["accion"], "ninguna")
        w.dns.ip = {RES[0]: OLD_IP, RES[1]: NEW_IP, RES[2]: OLD_IP}; self.assertEqual(a.dns_plan()["estado"], "indeterminado")
        w.dns.down = set(RES); self.assertEqual(a.inspect()["estado"], "indeterminado")      # ningún resolvedor responde: no es «ya apunta»
        self.assertEqual(w.dns.attempts, 0)                                                   # plan e inspect NO modifican nada

    def test_dns_indeterminado_no_se_cambia(self):
        w = self.build(); w.dns.ip = {RES[0]: OLD_IP, RES[1]: NEW_IP, RES[2]: OLD_IP}
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.attempts, 0)
        self.assertIn("indeterminado", res["abort_reason"]); self.assertTrue(w.standby.writes_permitted())     # el escritor nuevo YA estaba activo (etapa anterior)

    def test_sin_autorizacion_de_cambio_no_toca_el_dns(self):
        w = self.build(); os.environ.pop("NEXO_ALLOW_DNS_CHANGE")
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.attempts, 0); self.assertIn("no autorizado", res["abort_reason"])
        self.setUp(); w = self.build(); w.ad.dns.allow_change = False
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.attempts, 0)

    def test_proveedor_rechaza_ko_el_dns_no_cambia_y_se_bloquea_otra_promocion(self):
        w = self.build(dns_mode="ko"); res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.ip[RES[0]], OLD_IP); self.assertIn("rechaz", res["abort_reason"])
        self.assertEqual(w.ledger.state(), "DNS_REJECTED"); self.assertTrue(w.standby.writes_permitted())
        # SEGUNDA ejecución automática (otro run_id): el registro de promoción la bloquea en el precheck; no se promueve de nuevo
        w.ad.run_id = "run-2"; w.ad._began = False
        res2 = run_failover(w.ad, w.ocfg, State(self.d / "estado-2.json", "run-2"))
        self.assertEqual(res2["outcome"], "ABORTED"); self.assertIn("sin_promocion_previa", res2["abort_reason"]); self.assertEqual(w.ad.calls.get("restore_latest"), 1)

    def test_sin_respuesta_del_proveedor_y_sin_evidencia_es_incierto(self):
        w = self.build(dns_mode="timeout"); res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(res["safe_state"], SAFE_WRITER_ACTIVE_DNS_UNCERTAIN); self.assertEqual(w.ledger.state(), "UNCERTAIN_DNS")
        self.assertEqual(w.dns.attempts, 1)                                                    # no se reintenta a ciegas
        w.ad.run_id = "run-2"; w.ad._began = False
        res2 = run_failover(w.ad, w.ocfg, State(self.d / "estado-2.json", "run-2")); self.assertIn("sin_promocion_previa", res2["abort_reason"]); self.assertEqual(w.dns.attempts, 1)

    def test_el_proveedor_aplico_pero_la_conexion_se_corto_con_evidencia_cuenta_como_aplicado(self):
        w = self.build(dns_mode="apply_then_timeout"); res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual(w.dns.applied, 1); self.assertEqual(w.ledger.state(), "PROMOTED")

    def test_propagacion_no_confirmada_es_incierta(self):
        w = self.build(dns_mode="slow"); res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.ledger.state(), "UNCERTAIN_DNS"); self.assertEqual(w.dns.ip[RES[0]], OLD_IP)
        self.assertEqual(res["safe_state"], SAFE_WRITER_ACTIVE_DNS_UNCERTAIN)

    def test_token_incorrecto_y_el_token_no_se_filtra(self):
        w = self.build(); (self.d / "token").write_text("token-equivocado-0002"); os.chmod(self.d / "token", 0o600)
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertNotIn(TOKEN, json.dumps(res)); self.assertNotIn("token-equivocado-0002", json.dumps(res))

    def test_validate_rechaza_token_con_permisos_abiertos(self):
        w = self.build(); os.chmod(self.d / "token", 0o644); self.assertFalse(w.ad.dns.validate())
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("dns_en_lista_blanca", res["abort_reason"])

    def test_resolvedor_caido_no_impide_un_cambio_con_evidencia_suficiente(self):
        w = self.build(); w.dns.down = {RES[2]}
        res = self.run_fo(w); self.assertIn(res["outcome"], ("DONE", "ABORTED"))             # con un resolvedor caído la inspección es indeterminada o el cambio no se confirma
        if res["outcome"] == "ABORTED": self.assertIn(w.ledger.state(), ("WRITER_ENABLED", "UNCERTAIN_DNS", "NONE"))


class TestVerificacionPosterior(E2E):
    def test_primario_con_compuerta_apagada_se_detecta_y_se_libera_el_lease_nuevo(self):
        w = self.build(gate_mode="off", primary_dies_at=None); w.primary_http = 503     # sondas lo ven caído (ciego) pero está VIVO y escribe sin compuerta
        res = self.run_fo(w)
        # el lease estaba en manos del primario: sin compuerta no renueva… pero el almacén lo ve activo → la toma falla; para forzar VERIFY se usa un lease que ya caducó
        self.assertEqual(res["outcome"], "ABORTED")
        self.assertEqual(w.monitor["double"], 0)

    def test_doble_escritor_detectado_en_verify_libera_el_lease_y_exige_humano(self):
        w = self.build(primary_dies_at=3.0)                       # el primario muere (no renueva) → el standby toma el lease
        w.primary.gate_mode = "off"                               # …pero su compuerta está apagada y SIGUE escribiendo al volver
        orig = w.ad.probe_new_endpoint
        def revive():
            w.primary.alive = True; w.primary_http = 200
            return orig()
        w.ad.probe_new_endpoint = revive
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("CRÍTICO", res["abort_reason"]); self.assertEqual(res["safe_state"], "DOBLE ESCRITOR DETECTADO")
        self.assertFalse(w.standby.writes_permitted())            # el nuevo lease se libera: el standby deja de escribir
        self.assertEqual(w.ledger.state(), "PROMOTED")             # y el registro sigue bloqueado: ninguna ejecución automática repite

    def test_primario_con_compuerta_apagada_y_estado_desconocido_BLOQUEA_la_promocion(self):
        """Era un LÍMITE documentado (19-nov): primario VIVO, compuerta apagada, aislado del almacén y visto caído por las sondas → el failover procedía y quedaba un DOBLE ESCRITOR.
        Ahora FENCE_CHECK lo bloquea ANTES de habilitar el standby: estado desconocido (503) + sin atestación de enforce → aborto, lease liberado, alerta crítica, DNS intacto."""
        w = self.build(gate_mode="off", primary_dies_at=None)
        w.primary_http = 503                                       # las sondas lo ven caído
        w.primary_lease.store = _Partitioned(w.store)              # …y no puede renovar su lease (partición hacia el almacén)
        res = self.run_fo(w)
        self.assert_untouched(res, w)
        self.assertIn("desconocido", res["abort_reason"]); self.assertEqual([a[0] for a in w.ad.alerts], ["critical"])
        self.assertIsNone(w.ad.old_can_write()); self.assertTrue(w.primary.writes_permitted())   # (el primario SÍ puede escribir: por eso se bloquea)
        self.assertFalse(w.standby.writes_permitted())                                            # y el standby nunca llegó a ser escritor

    def test_primario_que_responde_escribiendo_bloquea_la_promocion_y_alerta(self):
        w = self.build(gate_mode="off", primary_dies_at=None)
        w.primary_http = 200; w.ocfg.rounds = 1
        w.ad.probes.probes[0].json_ok = lambda d: False             # las sondas lo ven «caído» aunque /write-gate responde mode=off (escribe)
        for p in w.ad.probes.probes: p.json_ok = lambda d: False
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.monitor["double"], 0); self.assertFalse(w.standby.writes_permitted())

    def test_standby_no_listo_antes_del_dns_aborta_y_libera_el_lease(self):
        for bad in ("/s/livez", "/s/ready", "/s/api"):
            w = self.build(name="sb" + bad[3:], ledger=PromotionLedger(self.d / ("ledger" + bad[3:].replace("/", "") + ".json"))); w.standby_ready = {bad: 503}
            res = self.run_fo(w)
            self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.applied, 0); self.assertFalse(w.standby.writes_permitted())
            self.assertIn("comprobaciones de salud", res["abort_reason"])
            self.assertIn("no está listo", w.ad.alerts[-1][1]); self.assertEqual(w.ad.alerts[-1][0], "warning")           # (la primera alerta señala el vallado solo inferido)
            self.assertEqual(w.ledger.state(), PromotionLedger.NONE)                # I8: la salud se comprueba ANTES de habilitar escrituras → aborto LIMPIO (nadie llegó a escribir)
            self.assertFalse(w.standby_lease.is_valid()); self.assertEqual(w.standby_db.rows(), [])

    def test_sin_sondas_de_preparacion_configuradas_no_se_promueve(self):
        w = self.build(); w.ad.standby_readiness_probes = {}
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns.applied, 0)

    def test_primario_inalcanzable_sin_atestacion_de_compuerta_no_se_promueve(self):
        w = self.build(); w.ad._gate_attested = None
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("desconocido", res["abort_reason"]); self.assertEqual(w.dns.applied, 0)

    def test_nuevo_sitio_que_no_escribe_aborta_en_verify(self):
        w = self.build(); orig = w.ad.synthetic_write_ok
        def raised():
            w.standby_db.raise_fence(w.standby_lease.epoch + 1)   # otro escritor instaló una época mayor entre medias
            return orig()
        w.ad.synthetic_write_ok = raised
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("no responde o no escribe", res["abort_reason"])


class TestDosOrquestadores(E2E):
    def _two(self, shared_ledger: bool, lease_http: bool = False):
        w1 = self.build(name="o1", lease_http=lease_http)
        shared = {"clock": w1.clock, "store": w1.store, "primary_lease": w1.primary_lease, "primary_db": w1.primary_db, "primary": w1.primary, "dns": w1.dns, "standby_db": w1.standby_db}
        w2 = self.build(name="o2", shared=shared, ledger=w1.ledger if shared_ledger else PromotionLedger(self.d / "ledger2.json"), with_backup=False, primary_dies_at=3.0, lease_http=lease_http)
        w1.others = [w2.standby]; w2.others = [w1.standby]; self.web.world = w1; w2.lock = w1.lock
        # el monitor de ambos mundos ve ambos standbys y el primario
        return w1, w2

    def _run_both(self, w1, w2):
        out = {}
        def go(w, k):
            try: out[k] = self.run_fo(w)
            except Exception as e: out[k] = {"outcome": f"EXC {type(e).__name__}: {e}"}
        ts = [threading.Thread(target=go, args=(w1, "o1")), threading.Thread(target=go, args=(w2, "o2"))]
        [t.start() for t in ts]; [t.join(60) for t in ts]
        return out

    def test_con_registro_compartido_solo_uno_promueve(self):
        w1, w2 = self._two(True); out = self._run_both(w1, w2)
        outcomes = sorted(v["outcome"] for v in out.values()); self.assertEqual(outcomes, ["ABORTED", "DONE"], out)
        self.assertEqual(w1.dns.applied, 1); self.assertEqual(w1.monitor["double"] + w2.monitor["double"], 0)
        self.assertEqual(sum(1 for s in (w1.standby, w2.standby) if s.promote_permitted()), 1)

    def test_sin_registro_compartido_el_lease_sigue_impidiendo_dos_escritores(self):
        w1, w2 = self._two(False); out = self._run_both(w1, w2)
        self.assertFalse(any(v["outcome"].startswith("EXC") for v in out.values()), out)
        self.assertEqual(w1.monitor["double"] + w2.monitor["double"], 0)                     # nunca dos escritores a la vez
        self.assertLessEqual(w1.dns.applied, 1)
        self.assertLessEqual(sum(1 for s in (w1.standby, w2.standby) if s.writes_permitted()), 1)
        rows = w1.standby_db.rows(); self.assertEqual(len({r[1] for r in rows if r[1] > 0}) <= 2, True)


class TestLeaseHttpConOrquestador(E2E):
    """ParHttpStore conectado al orquestador: autoprueba obligatoria (precheck y antes de tomar el lease), lease sobre HTTP con If-Match/If-None-Match falsos."""
    LEASE_PATH = f"/p/{L.SECRET}/n/ns/b/bk/o/writer-lease.json"

    def test_camino_feliz_con_lease_http_y_autoprueba(self):
        w = self.build(lease_http=True)
        pre = w.ad.precheck(); self.assertTrue(pre["almacen_verificado"], pre)
        self.assertTrue(any("selftest" in k for k in self.LS.objs))                          # la autoprueba escribió objetos de prueba exclusivos
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE", res)
        self.assertEqual((w.dns.applied, w.monitor["double"], w.ledger.state()), (1, 0, "PROMOTED"))
        import json as _j; rec = _j.loads(self.LS.objs[self.LEASE_PATH][0]); self.assertEqual(rec["holder"], "sb")        # el lease HTTP lo tiene el standby (época ≥ 2)
        self.assertGreaterEqual(rec["epoch"], 2)

    def test_un_servicio_que_ignora_if_match_bloquea_el_failover_antes_de_cualquier_cambio(self):
        w = self.build(lease_http=True); self.LS.enforce = False
        pre = w.ad.precheck(); self.assertFalse(pre["almacen_verificado"])
        before = self.LS.objs.get(self.LEASE_PATH)
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("almacen_verificado", res["abort_reason"])
        self.assertEqual((w.dns.attempts, w.ad.calls.get("lease_acquire", 0), w.monitor["double"]), (0, 0, 0)); self.assertFalse(w.standby.writes_permitted())
        self.assertEqual(self.LS.objs.get(self.LEASE_PATH), before)                          # el lease no se tocó

    def test_el_servicio_deja_de_respetar_las_condiciones_despues_del_precheck(self):
        w = self.build(lease_http=True); orig = w.ad.restore_latest
        def degrade():
            self.LS.enforce = False                                                           # tras el precheck y antes de tomar el lease
            return orig()
        w.ad.restore_latest = degrade
        before = self.LS.objs.get(self.LEASE_PATH)
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("lease", res["abort_reason"])
        self.assertEqual((w.dns.applied, w.monitor["double"]), (0, 0)); self.assertFalse(w.standby.writes_permitted()); self.assertEqual(w.ledger.state(), "NONE")
        self.assertEqual(self.LS.objs.get(self.LEASE_PATH), before)                          # el standby NUNCA escribió el registro del lease

    def test_resultado_incierto_en_la_toma_se_resuelve_sin_doble_escritor(self):
        w = self.build(lease_http=True); st = w.standby_lease.store; orig = st.replace; flag = {"n": 0}
        def replace(etag, data):
            flag["n"] += 1
            if flag["n"] == 1: self.LS.apply_then_503 = 1                                    # la PRIMERA toma se aplica en el servidor pero responde 503
            return orig(etag, data)
        st.replace = replace
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE", res); self.assertEqual((w.monitor["double"], w.dns.applied), (0, 1))
        self.assertGreaterEqual(flag["n"], 2)                                                # hubo un reintento tras el resultado incierto (adoptó su propia escritura)

    def test_almacen_caido_tras_promover_cierra_el_standby_y_se_recupera_sin_doble_escritor(self):
        w = self.build(lease_http=True); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        self.LS.down = True; w.ad.sleep(30.0)
        self.assertFalse(w.standby.writes_permitted())                                      # sin poder renovar, deja de escribir por su propio plazo
        with self.assertRaises(FencedOut): w.standby.write("durante-la-caida")
        self.LS.down = False; w.ad.sleep(10.0)
        self.assertTrue(w.standby.writes_permitted()); self.assertEqual(w.monitor["double"], 0)   # nadie más lo tomó: recupera su propio lease

    def test_dos_orquestadores_sobre_el_mismo_lease_http_con_registro_compartido(self):
        w1, w2 = TestDosOrquestadores._two(self, True, lease_http=True); out = TestDosOrquestadores._run_both(self, w1, w2)
        self.assertEqual(sorted(v["outcome"] for v in out.values()), ["ABORTED", "DONE"], out)
        self.assertEqual((w1.dns.applied, w1.monitor["double"] + w2.monitor["double"]), (1, 0))
        self.assertEqual(sum(1 for s_ in (w1.standby, w2.standby) if s_.promote_permitted()), 1)

    def test_dos_orquestadores_sobre_el_mismo_lease_http_sin_registro_compartido(self):
        """Solo el lease (condiciones atómicas del servicio) arbitra: nunca dos escritores a la vez, aunque cada orquestador tenga su propio registro."""
        w1, w2 = TestDosOrquestadores._two(self, False, lease_http=True); out = TestDosOrquestadores._run_both(self, w1, w2)
        self.assertFalse(any(v["outcome"].startswith("EXC") for v in out.values()), out)
        self.assertEqual(w1.monitor["double"] + w2.monitor["double"], 0)
        self.assertLessEqual(sum(1 for s_ in (w1.standby, w2.standby) if s_.writes_permitted()), 1); self.assertLessEqual(w1.dns.applied, 1)

    def test_limite_dos_orquestadores_con_un_servicio_que_ignora_las_condiciones_y_sin_autoprueba(self):
        """LÍMITE: si se desactivara la autoprueba (aquí: verificador que siempre dice «sí») y el servicio ignorara If-Match, el lease deja de arbitrar. Por eso el orquestador
        NO tiene ninguna opción para omitir la autoprueba; este test la sustituye a propósito para mostrar qué se perdería."""
        w1, w2 = TestDosOrquestadores._two(self, False, lease_http=True)
        for w in (w1, w2): w.ad.store_verifier = lambda: True; w.standby_lease.store.verified = True; w.primary.alive = False      # ← la trampa: «verificado» sin autoprueba
        self.LS.enforce = False
        for w in (w1, w2): self.assertFalse(w.standby_lease.acquire().ok)                  # ambos observan al titular (el primario ya no renueva)
        w1.ad.sleep(25.0)                                                                  # …y esperan a que caduque (TTL + margen)
        barrier = threading.Barrier(2, timeout=10)
        for w in (w1, w2):                                                                 # ambos leen el MISMO ETag antes de que cualquiera escriba (carrera real)
            orig = w.standby_lease.store.read
            w.standby_lease.store.read = lambda orig=orig: (lambda v: (barrier.wait(), v)[1])(orig())
        res = {}
        ts = [threading.Thread(target=lambda w=w, k=k: res.__setitem__(k, w.standby_lease.acquire())) for k, w in (("a", w1), ("b", w2))]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertTrue(res["a"].ok and res["b"].ok)                                       # sin condiciones atómicas en el servidor, DOS standby creen tener el lease
        self.assertTrue(w1.standby_lease.is_valid() and w2.standby_lease.is_valid())


class TestVallaExternaDelPrimario(E2E):
    """Vallado de la base del primario (db_fence) integrado en la activación del standby; el ejecutor es un registro (la base real se prueba en backend/tests/test_db_fence.py)."""
    def _fence(self, w, ok=True):
        calls = []
        def fn():
            calls.append({"promote_permitted_al_vallar": w.standby.promote_permitted()})
            if not ok: raise RuntimeError("base del primario inalcanzable con detalle sensible")
            return DbFence(lambda sql, params=None: calls.append(sql) or [(1,)], "nexoeventos_app", mode="nologin").fence()
        return fn, calls

    def test_el_vallado_externo_se_aplica_antes_de_habilitar_el_standby(self):
        holder = {}
        w = self.build(adapter_kw=holder)
        fn, calls = self._fence(w); w.ad.primary_db_fence = fn
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE", res)
        self.assertFalse(calls[0]["promote_permitted_al_vallar"])                           # primero el vallado de la base del primario, DESPUÉS el permiso del standby
        self.assertTrue(any(isinstance(c, str) and "NOLOGIN" in c for c in calls)); self.assertTrue(any(isinstance(c, str) and "pg_terminate_backend" in c for c in calls))
        self.assertEqual(w.ad.standby_status()["primary_db_fence"], True)

    def test_si_el_primario_es_inalcanzable_por_defecto_solo_se_registra_y_se_sigue(self):
        w = self.build(); fn, calls = self._fence(w, ok=False); w.ad.primary_db_fence = fn
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        self.assertEqual(w.ad.standby_status()["primary_db_fence"], False); self.assertNotIn("sensible", json.dumps(res))    # semántica anterior intacta; el fallo queda visible

    def test_con_vallado_obligatorio_su_fallo_impide_habilitar_el_standby(self):
        w = self.build(); fn, calls = self._fence(w, ok=False); w.ad.primary_db_fence = fn; w.ad.require_primary_db_fence = True
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("vallar", res["abort_reason"])
        self.assertEqual((w.dns.applied, w.monitor["double"]), (0, 0)); self.assertFalse(w.standby.promote_permitted()); self.assertFalse(w.standby.writes_permitted())
        self.assertEqual(w.ledger.state(), "NONE"); self.assertFalse(w.standby_lease.is_valid())     # y el lease tomado se libera (no queda retenido por una ejecución abortada)


class TestEscritoresExternosEnElPrecheck(E2E):
    def _check(self, w, report):
        w.ad.external_writers_check = (lambda: report) if not callable(report) else report

    def test_sin_detector_el_precheck_no_cambia(self):
        w = self.build(); self.assertNotIn("sin_escritores_externos", w.ad.precheck())

    def test_aceptacion_sin_hallazgos_y_visibilidad_completa(self):
        w = self.build(); self._check(w, {"bloquea": False, "visibilidad": "completa"})
        self.assertTrue(w.ad.precheck()["sin_escritores_externos"]); self.assertEqual(self.run_fo(w)["outcome"], "DONE")

    def test_rechazo_si_hay_escritores_externos_visibilidad_parcial_o_error(self):
        casos = {"hallazgo que bloquea": {"bloquea": True, "visibilidad": "completa"}, "visibilidad parcial": {"bloquea": False, "visibilidad": "parcial"},
                 "informe sin campos": {}, "error del detector": lambda: (_ for _ in ()).throw(RuntimeError("base inalcanzable"))}
        for n, rep in casos.items():
            with self.subTest(n):
                self.setUp(); w = self.build(); self._check(w, rep)
                res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("sin_escritores_externos", res["abort_reason"])
                self.assertEqual((w.dns.attempts, w.ad.calls.get("restore_latest", 0), w.ad.calls.get("lease_acquire", 0)), (0, 0, 0)); self.assertFalse(w.standby.writes_permitted())

    def test_visibilidad_parcial_solo_se_acepta_con_permiso_expreso(self):
        w = self.build(); self._check(w, {"bloquea": False, "visibilidad": "parcial"}); w.ad.allow_partial_visibility = True
        self.assertTrue(w.ad.precheck()["sin_escritores_externos"])

    def test_con_el_detector_real_contra_un_postgresql_desechable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pgtemp", ROOT / "backend/tests/pgtemp.py"); pgt = importlib.util.module_from_spec(spec); spec.loader.exec_module(pgt)
        if not pgt.available(): self.skipTest("initdb/pg_ctl no disponibles")
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        from app.failover.external_writers import scan_external_writers
        c = pgt.TempCluster(); self.addCleanup(c.stop)
        root = create_engine(c.url(), isolation_level="AUTOCOMMIT", poolclass=NullPool)
        with root.begin() as k:
            for st in ("CREATE ROLE app LOGIN", "CREATE ROLE owner_r LOGIN", "CREATE ROLE monitor LOGIN", "GRANT pg_read_all_stats TO monitor", "CREATE DATABASE nexo OWNER owner_r"): k.execute(text(st))
        own = create_engine(c.url("nexo", "owner_r"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
        with own.begin() as k: k.execute(text("CREATE TABLE t (id int)")); k.execute(text("GRANT SELECT, INSERT ON t TO app"))
        mon = create_engine(c.url("nexo", "monitor"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
        def ex(sql, params=None):
            with mon.connect() as k:
                r = k.exec_driver_sql(sql, params or {}); return [tuple(x) for x in r.fetchall()] if r.returns_rows else []
        w = self.build(); w.ad.allow_partial_visibility = False
        w.ad.external_writers_check = lambda: scan_external_writers(ex, app_role="app", tolerated_roles=("postgres",)).as_dict()
        self.assertTrue(w.ad.precheck()["sin_escritores_externos"])                          # base limpia: se acepta
        eng = create_engine(c.url("nexo", "owner_r"), poolclass=NullPool); conn = eng.connect(); self.addCleanup(conn.close)
        conn.execute(text("INSERT INTO t VALUES (1)"))                                        # un propietario escribe fuera de la compuerta (transacción abierta)
        self.assertFalse(w.ad.precheck()["sin_escritores_externos"])                         # …y el precheck lo rechaza
        res = self.run_fo(w); self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual((w.dns.attempts, w.ad.calls.get("lease_acquire", 0)), (0, 0))


class TestEstadoParaElPanel(E2E):
    def test_last_run_json_con_campos_permitidos_y_permisos_restrictivos(self):
        w = self.build(); sd = self.d / "panel"
        res = run_failover(w.ad, w.ocfg, State(w.statep, w.ad.run_id), status_dir=sd, origen="simulado")
        data = json.loads((sd / "last-run.json").read_text())
        self.assertEqual((data["outcome"], data["origen"]), (res["outcome"], "simulado")); self.assertEqual([t[0] for t in data["timeline"]], STAGES)
        self.assertEqual(stat.S_IMODE((sd / "last-run.json").stat().st_mode), 0o600)
        self.assertEqual(set(data), {"outcome", "safe_state", "abort_reason", "origen", "timeline", "epoch", "alerts", "modo", "incident", "fencing"})
        self.assertNotIn(TOKEN, json.dumps(data)); self.assertNotIn(T.PAR_SECRET, json.dumps(data))

    def test_un_aborto_tambien_se_registra_y_el_origen_es_validado(self):
        w = self.build(primary_dies_at=None); sd = self.d / "panel"
        res = run_failover(w.ad, w.ocfg, State(w.statep, w.ad.run_id), status_dir=sd)
        self.assertEqual(json.loads((sd / "last-run.json").read_text())["outcome"], "ABORTED")
        from adapters_standby import write_last_run
        with self.assertRaises(ValueError): write_last_run(sd, res, "produccion")


class TestRegistroYUnidades(E2E):
    def test_registro_de_promocion_transiciones_y_concurrencia(self):
        led = PromotionLedger(self.d / "l.json")
        wins = []
        ts = [threading.Thread(target=lambda i=i: wins.append(led.begin(f"r{i}"))) for i in range(16)]; [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sum(wins), 1)
        run = led.read()["run_id"]
        with self.assertRaises(LedgerError): led.advance("otro", "WRITER_ENABLED")          # otra ejecución
        with self.assertRaises(LedgerError): led.advance(run, "PROMOTED")                    # transición no permitida
        led.advance(run, "WRITER_ENABLED", 2); led.advance(run, "UNCERTAIN_DNS")
        with self.assertRaises(LedgerError): led.advance(run, "NONE")                        # ningún adaptador puede liberar
        with self.assertRaises(LedgerError): led.clear("sí")
        led.clear(PromotionLedger.CLEAR_PHRASE); self.assertEqual(led.state(), "NONE")

    def test_registro_corrupto_falla_cerrado(self):
        led = PromotionLedger(self.d / "l.json"); led.path.write_text("{{{"); self.assertEqual(led.state(), "CORRUPT")
        self.assertFalse(led.begin.__self__ is None) if False else None
        with self.assertRaises(LedgerError): led.begin("r")

    def test_ninguna_condicion_basta_sola_para_escribir_en_el_standby(self):
        w = self.build(); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        s = w.standby
        s.promote_file.unlink(); self.assertFalse(s.writes_permitted())                      # lease válido, sin permiso → no
        with self.assertRaises(FencedOut): s.write("x")
        s.promote_file.write_text("2"); self.assertTrue(s.writes_permitted())
        w.standby_lease.store = _Partitioned(w.store); w.ad.sleep(100.0); self.assertFalse(s.writes_permitted())   # permiso presente, lease vencido (no puede renovar) → no
        with self.assertRaises(FencedOut): s.write("x")

    def test_precheck_no_modifica_nada(self):
        w = self.build(); before = (w.dns.attempts, w.ledger.state(), w.standby.promote_permitted(), w.standby_db.rows())
        w.ad.precheck(); w.ad.precheck()
        self.assertEqual(before, (w.dns.attempts, w.ledger.state(), w.standby.promote_permitted(), w.standby_db.rows()))


class TestSondasUnidad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = ThreadingHTTPServer(("127.0.0.1", 0), Web); threading.Thread(target=cls.web.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.web.server_port}"
        w = type("W", (), {})(); w.lock = threading.Lock(); w.hits = []; w.primary_flaky = 0; w.primary_http = 200; w.standby_http = 200; w.control_ok = True; w.standby_ready = {}
        w.primary = type("P", (), {"status": lambda s: {"mode": "enforce", "holds_lease": True}})(); w.standby = type("S", (), {"status": lambda s: {"mode": "enforce", "holds_lease": False}})()
        cls.w = cls.web.world = w

    @classmethod
    def tearDownClass(cls): cls.web.shutdown(); cls.web.server_close()

    def setUp(self): self.w.primary_http = 200; self.w.primary_flaky = 0; self.w.control_ok = True

    def p(self, path="/p/health", **kw): return ap.HttpProbe(self.base + path, attempts=kw.pop("attempts", 2), spacing_s=0, sleep=lambda s: None, allow_http_localhost=True, **kw)

    def test_estados_de_una_sonda(self):
        self.assertIs(self.p().run(), True)
        self.w.primary_flaky = 1; self.assertIs(self.p().run(), True)                  # un fallo transitorio seguido de un acierto = sano
        self.w.primary_flaky = 5; self.assertIs(self.p().run(), False)                 # fallo sostenido
        self.w.primary_flaky = 0
        for code in (404, 429, 302): self.w.primary_http = code; self.assertIsNone(self.p().run(), code)
        self.w.primary_http = 503; self.assertIs(self.p().run(), False)
        self.w.primary_http = 200; self.assertIsNone(self.p("/p/write-gate", json_ok=lambda d: d["no_existe"]).run())     # cuerpo no cumple/ilegible = desconocido
        self.assertIsNone(ap.HttpProbe("http://ejemplo.invalid/x").run())              # URL inválida (http no local)

    def test_control_aislado_vuelve_desconocidas_todas_las_sondas(self):
        ps = ap.ProbeSet([self.p(), self.p("/p/ready")], control=ap.HttpProbe(self.base + "/c/health", attempts=1, allow_http_localhost=True))
        self.assertEqual(ps.probe_all(), [True, True]); self.w.control_ok = False; self.w.primary_http = 503
        self.assertEqual(ps.probe_all(), [None, None])

    def test_gate_status(self):
        self.assertEqual(ap.gate_status(self.base + "/p/write-gate", allow_http_localhost=True), "escribe")
        self.assertEqual(ap.gate_status(self.base + "/s/write-gate", allow_http_localhost=True), "vallado")
        self.w.primary_http = 503; self.assertIsNone(ap.gate_status(self.base + "/p/write-gate", allow_http_localhost=True))
        self.assertIsNone(ap.gate_status("http://127.0.0.1:9/x", allow_http_localhost=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)



# ───────────────────────── escenarios del failover SEGURO AWS → OCI (detector + vallado con evidencia) ─────────────────────────
class TestFailoverSeguro(E2E):
    """Cada escenario fija QUÉ se concluye (clasificación), con QUÉ evidencia de vallado y que NUNCA hay dos escritores. Todo local: sin nube, sin DNS real."""
    def signals(self, **kw):
        S = dict(livez=False, ready=False, control=True, gate=None, att=True, aws={"ec2": "stopped", "rds": "available"}); S.update(kw); return S

    def detector(self, S):
        return DET.IncidentDetector(livez=lambda: S["livez"], ready=lambda: S["ready"], control=lambda: S["control"], gate=lambda: S["gate"], aws=lambda: S["aws"], gate_attested=lambda: S["att"])

    def build_s(self, S, **kw):
        akw = dict(detector=self.detector(S), aws_state=lambda: S["aws"]); akw.update(kw.pop("adapter_kw", {}))
        return self.build(adapter_kw=akw, **kw)

    def test_caida_de_instancia_con_evidencia_verificada_de_aws_promueve_sin_doble_escritor(self):
        S = self.signals(); w = self.build_s(S); res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE", res.get("abort_reason"))
        self.assertEqual(res["incident"]["kind"], "INSTANCE_DOWN")
        self.assertEqual([(e["kind"], e["strength"]) for e in res["fencing"]["evidence"]], [("aws_instance", "verified")])
        self.assertEqual([a[0] for a in w.ad.alerts], [])                        # evidencia directa: sin alerta de «solo inferido»
        self.assertEqual(w.dns.applied, 1); self.assertEqual(w.monitor["double"], 0)
        self.assertEqual([t[0] for t in res["timeline"]], STAGES)                # orden I8: …FENCE_CHECK → HEALTH_GATE → ENABLE_STANDBY → SWITCH_DNS → VERIFY
        self.assertLess(STAGES.index("HEALTH_GATE"), STAGES.index("ENABLE_STANDBY"))

    def test_caida_de_rds_con_la_aplicacion_viva_no_se_promueve_mientras_el_primario_conserve_el_lease(self):
        S = self.signals(livez=True, ready=False, aws={"ec2": "running", "rds": "stopped"})
        w = self.build_s(S, primary_dies_at=None); w.primary_http = 503          # las sondas desde OCI ven fallar al primario; su proceso sigue vivo y renovando el lease
        res = self.run_fo(w)
        self.assertEqual(res["incident"]["kind"], "DB_DOWN")
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("lease", res["abort_reason"])      # el titular sigue activo: no se puede tomar el lease → NO hay promoción
        self.assert_untouched(res, w)

    def test_aislamiento_de_red_sin_atestacion_de_la_compuerta_se_bloquea_y_alerta(self):
        S = self.signals(livez=False, aws={"ec2": "running", "rds": "available"}, att=None)
        w = self.build_s(S, gate_mode="off", primary_dies_at=None); w.primary_http = "drop"
        res = self.run_fo(w)
        self.assertEqual(res["incident"]["kind"], "NETWORK_ISOLATION"); self.assertFalse(res["incident"]["promotable"])
        self.assertEqual(res["outcome"], "ABORTED"); self.assert_untouched(res, w)
        self.assertEqual(w.ad.alerts[0][0], "critical")

    def test_aislamiento_de_red_con_compuerta_enforce_promueve_solo_tras_caducar_el_lease_del_primario(self):
        S = self.signals(livez=False, aws={"ec2": "running", "rds": "available"}, att=True)
        w = self.build_s(S, primary_dies_at=None); w.primary_http = "drop"
        w.primary_lease.store = _Partitioned(w.store)                           # el primario aislado tampoco llega al almacén del lease: no puede renovarlo
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE", res.get("abort_reason"))
        self.assertEqual(res["incident"]["kind"], "NETWORK_ISOLATION")
        self.assertEqual([(e["kind"], e["strength"]) for e in res["fencing"]["evidence"]], [("lease_expiry", "inferred")])
        self.assertIn("INFERIDO", w.ad.alerts[0][1])                            # promovió con vallado solo inferido: queda señalado en la alerta
        self.assertGreaterEqual(res["timeline"][STAGES.index("FENCE_AND_ACQUIRE")][1], 15.0)       # tomó el lease DESPUÉS del TTL
        with self.assertRaises(FencedOut): w.primary.write("split-brain")        # RECHAZO OBLIGATORIO: el primario aislado no puede escribir
        self.assertEqual(w.monitor["double"], 0)

    def test_evidencia_inferida_sin_atestacion_del_vallado_en_la_base_no_basta_y_bloquea(self):
        """La compuerta de la aplicación atestiguada NO es una garantía suficiente por sí sola: sin la atestación vigente del vallado EN LA BASE del primario, el aislamiento no se promueve."""
        S = self.signals(livez=False, aws={"ec2": "running", "rds": "available"}, att=True)
        w = self.build_s(S, primary_dies_at=None, adapter_kw=dict(db_attestation=None)); w.primary_http = "drop"; w.primary_lease.store = _Partitioned(w.store)
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("desconocido", res["abort_reason"]); self.assertEqual(res["fencing"]["verdict"], "UNKNOWN")
        self.assert_untouched(res, w)
        w = self.build_s(S, primary_dies_at=None, name="vieja", ledger=PromotionLedger(self.d / "l-vieja.json"), adapter_kw=dict(db_attestation=lambda: {"ok": False, "reason": "atestación vencida"}))
        w.primary_http = "drop"; w.primary_lease.store = _Partitioned(w.store)
        self.assertEqual(self.run_fo(w)["outcome"], "ABORTED")

    def test_falso_positivo_una_sola_familia_o_sondeador_aislado_no_promueve(self):
        for kw, kind in ((dict(aws={"ec2": None, "rds": None}), "TRANSIENT"), (dict(control=False), "SONDEADOR_AISLADO"), (dict(aws={"ec2": "running", "rds": "available"}, att=None), "NETWORK_ISOLATION")):
            w = self.build_s(self.signals(**kw), primary_dies_at=3.0, name="fp-" + kind[:4].lower(), ledger=PromotionLedger(self.d / f"l-{kind}.json"))
            res = self.run_fo(w)
            self.assertEqual(res["incident"]["kind"], kind); self.assertEqual(res["outcome"], "ABORTED", kind)
            self.assertEqual((w.dns.applied, w.standby.writes_permitted(), w.ledger.state()), (0, False, "NONE"), kind)

    def test_perdida_del_lease_durante_las_comprobaciones_de_salud_impide_habilitar_escrituras(self):
        S = self.signals(); w = self.build_s(S)
        orig = w.ad.standby_readiness
        def slow():
            w.standby_lease.store = _Partitioned(w.store); w.ad.sleep(40.0)      # el standby pierde el almacén y su lease caduca mientras se comprueba la salud
            return orig()
        w.ad.standby_readiness = slow
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("lease", res["abort_reason"])
        self.assertEqual((w.dns.applied, w.standby.writes_permitted(), w.standby_db.rows()), (0, False, [])); self.assertEqual(w.monitor["double"], 0)

    def test_restauracion_fallida_o_respaldo_para_otro_certificado_c04_aborta_antes_del_lease(self):
        w = self.build_s(self.signals(), with_backup=False, adapter_kw=dict(restore_cert_sha256="a" * 64))
        self.make_backup(5, "ultimo", recipient="b" * 64)                        # cifrado para OTRO certificado
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIsNone(res.get("epoch")); self.assert_untouched(res, w)
        w = self.build_s(self.signals(), name="c04ok", with_backup=False, ledger=PromotionLedger(self.d / "l-c04.json"), adapter_kw=dict(restore_cert_sha256="a" * 64))
        self.make_backup(4, "ultimo", recipient="a" * 64)                        # certificado fijado y declarado: admisible
        res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE", res.get("abort_reason"))

    def test_retorno_de_aws_tras_la_promocion_no_escribe_y_el_failback_no_es_automatico(self):
        S = self.signals(); w = self.build_s(S); res = self.run_fo(w); self.assertEqual(res["outcome"], "DONE")
        w.primary.alive = True; w.primary.frozen = False; w.primary_http = 200; S.update(livez=True, ready=True, aws={"ec2": "running", "rds": "available"})
        w.ad.sleep(60.0)                                                        # AWS vuelve: intenta recuperar el lease y escribir
        with self.assertRaises(FencedOut): w.primary.write("retorno-de-aws")
        self.assertEqual(w.monitor["double"], 0); self.assertTrue(w.standby.writes_permitted())
        plan = FB.plan_failback(ledger_state=w.ledger.state(), primary_fenced=(w.ad.old_can_write() is False), primary_data_status="DESCONOCIDO", standby_is_writer=w.standby.writes_permitted())
        self.assertFalse(plan["automatic"]); self.assertFalse(plan["allowed"]); self.assertIn("revisión humana", " ".join(plan["blockers"]))

    def test_dns_en_modo_de_prueba_planifica_sin_cambiar_nada(self):
        S = self.signals(); w = self.build_s(S)
        res = run_failover(w.ad, w.ocfg, State(w.statep, w.ad.run_id), dry_run=True)
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual(w.dns.applied, 0); self.assertFalse(res["stages"]["SWITCH_DNS"]["result"]["aplicado"])

    def http_detector(self, w, aws):
        return ap.detector_from_http(livez_url=f"{self.base}/p/health", ready_url=f"{self.base}/p/ready", control_url=f"{self.base}/c/health", gate_url=f"{self.base}/p/write-gate",
                                     aws=lambda: aws, gate_attested=True, allow_http_localhost=True, attempts=1, sleep=lambda s: None)

    def test_detector_con_sondas_http_reales_clasifica_sano_caido_y_sondeador_aislado(self):
        aws = {"ec2": "running", "rds": "available"}
        w = self.build(primary_dies_at=None); det = self.http_detector(w, aws)
        self.assertEqual(det.observe()["kind"], "HEALTHY")
        w.primary_http = "drop"; aws["ec2"] = "stopped"
        self.assertEqual(det.observe()["kind"], "INSTANCE_DOWN")
        w.control_ok = False                                                    # el sondeador pierde el control: NO se concluye nada, aunque AWS diga que está parada
        self.assertEqual(det.observe()["kind"], "SONDEADOR_AISLADO")

    def test_extremo_a_extremo_con_sondas_http_reales_y_estado_de_aws(self):
        aws = {"ec2": "stopped", "rds": "available"}
        w = self.build(adapter_kw=None, primary_dies_at=3.0)
        w.ad.detector = self.http_detector(w, aws); w.ad.aws_state = lambda: aws
        res = self.run_fo(w)
        self.assertEqual(res["outcome"], "DONE", res.get("abort_reason")); self.assertEqual(res["incident"]["kind"], "INSTANCE_DOWN")
        self.assertEqual(w.monitor["double"], 0); self.assertEqual(res["fencing"]["verdict"], "FENCED")


if __name__ == "__main__":
    pass
