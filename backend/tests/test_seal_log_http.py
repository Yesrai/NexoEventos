"""ParLogStore contra un servidor HTTP local que imita un PAR de PREFIJO de OCI (listado, lectura y creación con If-None-Match; con o sin retención WORM)."""
import http.server, json, os, threading
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.failover.lease import Ed25519Auth
from app.failover.seal_log import LogGuard, MemRatchet, ParLogStore, append, _name
from app.failover.store import PreconditionFailed, StoreError

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
PREFIX = "/p/TOKEN/n/ns/b/bk/o/"


def servidor(worm):
    objs = {}
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _n(self): return self.path[len(PREFIX):] if self.path.startswith(PREFIX) else None
        def do_GET(self):
            n = self._n()
            if n is None: return self._r(404)
            if n == "":
                return self._r(200, json.dumps({"objects": [{"name": k} for k in sorted(objs)]}).encode())
            self._r(200, objs[n]) if n in objs else self._r(404)
        def do_PUT(self):
            n = self._n(); body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if n is None: return self._r(404)
            if n in objs and (self.headers.get("If-None-Match") == "*" or worm): return self._r(412)
            objs[n] = body; self._r(200, b"", {"ETag": '"e1"'})
        def _r(self, code, body=b"", h=None):
            self.send_response(code); [self.send_header(k, v) for k, v in (h or {}).items()]; self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv, objs


@pytest.fixture
def auth():
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator")}; pubs = {n: [pub(v)] for n, v in k.items()}
    return {n: Ed25519Auth(n, raw(k[n]), pubs) for n in k}


def store(srv, tmp_path):
    f = tmp_path / "par.url"; f.write_text(f"http://127.0.0.1:{srv.server_port}{PREFIX}seal-log/"); os.chmod(f, 0o600)
    return ParLogStore(str(f), allow_create=True, allow_http_localhost=True)


@pytest.mark.parametrize("worm", [True, False])
def test_ciclo_completo_por_http_y_ataques(auth, tmp_path, worm):
    srv, objs = servidor(worm)
    try:
        log = store(srv, tmp_path); g = LogGuard(log, auth["aws"], MemRatchet())
        append(log, auth["operator"], "operator", "unsealed", 0); assert g(0)[0]
        append(log, auth["oci"], "oci", "sealed", 3); ok, why = g(None); assert not ok and "SELLADO" in why
        assert log.names() == [_name(1), _name(2)]
        with pytest.raises(PreconditionFailed): log.create(_name(1), b"x")                 # crear sobre una entrada existente: 412
        viejo = objs[_name(1)]
        if worm:
            with pytest.raises(Exception):                                                   # sobrescritura ciega SIN condición: la retención la rechaza
                log.put = None; import urllib.request; urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{srv.server_port}{PREFIX}{_name(2)}", data=viejo, method="PUT"))
            assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]
        else:
            import urllib.request; urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{srv.server_port}{PREFIX}{_name(2)}", data=viejo, method="PUT"))   # sin retención: se reemplaza por el «unsealed» antiguo
            ok, why = LogGuard(log, auth["aws"], MemRatchet())(None); assert not ok and "inválida" in why     # …pero la CADENA lo delata (seq 1 en la posición 2)
        with pytest.raises(StoreError): log.read("otro/prefijo.json")
    finally:
        srv.shutdown()


def test_url_sin_prefijo_o_con_permisos_abiertos_se_rechaza(tmp_path):
    f = tmp_path / "u"; f.write_text("http://127.0.0.1:1/p/T/n/ns/b/bk/o/"); os.chmod(f, 0o600)
    with pytest.raises(StoreError): ParLogStore(str(f), allow_http_localhost=True)            # sin prefijo
    f.write_text("http://127.0.0.1:1/p/T/n/ns/b/bk/o/seal-log/"); os.chmod(f, 0o644)
    with pytest.raises(StoreError): ParLogStore(str(f), allow_http_localhost=True)            # permisos abiertos


def test_par_log_store_es_solo_lector_por_defecto(tmp_path):
    srv, objs = servidor(True)
    try:
        f = tmp_path / "par.url"; f.write_text(f"http://127.0.0.1:{srv.server_port}{PREFIX}seal-log/"); os.chmod(f, 0o600)
        lector = ParLogStore(str(f), allow_http_localhost=True)
        with pytest.raises(StoreError, match="SOLO LECTURA"): lector.create(_name(1), b"x")
        assert objs == {} and lector.names() == []                                                         # no escribió nada; listar y leer sí funcionan
    finally:
        srv.shutdown()


def test_formato_real_de_oci_url_del_par_acaba_en_o_y_el_prefijo_se_indica_aparte(tmp_path):
    srv, objs = servidor(True)
    try:
        log = ParLogStore(str(_f(tmp_path, f"http://127.0.0.1:{srv.server_port}{PREFIX}")), allow_create=True, prefix="seal-log/", allow_http_localhost=True)
        log.create("seal-log/0000000001.json", b"x"); assert log.names() == ["seal-log/0000000001.json"] and log.read("seal-log/0000000001.json") == b"x"
        with pytest.raises(StoreError): ParLogStore(str(_f(tmp_path, f"http://127.0.0.1:{srv.server_port}{PREFIX}")), allow_http_localhost=True)      # sin prefijo en ninguna parte: se rechaza
    finally:
        srv.shutdown()


def _f(tmp_path, url):
    f = tmp_path / "u2"; f.write_text(url); os.chmod(f, 0o600); return f
