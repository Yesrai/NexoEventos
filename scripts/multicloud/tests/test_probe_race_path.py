"""Regresión de T1 (22-nov): el probe real lanzó NameError al llegar a la carrera de adquisición porque `lease_race` no estaba importado. Estas pruebas ejercitan ESE camino con un servidor PAR local
(If-Match efectivo) y comprueban, para los scripts de la prueba, que no queden nombres globales sin definir (la clase de error que ocurrió)."""
import io, json, os, symtable, sys, tempfile, threading, types, unittest, builtins
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "hybrid")); sys.path.insert(0, str(HERE.parent / "failover"))
fake_oci = types.ModuleType("oci"); fake_oci.exceptions = types.SimpleNamespace(ServiceError=type("ServiceError", (Exception,), {})); sys.modules.setdefault("oci", fake_oci)
from test_lease_http import H, Srv, SECRET  # noqa: E402
import oci_par_probe as P  # noqa: E402
from app.failover.lease import LeaseConfig  # noqa: E402


class Obj:
    def __init__(s, **k): s.__dict__.update(k)


class CarreraDelProbe(unittest.TestCase):
    def test_lease_race_step_corre_con_el_codigo_real_del_probe(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H); srv.s = Srv(); threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            par = Path(d) / "race.par"; par.write_text(f"http://127.0.0.1:{srv.server_port}/p/{SECRET}/n/ns/b/bk/o/lease.json"); os.chmod(par, 0o600)
            a = Obj(lease_race_rounds=3, contenders=4, max_minutes=5.0)
            try:
                r = P.lease_race_step(d, a, __import__("time").monotonic(), allow_http_localhost=True, cfg=LeaseConfig(ttl_s=0.6, margin_s=0.2))
            finally: srv.shutdown()
        self.assertTrue(r["exclusividad_demostrada"], r); self.assertEqual((r["rondas_aprobadas"], r["rondas_con_mas_de_un_ganador"]), (3, 0))

    def test_ningun_nombre_global_sin_definir_en_los_scripts_de_la_prueba(self):
        import lease_race, real_factory
        for mod in (P, lease_race, real_factory):
            tab = symtable.symtable(Path(mod.__file__).read_text(), mod.__file__, "exec"); missing = set()
            def walk(t):
                if t.get_type() == "function":
                    for s in t.get_symbols():
                        if s.is_global() and s.is_referenced() and not hasattr(mod, s.get_name()) and not hasattr(builtins, s.get_name()): missing.add(f"{t.get_name()}:{s.get_name()}")
                for c in t.get_children(): walk(c)
            walk(tab); self.assertEqual(missing, set(), f"{mod.__name__}: nombres globales sin definir {sorted(missing)}")


    def test_humo_con_el_interprete_de_la_cli_de_oci(self):
        import subprocess
        cli = Path("/opt/homebrew/Cellar/oci-cli/3.95.0/libexec/bin/python")
        if not cli.exists(): self.skipTest("intérprete de la CLI de OCI no disponible en este equipo")
        r = subprocess.run([str(cli), str(HERE / "smoke_cli_interpreter.py")], capture_output=True, text=True, timeout=120, env={**os.environ, "SUPPRESS_LABEL_WARNING": "True"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-400:]); self.assertTrue(json.loads(r.stdout.strip().splitlines()[-1])["exclusividad_demostrada"])


if __name__ == "__main__":
    unittest.main()
