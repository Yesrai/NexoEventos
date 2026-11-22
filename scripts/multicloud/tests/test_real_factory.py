"""La fábrica de adaptadores: mapeo de la configuración, rechazo ante configuración insegura o proveedores ausentes y bloqueo del modo real. Proveedores SIMULADOS; sin red ni nube."""
import copy, os, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "failover")); sys.path.insert(0, str(HERE.parents[2] / "backend"))
import failover_config as FC  # noqa: E402
import real_factory as RF  # noqa: E402
import adapters_probes as ap  # noqa: E402
from adapters_standby import FullRecoveryAdapters, SimClock  # noqa: E402


class Stub:
    def __init__(self, name): self.name = name
    def __repr__(self): return f"Stub({self.name})"


def providers(skip=()):
    p = {n: (lambda cfg, n=n: Stub(n)) for n in RF.REQUIRED_PROVIDERS}
    p["clock"] = lambda cfg: SimClock()
    p["dns_runtime"] = lambda cfg: {"resolver": Stub("resolver"), "opener": Stub("opener")}
    for s in skip: p.pop(s, None)
    return p


def cfg_ok():
    c = copy.deepcopy(FC.EXAMPLE); c["dns"] = {"mode": "dry-run", "domain": "nexoeventos-test", "target": "b", "config_path": "/x/dns.json", "token_file": "/x/token", "state_dir": "/x/state"}; return c


class Fabrica(unittest.TestCase):
    def build(self, c=None, **kw): return RF.build_adapters(c or cfg_ok(), providers(), check_files=False, **kw)

    def test_construye_adaptadores_completos_con_proveedores_simulados(self):
        a = self.build(); self.assertIsInstance(a, FullRecoveryAdapters)
        self.assertEqual(len(a.probes.probes), 3); self.assertIsNotNone(a.probes.control)
        self.assertEqual(set(a.standby_readiness_probes), {"livez", "ready", "api"})

    def test_banderas_de_seguridad_salen_de_la_configuracion(self):
        a = self.build(); self.assertTrue(a.require_primary_db_fence); self.assertTrue(a.require_strong_fence); self.assertTrue(a.requires_seal)
        self.assertEqual(a.restore_cert_sha256, FC.EXAMPLE["recovery"]["cert_sha256"]); self.assertEqual(a.max_backup_age_s, 3600.0)
        self.assertEqual(a.oci["passin"], "env:NEXO_RECOVERY_PASS"); self.assertTrue(a.min_probes >= 2)

    def test_dns_no_puede_cambiar_por_defecto_ni_con_apply_sin_la_variable(self):
        self.assertFalse(self.build().dns.allow_change)                                 # dry-run
        c = cfg_ok(); c["dns"]["mode"] = "apply"
        self.assertFalse(RF.build_adapters(c, providers(), check_files=False, env={}).dns.allow_change)                                    # apply sin NEXO_ALLOW_DNS_CHANGE
        self.assertTrue(RF.build_adapters(c, providers(), check_files=False, env={"NEXO_ALLOW_DNS_CHANGE": "YES"}).dns.allow_change)      # ambas condiciones

    def test_configuracion_insegura_no_produce_adaptadores(self):
        for mut in (lambda c: c["primary"].update(db_fence="off"), lambda c: c["primary"].update(gate_attested=False), lambda c: c["lease"].update(store="file"),
                    lambda c: c["primary"].pop("seal"), lambda c: c["primary"]["freshness_witness"].update(require=False), lambda c: c["recovery"].update(cert_sha256="12")):
            c = cfg_ok(); mut(c)
            with self.assertRaises(RF.WiringError): RF.build_adapters(c, providers(), check_files=False)

    def test_falta_de_un_proveedor_se_rechaza_con_su_nombre(self):
        for name in RF.REQUIRED_PROVIDERS:
            with self.assertRaises(RF.WiringError) as cm: RF.build_adapters(cfg_ok(), providers(skip=(name,)), check_files=False)
            self.assertIn(name, str(cm.exception))

    def test_el_modo_real_esta_bloqueado(self):
        self.assertFalse(RF.REAL_WIRING_ENABLED)
        with self.assertRaises(RF.NotWired): RF.build_adapters(cfg_ok(), providers(), mode="real", check_files=False)
        with self.assertRaises(RF.NotWired): RF.build_adapters(FC.EXAMPLE, {}, mode="real")           # ni siquiera valida: se bloquea primero

    def test_automatico_y_dominio_de_produccion_se_rechazan(self):
        c = cfg_ok(); c["automatic"] = True
        with self.assertRaises(RF.WiringError): RF.build_adapters(c, providers(), check_files=False)
        c = cfg_ok(); c["dns"]["domain"] = "nexoeventos-demo"
        with self.assertRaises(RF.WiringError) as cm: RF.build_adapters(c, providers(), check_files=False)
        self.assertIn("producción", str(cm.exception))

    def test_dns_incompleto_se_rechaza(self):
        c = cfg_ok(); c["dns"].pop("token_file")
        with self.assertRaises(RF.WiringError): RF.build_adapters(c, providers(), check_files=False)

    def test_contrato_real_documenta_cada_proveedor_requerido(self):
        self.assertEqual(set(RF.REAL_CONTRACT), set(RF.REQUIRED_PROVIDERS))

    def test_derive_kwargs_es_pura_y_no_abre_archivos(self):
        kw = RF.derive_kwargs(FC.EXAMPLE); self.assertEqual(str(kw["oci_key"]), FC.EXAMPLE["recovery"]["private_key_file"]); self.assertFalse(os.path.exists(str(kw["signer_pub"])))


if __name__ == "__main__":
    unittest.main()
