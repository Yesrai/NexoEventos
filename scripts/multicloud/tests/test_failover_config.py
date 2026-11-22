import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
import failover_config as FC  # noqa: E402

ORCH = Path(__file__).resolve().parents[1] / "failover/orchestrator.py"


class Validacion(unittest.TestCase):
    def cfg(self):
        return copy.deepcopy(FC.EXAMPLE)

    def test_el_ejemplo_valido_sin_comprobar_archivos(self):
        r = FC.validate(self.cfg(), check_files=False); self.assertTrue(r["ok"], r["errors"]); self.assertEqual(r["modo"], "standby_preparado")

    def test_automatico_exige_una_identidad_de_recuperacion_que_no_dependa_de_una_persona(self):
        c = self.cfg(); c["automatic"] = True; c["primary"]["strong_fence"]["validated_on_real_rds"] = True; c["primary"]["seal"]["antirollback_validated"] = True; c["primary"]["freshness_witness"].update(independent_infrastructure_validated=True, witnesses=2, quorum_k=2)
        r = FC.validate(c, check_files=False); self.assertFalse(r["ok"]); self.assertTrue(any("PERSONA" in e for e in r["errors"]))        # la clave personal C-04 en el Mac no sirve para automático
        c["recovery"].pop("private_key_file"); c["recovery"].update(key_provider="oci_vault_secret", key_ref="ocid1.vaultsecret.oc1.sa-saopaulo-1.xxxx")
        r = FC.validate(c, check_files=False); self.assertTrue(r["ok"], r["errors"]); self.assertEqual(r["modo"], "failover_automatico"); self.assertTrue(any("NO implementado" in w for w in r["warnings"]))
        c["recovery"]["private_key_file"] = "/etc/x/k.pem"; self.assertTrue(any("no debe usarse" in e for e in FC.validate(c, check_files=False)["errors"]))

    def test_automatico_solo_si_todo_es_valido_y_se_pide_expresamente(self):
        c = self.cfg(); c["automatic"] = True; c["primary"]["strong_fence"]["validated_on_real_rds"] = True; c["primary"]["seal"]["antirollback_validated"] = True; c["primary"]["freshness_witness"].update(independent_infrastructure_validated=True, witnesses=2, quorum_k=2); c["recovery"].pop("private_key_file"); c["recovery"].update(key_provider="oci_kms", key_ref="ocid1.key.oc1.sa-saopaulo-1.xxxx")
        self.assertEqual(FC.validate(c, check_files=False)["modo"], "failover_automatico")
        c["recovery"]["cert_sha256"] = ""; r = FC.validate(c, check_files=False); self.assertFalse(r["ok"]); self.assertEqual(r["modo"], "recuperacion_desde_respaldo")

    def test_cada_incumplimiento_de_seguridad_se_rechaza(self):
        casos = [
            (lambda c: c["primary"].update(gate_attested=False), "gate_attested"),
            (lambda c: c["primary"].pop("aws"), "primary.aws"),
            (lambda c: c["primary"].update(livez_url="http://app.example/livez"), "primary.livez_url"),
            (lambda c: c["primary"].update(ready_url="https://u:p@app.example/ready"), "primary.ready_url"),
            (lambda c: c["standby"].update(api_url="https://oci.example/api/events?token=1"), "standby.api_url"),
            (lambda c: c["lease"].update(store="file"), "lease"),
            (lambda c: c["recovery"].update(cert_sha256="123"), "cert_sha256"),
            (lambda c: c["recovery"].update(private_key_file="work/k.pem"), "ruta absoluta"),
            (lambda c: c["recovery"].update(private_key_file="/Users/x/Workspace/NexoEventos/work/k.pem"), "dentro del repositorio"),
            (lambda c: c["dns"].update(mode="auto"), "dns.mode"),
            (lambda c: c["primary"].update(db_fence="off"), "db_fence"),
            (lambda c: c["primary"].pop("attestation_max_age_s"), "attestation_max_age_s"),
            (lambda c: c["primary"].update(attestation_max_age_s=300), "attestation_max_age_s"),
            (lambda c: c["recovery"].update(key_provider="otro"), "key_provider"),
            (lambda c: c["detector"].update(rounds=1), "rounds"),
            (lambda c: c["detector"].update(quorum=1), "quorum"),
            (lambda c: c["recovery"].update(password="x"), "secreto en línea"),
            (lambda c: c["lease"].update(par_url="https://x/p/TOKEN/o/"), "secreto en línea"),
        ]
        for mut, frag in casos:
            c = self.cfg(); mut(c); r = FC.validate(c, check_files=False)
            self.assertFalse(r["ok"], frag); self.assertTrue(any(frag in e for e in r["errors"]), (frag, r["errors"])); self.assertNotIn("TOKEN", json.dumps(r))

    def test_archivos_con_permisos_abiertos_o_ausentes_se_rechazan(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            k, par, pub = Path(t) / "k.pem", Path(t) / "par.url", Path(t) / "s.pub"
            for f in (k, par, pub): f.write_text("x")
            c = self.cfg(); c["recovery"].update(private_key_file=str(k), signer_pub=str(pub)); c["lease"].update(par_url_file=str(par))
            os.chmod(k, 0o644); os.chmod(par, 0o600)
            r = FC.validate(c); self.assertTrue(any("0600" in e and "private_key_file" in e for e in r["errors"]))
            os.chmod(k, 0o600); self.assertTrue(FC.validate(c)["ok"])
            par.unlink(); self.assertTrue(any("par_url_file" in e for e in FC.validate(c)["errors"]))

    def test_preflight_cli_valida_sin_ejecutar_nada_y_run_sigue_rechazado(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "c.json"; f.write_text(json.dumps(FC.EXAMPLE))
            r = subprocess.run([sys.executable, str(ORCH), "preflight", "--config", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1); self.assertIn("no existe o no se puede leer", r.stdout)           # el ejemplo apunta a rutas que no existen aquí: falla cerrado
            r = subprocess.run([sys.executable, str(ORCH), "run"], capture_output=True, text=True, env={**os.environ, "NEXO_ALLOW_FAILOVER_EXECUTE": "YES"})
            self.assertEqual(r.returncode, 2)



    def test_el_vallado_fuerte_es_obligatorio_y_el_automatico_queda_bloqueado_hasta_validarlo_en_RDS_real(self):
        for mut, frag in ((lambda c: c["primary"].pop("strong_fence"), "strong_fence.require"), (lambda c: c["primary"]["strong_fence"].update(require=False), "strong_fence.require"),
                          (lambda c: c["primary"]["strong_fence"].update(methods=["atestacion"]), "methods"), (lambda c: c["primary"]["strong_fence"].update(max_age_s=600), "max_age_s"),
                          (lambda c: c["primary"]["strong_fence"].update(allow_stop_rds="si"), "allow_stop_rds"), (lambda c: c["lease"].pop("auth"), "lease.auth"), (lambda c: c["primary"].pop("seal"), "seal.require"),
                          (lambda c: c["primary"]["seal"].pop("operator_pubkey_file"), "operator_pubkey_file"), (lambda c: c["primary"].pop("freshness_witness"), "freshness_witness.require"),
                          (lambda c: c["primary"]["freshness_witness"].pop("pubkey_file"), "pubkey_file"), (lambda c: c["primary"]["freshness_witness"].update(max_age_s=999), "max_age_s")):
            c = self.cfg(); mut(c); r = FC.validate(c, check_files=False); self.assertFalse(r["ok"], frag); self.assertTrue(any(frag in e for e in r["errors"]), (frag, r["errors"]))
        c = self.cfg(); c["automatic"] = True; c["recovery"].pop("private_key_file"); c["recovery"].update(key_provider="oci_kms", key_ref="ocid1.key.oc1.sa-saopaulo-1.xxxx")
        r = FC.validate(c, check_files=False); self.assertFalse(r["ok"]); self.assertTrue(any("validated_on_real_rds" in e for e in r["errors"]))
        c["primary"]["strong_fence"]["validated_on_real_rds"] = True; r = FC.validate(c, check_files=False); self.assertTrue(any("antirollback_validated" in e for e in r["errors"]), r["errors"])
        c["primary"]["seal"]["antirollback_validated"] = True; r = FC.validate(c, check_files=False); self.assertTrue(any("independent_infrastructure_validated" in e for e in r["errors"]), r["errors"])
        c["primary"]["freshness_witness"].update(independent_infrastructure_validated=True); r = FC.validate(c, check_files=False); self.assertTrue(any("≥ 2 testigos" in e for e in r["errors"]), r["errors"])      # un solo testigo no basta para el automático      # sin testigo independiente validado el automático sigue bloqueado      # sello sin antirretroceso validado: automático bloqueado      # automático bloqueado: vallado fuerte sin validar en RDS real


if __name__ == "__main__":
    unittest.main()
