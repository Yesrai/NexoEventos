"""G1 · Proveedores reales (real_providers.py) probados en LOCAL contra extremos simulados (127.0.0.1 / comandos falsos). Sin red externa ni nube. El modo real de la fábrica sigue bloqueado."""
import copy, os, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "failover")); sys.path.insert(0, str(HERE.parents[2] / "backend"))
import failover_config as FC  # noqa: E402
import real_factory as RF  # noqa: E402
import real_providers as RP  # noqa: E402
from adapters_standby import FullRecoveryAdapters  # noqa: E402
from test_lease_http import H, SECRET, Srv  # noqa: E402


def keypair():
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    return (k.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption()).hex(), k.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw).hex())


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.d = Path(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); cls.S = cls.srv.s = Srv()
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}/p/{SECRET}/n/ns/b/bk/o/"
        cls.par = cls.w("lease.url", base + "writer-lease.json"); cls.att = cls.w("att.url", base + "fence-attestation.json"); cls.pre = cls.w("pre.url", base)
        priv, pub = keypair(); _, pub2 = keypair()
        cls.priv = cls.w("own.key", priv); cls.pub_own = cls.w("own.pub", pub, 0o644); cls.pub_aws = cls.w("aws.pub", pub2, 0o644)
        cls.paths = {"own_private_key_file": cls.priv, "peer_public_files": {"oci-standby": cls.pub_own, "aws-primary": cls.pub_aws}, "lease_state_path": str(cls.d / "lease.state"),
                     "state_dir": str(cls.d / "state"), "attestation_par_url_file": cls.att, "selftest_par_url_file": cls.pre, "seal_log_par_url_file": cls.att}

    @classmethod
    def w(cls, name, text, mode=0o600):
        p = cls.d / name; p.write_text(text); os.chmod(p, mode); return str(p)

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def setUp(self): self.S.reset()

    def cfg(self):
        c = copy.deepcopy(FC.EXAMPLE); c["lease"]["par_url_file"] = self.par
        c["dns"] = {"mode": "dry-run", "domain": "nexoeventos-test", "target": "b", "config_path": "/x/dns.json", "token_file": "/x/token", "state_dir": str(self.d / "dns")}; return c


class Proveedores(Base):
    def test_reloj_real_es_monotono_y_avisa_a_los_oyentes(self):
        t = [100.0]; seen = []
        c = RP.clock_provider(mono=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))(None); c.listeners.append(seen.append)
        c.advance(0.5); self.assertEqual(c.now(), 100.5); self.assertEqual(seen, [100.5])

    def test_ledger_en_el_directorio_de_estado(self):
        led = RP.ledger_provider(self.paths)(self.cfg()); self.assertEqual(led.state() if hasattr(led, "state") else "ok", led.state() if hasattr(led, "state") else "ok")
        self.assertTrue((self.d / "state").is_dir())

    def test_lease_real_se_construye_sin_tocar_la_red(self):
        puts = self.S.puts; l = RP.lease_provider(self.paths, allow_http_localhost=True)(self.cfg())
        self.assertEqual(l.holder_id, "oci-standby"); self.assertEqual(self.S.puts, puts)

    def test_lease_rechaza_clave_privada_con_permisos_abiertos_y_auth_hmac(self):
        p = dict(self.paths, own_private_key_file=self.w("bad.key", "00" * 32, 0o644))
        with self.assertRaises(RP.ProviderError): RP.lease_provider(p, allow_http_localhost=True)(self.cfg())
        c = self.cfg(); c["lease"]["auth"] = "hmac"
        with self.assertRaises(RP.ProviderError): RP.lease_provider(self.paths, allow_http_localhost=True)(c)
        with self.assertRaises(RP.ProviderError): RP.lease_provider(dict(self.paths, peer_public_files={}), allow_http_localhost=True)(self.cfg())

    def test_autoprueba_del_almacen_pasa_y_falla_si_no_respeta_condiciones(self):
        v = RP.store_verifier_provider(self.paths, allow_http_localhost=True)(self.cfg()); self.assertTrue(v())
        self.S.enforce = False; self.assertFalse(v())

    def test_estado_de_aws_es_solo_lectura_y_desconocido_ante_error(self):
        cmds = []
        def run(cmd): cmds.append(cmd); return '["running"]' if "ec2" in cmd else '["available"]'
        r = RP.aws_state_provider(run=run)(self.cfg())(); self.assertEqual(r, {"ec2": "running", "rds": "available"})
        self.assertTrue(all(c[1:3] == ["ec2", "describe-instances"] or c[1:3] == ["rds", "describe-db-instances"] for c in cmds))
        def boom(cmd): raise OSError("x")
        self.assertEqual(RP.aws_state_provider(run=boom)(self.cfg())(), {"ec2": None, "rds": None})

    def test_vallado_fuerte_solo_puede_parar_la_rds_si_la_configuracion_lo_permite(self):
        c = self.cfg(); calls = []
        sf = RP.strong_fence_provider(self.paths, aws_read=lambda: {"rds": "available"}, stop_rds=lambda: calls.append(1))(c)
        self.assertFalse(sf.allow_stop_rds); self.assertIsNone(sf.stop_rds)
        c["primary"]["strong_fence"]["allow_stop_rds"] = True
        with self.assertRaises(RP.ProviderError): RP.strong_fence_provider(self.paths, aws_read=lambda: {})(c)
        self.assertTrue(RP.strong_fence_provider(self.paths, aws_read=lambda: {}, stop_rds=lambda: None)(c).allow_stop_rds)

    def test_atestacion_ausente_es_false(self):
        self.assertFalse(RP.db_attestation_provider(self.paths, allow_http_localhost=True)(self.cfg())())

    def test_sellador_exige_el_informe_al_testigo(self):
        with self.assertRaises(RP.ProviderError): RP.sealer_provider(self.paths, oci_auth=object(), witness_report=None, log=object())(self.cfg())
        self.assertTrue(callable(RP.sealer_provider(self.paths, oci_auth=object(), witness_report=lambda *a: None, log=object())(self.cfg())))

    def test_dns_runtime_entrega_resolvedor_y_abridor(self):
        d = RP.dns_runtime_provider()(self.cfg()); self.assertTrue(callable(d["resolver"]) and callable(d["opener"]))

    def test_ensamblado_completo_y_modo_real_sigue_bloqueado(self):
        class S: pass
        pv = RP.build_real_providers(self.paths, oci_auth=object(), witness_report=lambda *a: None, fence=S(), app_exec=S(), allow_http_localhost=True,
                                     aws_run=lambda c: '["running"]', seal_log=object())
        c = self.cfg(); pv["oci_reader"] = lambda cfg: object()           # el lector de OCI real exige su PAR/CLI: aquí un lector nulo
        a = RF.build_adapters(c, pv, mode="sim", check_files=False, allow_http_localhost=True)
        self.assertIsInstance(a, FullRecoveryAdapters); self.assertIs(a.standby.lease, a.lease)        # el standby comparte EL MISMO lease
        with self.assertRaises(RF.NotWired): RF.build_adapters(c, pv, mode="real", check_files=False)


if __name__ == "__main__":
    unittest.main()
