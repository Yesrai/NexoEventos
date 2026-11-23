"""Pruebas de B-17 (verify_clean.py): 100 % simuladas; no se conecta a ninguna nube ni ejecuta ninguna CLI real.
Uso: python3 -m unittest discover -s scripts/multicloud/tests -p 'test_verify_clean.py' -v"""
import contextlib, io, json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import verify_clean as vc  # noqa: E402

NOW = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
OCID = "ocid1.instance.oc1.sa-saopaulo-1.anuwcljsabcdefghijklmnopqrstuvwxyz0123456789SECRETTAIL"


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def oci_empty():
    return {"oci": dict(instances={"data": []}, boot={"data": []}, block={"data": []}, bastions={"data": []}, public_ips={"data": []}, nat={"data": []}, lbs={"data": []})}


def run_main(inv, extra=None, baseline=None):
    with tempfile.TemporaryDirectory() as d:
        fx = os.path.join(d, "inv.json"); json.dump(inv, open(fx, "w"))
        args = ["--fixture", fx] + (extra or [])
        if baseline is not None:
            bp = os.path.join(d, "base.json"); json.dump(baseline, open(bp, "w")); args += ["--baseline", bp]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vc.main(args, now=NOW)
        return code, out.getvalue()


class OciCases(unittest.TestCase):
    def test_limpio(self):
        code, out = run_main(oci_empty())
        self.assertEqual(code, 0); self.assertIn("LIMPIO", out)

    def test_instancia_terminada_no_cuenta(self):
        inv = oci_empty(); inv["oci"]["instances"] = {"data": [{"id": OCID, "lifecycle-state": "TERMINATED", "shape": "VM.Standard.E5.Flex"}]}
        self.assertEqual(run_main(inv)[0], 0)

    def test_e5_en_marcha_es_residual_con_costo_y_tope(self):
        inv = oci_empty(); inv["oci"]["instances"] = {"data": [{"id": OCID, "lifecycle-state": "RUNNING", "shape": "E5.Flex", "shape-config": {"ocpus": 1, "memory-in-gbs": 8}, "time-created": ago(95)}]}
        code, out = run_main(inv, ["--max-age-min", "90", "--until-hours", "100"])
        self.assertEqual(code, 1)
        self.assertIn("0.0460", out)                    # 1×0,03 + 8×0,002
        self.assertIn("EXCEDE el tope de 90 min", out)
        self.assertNotIn("SECRETTAIL", out)             # el OCID completo no se imprime
        self.assertIn("4.60", out)                      # proyección 0,046 USD/h × 100 h

    def test_terminando_aun_no_esta_limpio(self):
        inv = oci_empty(); inv["oci"]["instances"] = {"data": [{"id": OCID, "lifecycle-state": "TERMINATING", "shape": "VM.Standard.E2.1.Micro"}]}
        code, out = run_main(inv); self.assertEqual(code, 1); self.assertIn("PENDIENTE", out)

    def test_volumen_huerfano(self):
        inv = oci_empty(); inv["oci"]["boot"] = {"data": [{"id": OCID, "lifecycle-state": "AVAILABLE", "size-in-gbs": 50, "vpus-per-gb": 10}]}
        code, out = run_main(inv, ["--json"]); d = json.loads(out)
        self.assertEqual(code, 1); self.assertAlmostEqual(d["recursos"][0]["hourly"], 50 * (0.0255 + 10 * 0.0017) / 730, places=6)

    def test_bastion_activo_es_residual_aunque_no_cobre(self):
        inv = oci_empty(); inv["oci"]["bastions"] = {"data": [{"id": OCID, "lifecycle-state": "ACTIVE", "name": "nexorecovery"}]}
        self.assertEqual(run_main(inv)[0], 1)

    def test_ip_reservada_si_efimera_no(self):
        inv = oci_empty(); inv["oci"]["public_ips"] = {"data": [{"id": OCID, "lifetime": "EPHEMERAL", "lifecycle-state": "ASSIGNED"}]}
        self.assertEqual(run_main(inv)[0], 0)
        inv["oci"]["public_ips"] = {"data": [{"id": OCID, "lifetime": "RESERVED", "lifecycle-state": "AVAILABLE"}]}
        self.assertEqual(run_main(inv)[0], 1)

    def test_estado_desconocido_es_no_verificable(self):
        inv = oci_empty(); inv["oci"]["instances"] = {"data": [{"id": OCID, "lifecycle-state": "EXTRAÑO", "shape": "VM.Standard.E2.1.Micro"}]}
        code, out = run_main(inv); self.assertEqual(code, 2); self.assertIn("NO VERIFICABLE", out)

    def test_dato_ausente_es_no_verificable(self):
        inv = oci_empty(); inv["oci"]["boot"] = None
        self.assertEqual(run_main(inv)[0], 2)
        inv = oci_empty(); inv["oci"]["lbs"] = {"data": "no es una lista"}
        self.assertEqual(run_main(inv)[0], 2)

    def test_inventario_vacio_no_es_limpio(self):
        self.assertEqual(run_main({})[0], 2)


class AwsCases(unittest.TestCase):
    BASE = {"aws_stopped_ec2_names": ["nexoeventos-academy-app"]}

    def inv(self, **kw):
        d = dict(instances=[], load_balancers=[], rds=[], nat_gateways=[], addresses=[], volumes=[]); d.update(kw); return {"aws": d}

    def ec2(self, state, name="nexoeventos-academy-app"):
        return [{"Instances": [{"InstanceId": "i-0123456789abcdef0", "InstanceType": "t3.small", "State": {"Name": state}, "LaunchTime": ago(600), "Tags": [{"Key": "Name", "Value": name}]}]}]

    def test_estado_actual_del_proyecto_es_limpio(self):
        inv = self.inv(instances=self.ec2("stopped"), rds=[{"DBInstanceIdentifier": "nexoeventos-academy-postgres", "DBInstanceStatus": "stopped", "MultiAZ": True, "DBInstanceClass": "db.t3.micro"}])
        code, out = run_main(inv, baseline=self.BASE); self.assertEqual(code, 0, out); self.assertIn("Esperados", out)

    def test_ec2_en_marcha(self):
        code, out = run_main(self.inv(instances=self.ec2("running")), baseline=self.BASE); self.assertEqual(code, 1); self.assertIn("0.0258", out)

    def test_ec2_detenida_fuera_de_linea_base(self):
        self.assertEqual(run_main(self.inv(instances=self.ec2("stopped", "otra")), baseline=self.BASE)[0], 1)

    def test_rds_disponible_es_residual(self):
        rds = [{"DBInstanceIdentifier": "nexoeventos-academy-postgres", "DBInstanceStatus": "available", "MultiAZ": True, "DBInstanceClass": "db.t3.micro"}]
        code, out = run_main(self.inv(rds=rds), baseline=self.BASE); self.assertEqual(code, 1); self.assertIn("0.0420", out)

    def test_alb_nat_eip_y_volumen_huerfano(self):
        for key, item in (("load_balancers", {"LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/x/abcdef123456", "State": {"Code": "active"}, "LoadBalancerName": "x"}),
                          ("nat_gateways", {"NatGatewayId": "nat-0abc123456789", "State": "available"}),
                          ("addresses", {"AllocationId": "eipalloc-0abc123456"}),
                          ("volumes", {"VolumeId": "vol-0abc123456789", "State": "available", "Size": 20})):
            code, out = run_main(self.inv(**{key: [item]}), baseline=self.BASE)
            self.assertEqual(code, 1, key); self.assertNotIn("111111111111", out)
        self.assertEqual(run_main(self.inv(addresses=[{"AllocationId": "eipalloc-0abc", "AssociationId": "eipassoc-1"}]))[0], 0)
        self.assertEqual(run_main(self.inv(volumes=[{"VolumeId": "vol-0abc123456789", "State": "in-use", "Size": 20}]))[0], 0)

    def test_rds_estado_raro(self):
        rds = [{"DBInstanceIdentifier": "x", "DBInstanceStatus": "inaccessible-encryption-credentials", "MultiAZ": False, "DBInstanceClass": "db.t3.micro"}]
        self.assertEqual(run_main(self.inv(rds=rds))[0], 2)


class LiveCases(unittest.TestCase):
    def make_runner(self, responses, calls):
        def runner(argv):
            calls.append(list(argv))
            key = tuple(argv[: 4 if argv[0] == "oci" else 3])
            r = responses.get(key)
            if isinstance(r, Exception): raise r
            if r is None:
                if argv[0] == "oci": return SimpleNamespace(returncode=0, stdout="", stderr="")      # OCI no imprime nada si la lista está vacía
                name = {"describe-instances": "Reservations", "describe-load-balancers": "LoadBalancers", "describe-db-instances": "DBInstances", "describe-nat-gateways": "NatGateways", "describe-addresses": "Addresses", "describe-volumes": "Volumes"}[argv[2]]
                return SimpleNamespace(returncode=0, stdout=json.dumps({name: []}), stderr="")
            if isinstance(r, tuple): return SimpleNamespace(returncode=r[0], stdout="", stderr=r[1])
            return SimpleNamespace(returncode=0, stdout=json.dumps(r), stderr="")
        return runner

    def run_live(self, responses, extra):
        calls = []; out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vc.main(["--live"] + extra, runner=self.make_runner(responses, calls), now=NOW)
        return code, out.getvalue(), calls

    def test_live_limpio_y_solo_comandos_de_lectura(self):
        code, out, calls = self.run_live({}, ["--oci-compartment", "ocid1.compartment.oc1..x", "--oci-ad", "AD-1", "--aws"])
        self.assertEqual(code, 0, out)
        self.assertGreaterEqual(len(calls), 13)
        for c in calls:
            self.assertIn(tuple(c[: 4 if c[0] == "oci" else 3]), vc.ALLOWED)
            self.assertFalse(any(w in " ".join(c) for w in ("terminate", "delete", "stop", "start-", "create", "run-instances", "update", "modify", "reboot")), c)

    def test_credenciales_caducadas_es_no_verificable(self):
        code, out, _ = self.run_live({("aws", "ec2", "describe-instances"): (254, "An error occurred (ExpiredToken) token AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")}, ["--aws"])
        self.assertEqual(code, 2); self.assertIn("ExpiredToken", out); self.assertNotIn("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", out)

    def test_cli_ausente_es_no_verificable(self):
        code, _, _ = self.run_live({("oci", "compute", "instance", "list"): FileNotFoundError("oci")}, ["--oci-compartment", "x", "--oci-ad", "AD-1"])
        self.assertEqual(code, 2)

    def test_aws_salida_vacia_o_sin_lista_es_no_verificable(self):
        calls = []; out = io.StringIO()
        runner = lambda argv: SimpleNamespace(returncode=0, stdout="", stderr="")
        with contextlib.redirect_stdout(out):
            self.assertEqual(vc.main(["--live", "--aws"], runner=runner, now=NOW), 2)
        runner = lambda argv: SimpleNamespace(returncode=0, stdout=json.dumps({"Otra": []}), stderr="")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vc.main(["--live", "--aws"], runner=runner, now=NOW), 2)

    def test_si_un_proveedor_falla_el_otro_se_informa_igualmente_y_el_veredicto_es_no_verificable(self):
        r = {("aws", "ec2", "describe-instances"): (254, "UnauthorizedOperation"),
             ("oci", "compute", "instance", "list"): {"data": [{"id": OCID, "lifecycle-state": "RUNNING", "shape": "VM.Standard.E2.1.Micro", "time-created": ago(5)}]}}
        code, out, _ = self.run_live(r, ["--oci-compartment", "x", "--oci-ad", "AD-1", "--aws"])
        self.assertEqual(code, 2); self.assertIn("AWS no verificable", out); self.assertIn("RUNNING", out)       # el residuo de OCI se muestra aunque AWS no se pudo consultar
        self.assertNotIn("LIMPIO", out); self.assertIn("OCI: consultado", out)

    def test_los_numeros_de_cuenta_de_los_errores_se_enmascaran(self):
        r = {("aws", "ec2", "describe-instances"): (254, "AccessDenied: User arn:aws:sts::123456789012:assumed-role/voclabs/x is not authorized")}
        code, out, _ = self.run_live(r, ["--aws"]); self.assertEqual(code, 2); self.assertNotIn("123456789012", out); self.assertIn("<cuenta>", out)

    def test_live_sin_proveedor_o_sin_ad(self):
        self.assertEqual(self.run_live({}, [])[0], 2)
        self.assertEqual(self.run_live({}, ["--oci-compartment", "x"])[0], 2)

    def test_lista_blanca_rechaza_modificaciones(self):
        for argv in (["oci", "compute", "instance", "terminate", "--instance-id", "x"], ["aws", "ec2", "run-instances"], ["aws", "rds", "stop-db-instance"], ["oci", "bastion", "bastion", "delete"]):
            with self.assertRaises(PermissionError): vc.guarded_run(argv, runner=lambda a: self.fail("se ejecutó un comando no permitido"))
        with self.assertRaises(PermissionError): vc.guarded_run(["oci", "compute", "instance", "list", "--force"], runner=lambda a: self.fail("se ejecutó"))

    def test_residuo_en_vivo(self):
        r = {("oci", "compute", "instance", "list"): {"data": [{"id": OCID, "lifecycle-state": "RUNNING", "shape": "VM.Standard.E2.1.Micro", "time-created": ago(5)}]}}
        code, out, _ = self.run_live(r, ["--oci-compartment", "x", "--oci-ad", "AD-1"])
        self.assertEqual(code, 1); self.assertIn("RUNNING", out)


class SalidaYSeguridad(unittest.TestCase):
    def test_json_valido_y_sin_datos_sensibles(self):
        inv = oci_empty(); inv["oci"]["instances"] = {"data": [{"id": OCID, "lifecycle-state": "RUNNING", "shape": "VM.Standard.E2.1.Micro", "time-created": ago(10)}]}
        code, out = run_main(inv, ["--json"]); d = json.loads(out)
        self.assertEqual(d["codigo"], 1); self.assertNotIn("SECRETTAIL", out); self.assertNotIn("ocid1.instance", out)

    def test_el_verificador_no_contiene_llamadas_de_escritura(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "verify_clean.py")) as fh:
            src = fh.read()
        calls = [l for l in src.splitlines() if '["oci"' in l or '["aws"' in l or 'q("' in l]
        self.assertTrue(calls)
        for l in calls:
            self.assertFalse(any(w in l for w in ("terminate", "delete", "create", "stop", "start", "modify", "update", "run-instances")), l)


if __name__ == "__main__":
    unittest.main()
