"""Humo con el INTÉRPRETE DE LA CLI DE OCI (el que ejecuta T1): importa el probe real (con el SDK real de OCI) y corre su carrera de adquisición contra un servidor PAR LOCAL atómico (If-Match / If-None-Match).
No llama a ninguna nube. Uso:  <python de la CLI de OCI> smoke_cli_interpreter.py   → imprime JSON y sale 0 si la exclusividad se demuestra."""
import hashlib, json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/multicloud/hybrid"))
import oci_par_probe as P  # noqa: E402  (import real: incluye oci, hybrid_par y lease_race)
from app.failover.lease import LeaseConfig  # noqa: E402

OBJ, LOCK = {}, threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def _send(s, code, body=b"", etag=None):
        s.send_response(code); s.send_header("Content-Length", str(len(body)))
        if etag: s.send_header("ETag", etag)
        s.end_headers(); s.wfile.write(body)
    def do_GET(s):
        with LOCK: o = OBJ.get("x")
        s._send(200, o[0], o[1]) if o else s._send(404)
    def do_PUT(s):
        n = int(s.headers.get("Content-Length", "0")); data = s.rfile.read(n); inm, im = s.headers.get("If-None-Match"), s.headers.get("If-Match")
        with LOCK:
            cur = OBJ.get("x")
            if inm == "*" and cur: return s._send(412)
            if im is not None and (not cur or cur[1] != im): return s._send(412)
            et = hashlib.sha256(data + os.urandom(8)).hexdigest()[:16]; OBJ["x"] = (data, et)
        s._send(200, b"", et)


class A:  # argumentos mínimos que usa lease_race_step
    lease_race_rounds, contenders, max_minutes = 3, 4, 5.0


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory() as d:
    par = Path(d) / "race.par"; par.write_text(f"http://127.0.0.1:{srv.server_port}/x"); os.chmod(par, 0o600)
    r = P.lease_race_step(d, A, time.monotonic(), allow_http_localhost=True, cfg=LeaseConfig(ttl_s=0.6, margin_s=0.2))
srv.shutdown()
print(json.dumps({"python": sys.version.split()[0], "exclusividad_demostrada": r["exclusividad_demostrada"], "rondas_aprobadas": r["rondas_aprobadas"], "violaciones": r["rondas_con_mas_de_un_ganador"]}))
sys.exit(0 if r["exclusividad_demostrada"] else 1)
