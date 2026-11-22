"""Limpieza y fallos del probe de PAR (oci_par_probe.py) con un cliente OCI FALSO: timeout, red caída, error de reloj, fallo de limpieza. Sin nube."""
import io, json, sys, types, unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hybrid"))
fake_oci = types.ModuleType("oci"); fake_oci.exceptions = types.SimpleNamespace(ServiceError=type("ServiceError", (Exception,), {})); sys.modules.setdefault("oci", fake_oci)
import oci_par_probe as P  # noqa: E402


class Obj:
    def __init__(s, **k): s.__dict__.update(k)


class FakeClient:
    def __init__(s, pars, versions, fail=()):
        s.pars, s.vers, s.fail, s.deleted_pars, s.deleted_objs = dict(pars), list(versions), set(fail), [], []
    def _f(s, name):
        if name in s.fail: raise TimeoutError(name)
    def list_preauthenticated_requests(s, ns, b, object_name_prefix=None):
        s._f("list_par"); return Obj(data=[Obj(id=i, name=n) for n, i in s.pars.items()])
    def delete_preauthenticated_request(s, ns, b, pid):
        s._f("delete_par"); s.pars = {n: i for n, i in s.pars.items() if i != pid}; s.deleted_pars.append(pid)
    def list_object_versions(s, ns, b, prefix=None):
        s._f("list_versions"); return Obj(data=Obj(items=[Obj(name=n, version_id=v) for n, v in s.vers]))
    def delete_object(s, ns, b, name, version_id=None):
        s._f("delete_object"); s.vers = [x for x in s.vers if x != (name, version_id)]; s.deleted_objs.append(name)


PFX = "hybrid-test/par-probe-20261125/"; A = Obj(bucket="nexoeventos-recovery", prefix=PFX, workdir="/nonexistent-par-probe")


def run_end(client, pars, objs, out=None):
    out = out if out is not None else {"run": "abc123"}; buf = io.StringIO()
    with redirect_stdout(buf): code = P.end(client, "ns", A, pars, objs, out, {})
    return code, json.loads(buf.getvalue())


class Limpieza(unittest.TestCase):
    objs = {"lease": PFX + "lease-abc123.json", "race": PFX + "race-abc123.json"}

    def test_limpieza_completa_devuelve_0(self):
        c = FakeClient({"par-probe-lease-abc123": "id1", "par-probe-race-abc123": "id2"}, [(self.objs["lease"], "v1"), (self.objs["race"], "v1")])
        code, out = run_end(c, {"lease": "id1", "race": "id2"}, self.objs)
        self.assertEqual((code, out["limpio"], out["par_activos_tras_revocar"], out["versiones_restantes_en_prefijo"]), (0, True, 0, 0))

    def test_par_huerfano_cuyo_acuse_se_perdio_se_revoca_por_nombre(self):
        c = FakeClient({"par-probe-lease-abc123": "id1", "par-probe-race-abc123": "idX"}, [])
        code, out = run_end(c, {"lease": "id1"}, self.objs)       # «race» no está en pars (timeout al crearlo)
        self.assertEqual(code, 0); self.assertIn("idX", c.deleted_pars)

    def test_no_revoca_par_ajeno_aunque_este_bajo_el_prefijo(self):
        c = FakeClient({"otro-par-de-alguien": "idZ", "par-probe-lease-ZZZZZZ": "idY"}, [])
        run_end(c, {}, {}); self.assertEqual(c.deleted_pars, [])           # ni otra corrida ni PAR ajeno

    def test_fallo_al_revocar_continua_limpia_objetos_y_devuelve_3(self):
        c = FakeClient({"par-probe-lease-abc123": "id1"}, [(self.objs["lease"], "v1")], fail={"delete_par"})
        code, out = run_end(c, {"lease": "id1"}, self.objs)
        self.assertEqual(code, 3); self.assertFalse(out["limpio"]); self.assertEqual(out["par_activos_tras_revocar"], 1)
        self.assertIn("accion_manual", out); self.assertTrue(any("revocar" in e for e in out["limpieza_errores"])); self.assertEqual(out["versiones_restantes_en_prefijo"], 0)

    def test_red_caida_en_el_listado_no_se_declara_limpio(self):
        c = FakeClient({"par-probe-lease-abc123": "id1"}, [(self.objs["lease"], "v1")], fail={"list_par", "list_versions"})
        code, out = run_end(c, {"lease": "id1"}, self.objs)
        self.assertEqual(code, 3); self.assertFalse(out["limpio"]); self.assertIsNone(out["par_activos_tras_revocar"])

    def test_objeto_ajeno_en_el_prefijo_no_se_borra_y_no_es_limpio(self):
        c = FakeClient({}, [(PFX + "ajeno.json", "v1"), (self.objs["lease"], "v1")])
        code, out = run_end(c, {}, self.objs)
        self.assertEqual(out["objetos_ajenos_en_prefijo"], [PFX + "ajeno.json"]); self.assertEqual(c.deleted_objs, []); self.assertEqual(code, 3)

    def test_borrado_de_objetos_que_falla_deja_residuo_y_codigo_3(self):
        c = FakeClient({}, [(self.objs["lease"], "v1")], fail={"delete_object"})
        code, out = run_end(c, {}, self.objs); self.assertEqual((code, out["versiones_restantes_en_prefijo"]), (3, 1))

    def test_prueba_detenida_pero_limpia_devuelve_1_no_0(self):
        c = FakeClient({}, []); code, out = run_end(c, {}, {}, {"run": "abc123", "detenido": "reloj"}); self.assertEqual((code, out["limpio"]), (1, True))


class Reloj(unittest.TestCase):
    def test_skew(self):
        now = datetime(2026, 11, 25, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(P.skew_s(format_datetime(now - timedelta(seconds=2), usegmt=True), now), 2.0)
        self.assertIsNone(P.skew_s("no es una fecha", now)); self.assertIsNone(P.skew_s(None, now))
        self.assertGreater(P.skew_s(format_datetime(now - timedelta(minutes=10), usegmt=True), now), 5)

    def test_hget_insensible_a_mayusculas(self):
        self.assertEqual(P.hget({"date": "x"}, "Date"), "x"); self.assertIsNone(P.hget({}, "Date"))


class PlanClient(FakeClient):
    """Cliente de solo lectura: CUALQUIER escritura (crear/borrar) hace fallar la prueba."""
    def __init__(s, pars=(), versions=(), date=None):
        super().__init__({n: n for n in pars}, versions); s.date = date
    def get_namespace(s):
        from email.utils import format_datetime
        d = s.date or format_datetime(datetime.now(timezone.utc), usegmt=True); return Obj(data="ns", headers={"Date": d})
    def list_objects(s, ns, b, fields=None, start=None, limit=None): return Obj(data=Obj(objects=[Obj(size=1000), Obj(size=2000)], next_start_with=None))
    def create_preauthenticated_request(s, *a, **k): raise AssertionError("plan-only NO debe crear PAR")
    def delete_preauthenticated_request(s, *a, **k): raise AssertionError("plan-only NO debe borrar PAR")
    def delete_object(s, *a, **k): raise AssertionError("plan-only NO debe borrar objetos")
    def put_object(s, *a, **k): raise AssertionError("plan-only NO debe escribir")


def run_plan(client, bucket_kw=None, **argkw):
    a = Obj(bucket="nexoeventos-recovery", prefix=PFX, rounds=20, contenders=8, lease_race_rounds=20, max_minutes=20.0, max_skew_s=5.0, **argkw)
    b = Obj(**{**dict(public_access_type="NoPublicAccess", versioning="Enabled", storage_tier="Standard"), **(bucket_kw or {})})
    buf = io.StringIO()
    with redirect_stdout(buf): code = P.plan_only(client, "ns", a, b, {"region": "sa-saopaulo-1"})
    return code, json.loads(buf.getvalue())


class PlanOnly(unittest.TestCase):
    def test_todo_en_orden_es_LISTO_y_no_escribe_nada(self):
        code, out = run_plan(PlanClient()); self.assertEqual((code, out["resultado"]), (0, "LISTO")); self.assertEqual(out["T1_crearia"]["rondas_adquisicion"], 20)

    def test_par_activo_ajeno_impide_empezar(self):
        code, out = run_plan(PlanClient(pars=["par-de-alguien"])); self.assertEqual((code, out["comprobaciones"]["cero_PAR_activos"]), (2, False))

    def test_prefijo_con_residuos_impide_empezar(self):
        code, out = run_plan(PlanClient(versions=[(PFX + "lease-x.json", "v1")])); self.assertEqual((code, out["comprobaciones"]["prefijo_vacio"]), (2, False))

    def test_reloj_desfasado_o_ilegible_impide_empezar(self):
        from email.utils import format_datetime
        old = format_datetime(datetime.now(timezone.utc) - timedelta(minutes=5), usegmt=True)
        self.assertEqual(run_plan(PlanClient(date=old))[0], 2); self.assertEqual(run_plan(PlanClient(date="basura"))[0], 2)

    def test_bucket_publico_o_sin_versionado_impide_empezar(self):
        self.assertEqual(run_plan(PlanClient(), {"public_access_type": "ObjectRead"})[0], 2); self.assertEqual(run_plan(PlanClient(), {"versioning": "Suspended"})[0], 2)

    def test_prefijo_fuera_de_hybrid_test_se_rechaza(self):
        a = Obj(bucket="b", prefix="backups/", rounds=20, contenders=8, lease_race_rounds=20, max_minutes=20.0, max_skew_s=5.0); buf = io.StringIO()
        with redirect_stdout(buf): code = P.plan_only(PlanClient(), "ns", a, Obj(public_access_type="NoPublicAccess", versioning="Enabled", storage_tier="Standard"), {"region": "x"})
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
