"""T4 — recolector de estado: sondas reales (HTTPS local con certificado FIJADO), independencia entre destinos, TLS siempre verificado, instantánea atómica y panel sin AWS."""
import http.server
import json
import os
import socket
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from ops_center import collector as C
from ops_center.settings import Settings


def _cert(tmp):
    crt, key = tmp / "c.crt", tmp / "c.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
    return crt, key


class H(http.server.BaseHTTPRequestHandler):
    routes = {"/livez": (200, b'{"status":"ok"}'), "/ready": (200, b'{"status":"ready"}'), "/api/events": (200, b'[{"id":1},{"id":2}]'), "/ops/healthz": (200, b"{}"), "/healthz": (200, b"{}")}
    def do_GET(self):
        code, body = self.routes.get(self.path, (404, b"{}")); self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


@pytest.fixture
def server(tmp_path):
    crt, key = _cert(tmp_path); ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, key)
    class Srv(http.server.ThreadingHTTPServer): pass
    srv = Srv(("127.0.0.1", 0), type("HH", (H,), {"routes": dict(H.routes)})); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"base": f"https://localhost:{srv.server_address[1]}", "cafile": str(crt), "srv": srv, "routes": srv.RequestHandlerClass.routes}
    srv.shutdown()


def settings(tmp): return Settings.from_env({"OPS_CENTER_STATE_DIR": str(tmp / "st")})


def test_destino_sano_con_certificado_fijado_es_ok(server, tmp_path):
    r = C.probe_target({"base": server["base"], "cafile": server["cafile"]})
    assert r["estado"] == "OK" and r["origen"] == "cloud_verificado" and [s["code"] for s in r["sondas"]] == [200, 200, 200] and r["sondas"][2]["eventos"] == 2


def test_certificado_no_fijado_se_rechaza_nunca_se_desactiva_la_verificacion(server):
    r = C.probe_target({"base": server["base"]})                    # sin cafile: el autofirmado NO es de confianza
    assert r["estado"] == "ERROR" and all(s["code"] == 0 and s["error"] for s in r["sondas"])
    code = Path(C.__file__).read_text().split('"""', 2)[2]                       # sin el docstring que menciona la prohibición
    assert "verify=False" not in code and "CERT_NONE" not in code and "_create_unverified_context" not in code


def test_http_plano_y_destino_inalcanzable_son_error_no_ok(server):
    assert C.probe_http("http://localhost:1", "/livez")["code"] == 0
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    assert C.probe_target({"base": f"https://localhost:{p}", "cafile": server["cafile"]})["estado"] == "ERROR"


def test_degradacion_parcial_y_standby(server):
    server["routes"]["/ready"] = (503, b"{}")
    r = C.probe_target({"base": server["base"], "cafile": server["cafile"]}); assert r["estado"] == "ADVERTENCIA" and "/ready" in r["detalle"]
    assert C.classify([{"path": "/livez", "code": 0, "ms": 5, "error": "URLError"}], "standby")[0] == "ADVERTENCIA"      # OCI en espera: no responder es lo esperado
    assert C.classify([{"path": "/livez", "code": 0, "ms": 5, "error": "URLError"}], "activo")[0] == "ERROR"             # AWS activo que no responde: error
    assert C.classify([{"path": "/livez", "code": 200, "ms": 4000}])[0] == "ADVERTENCIA"


def test_sin_destino_configurado_es_no_verificado_nunca_ok():
    assert C.probe_target({})["estado"] == "No verificado"


def test_caida_de_aws_no_impide_oci_ni_azure_ni_escribir_la_instantanea(server, tmp_path):
    st = settings(tmp_path)
    t = {"aws": {"base": "https://aws.invalid", "esperado": "activo"}, "oci": {"base": server["base"], "cafile": server["cafile"], "esperado": "standby"}, "azure": {"self_url": server["base"], "self_cafile": server["cafile"], "witness_url": server["base"], "witness_cafile": server["cafile"]}}
    snap = C.collect(st, t, free_gb=50); C.write_snapshot(st, snap)
    assert snap["clouds"]["aws"]["estado"] == "ERROR" and snap["clouds"]["oci"]["estado"] == "OK" and snap["clouds"]["azure"] == {"estado": "OK", "origen": "local", "detalle": "ok: panel, disco 50 GB, testigo"}
    # el panel lee la instantánea y muestra las tres nubes con origen y hora
    from ops_center.status import cloud_status
    cs = cloud_status(st); assert cs["observado"] == snap["observed_at"] and cs["nubes"]["aws"]["estado"] == "ERROR" and cs["nubes"]["oci"]["origen"] == "cloud_verificado"
    mode = oct(os.stat(Path(st.state_dir) / "status/cloud-status.json").st_mode)[-3:]; assert mode == "600"


def test_un_fallo_interno_en_un_destino_no_tumba_el_ciclo(tmp_path):
    def boom(base, path, **k): raise RuntimeError("x")
    snap = C.collect(settings(tmp_path), {"aws": {"base": "https://a.example"}, "oci": {"base": "https://o.example"}}, fetch=boom, free_gb=50)
    assert snap["clouds"]["aws"]["estado"] == "ERROR" and "RuntimeError" in snap["clouds"]["aws"]["detalle"] and snap["clouds"]["azure"]["estado"] == "OK"


def test_historial_es_append_y_la_instantanea_se_reemplaza(tmp_path):
    st = settings(tmp_path)
    for _ in range(3): C.write_snapshot(st, C.collect(st, {}, free_gb=50))
    h = (Path(st.state_dir) / "status/probe-history.jsonl").read_text().splitlines(); assert len(h) == 3 and all(json.loads(l)["azure"] == "OK" for l in h)
    assert not list((Path(st.state_dir) / "status").glob(".tmp-*"))


def test_disco_bajo_o_testigo_caido_es_error_de_azure(server, tmp_path):
    st = settings(tmp_path)
    assert C.self_check(st, {}, free_gb=1)["estado"] == "ERROR"
    server["routes"].pop("/healthz"); r = C.self_check(st, {"witness_url": server["base"], "witness_cafile": server["cafile"]}, free_gb=50); assert r["estado"] == "ERROR" and "testigo" in r["detalle"]


def test_targets_validados(tmp_path):
    p = tmp_path / "t.json"
    for bad in ({"gcp": {}}, {"aws": {"base": "http://x"}}, {"oci": {"esperado": "otro"}}):
        p.write_text(json.dumps(bad)); 
        with pytest.raises(ValueError): C.load_targets(p)
    p.write_text(json.dumps({"aws": {"base": "https://x", "esperado": "activo"}})); assert "aws" in C.load_targets(p)


def test_cli_collect_una_vez(tmp_path):
    from ops_center.cli import main
    import io
    t = tmp_path / "t.json"; t.write_text(json.dumps({"azure": {}})); out = io.StringIO()
    rc = main(["collect", "--targets", str(t)], env={"OPS_CENTER_STATE_DIR": str(tmp_path / "st"), "OPS_CENTER_IDENTITIES_FILE": str(tmp_path / "x.json")}, out=out)
    assert rc == 0 and json.loads(out.getvalue())["aws"] == "No verificado" and (tmp_path / "st/status/cloud-status.json").exists()


def test_modo_alcanzabilidad_oci_en_espera_es_advertencia_nunca_ok(server):
    r = C.probe_target({"base": server["base"], "cafile": server["cafile"], "modo": "alcanzabilidad", "path": "/no-existe"})        # el servidor responde 404: hay alcanzabilidad, no aplicación
    assert r["estado"] == "ADVERTENCIA" and r["origen"] == "cloud_verificado" and "NO hay aplicación activa" in r["detalle"] and len(r["sondas"]) == 1
    r2 = C.probe_target({"base": server["base"], "cafile": server["cafile"], "modo": "alcanzabilidad", "path": "/livez"}); assert r2["estado"] == "ADVERTENCIA"      # incluso con 200 sigue siendo «en espera»


def test_modo_alcanzabilidad_sin_respuesta_o_sin_tls_valido_es_error(server):
    assert C.probe_target({"base": server["base"], "modo": "alcanzabilidad"})["estado"] == "ERROR"                # sin certificado fijado: autofirmado rechazado
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    assert C.probe_target({"base": f"https://localhost:{p}", "cafile": server["cafile"], "modo": "alcanzabilidad"})["estado"] == "ERROR"


def test_modo_invalido_se_rechaza(tmp_path):
    p = tmp_path / "t.json"; p.write_text(json.dumps({"oci": {"base": "https://x", "modo": "otro"}}))
    with pytest.raises(ValueError): C.load_targets(p)


def test_http_solo_a_loopback_nunca_a_destinos_remotos(tmp_path):
    assert C.probe_http("http://example.com", "/livez")["error"] == "solo https" and C.probe_http("http://10.0.0.5:8750", "/healthz")["error"] == "solo https"
    assert C.probe_http("http://127.0.0.1:1", "/healthz")["error"] != "solo https"            # loopback permitido (aquí falla por conexión rechazada)
    p = tmp_path / "t.json"; p.write_text(json.dumps({"azure": {"self_url": "http://example.com"}}))
    with pytest.raises(ValueError): C.load_targets(p)
    p.write_text(json.dumps({"azure": {"self_url": "http://127.0.0.1:8750", "self_path": "/healthz", "witness_url": "http://127.0.0.1:8760"}})); assert "azure" in C.load_targets(p)


def test_verify_as_valida_el_certificado_contra_el_dominio_del_certificado_no_contra_el_dns_del_alb(server, tmp_path):
    base_ip = server["base"].replace("localhost", "127.0.0.1")                 # el «DNS del ALB» (aquí una IP)
    ok = C.probe_target({"base": base_ip, "cafile": server["cafile"], "verify_as": "localhost"})             # con verify_as = dominio del certificado se valida y responde
    assert ok["estado"] == "OK" and [s["code"] for s in ok["sondas"]] == [200, 200, 200] and ok["sondas"][2]["eventos"] == 2
    mal = C.probe_target({"base": base_ip, "cafile": server["cafile"], "verify_as": "otro.example"})            # un nombre que NO está en el certificado sigue fallando
    assert mal["estado"] == "ERROR" and all(s["code"] == 0 for s in mal["sondas"])
    p = tmp_path / "t.json"; p.write_text(json.dumps({"aws": {"base": "https://x", "verify_as": "a b;c"}}))
    with pytest.raises(ValueError): C.load_targets(p)


def test_verify_as_no_desactiva_la_verificacion_ni_acepta_http():
    code = Path(C.__file__).read_text().split('"""', 2)[2]
    assert "CERT_NONE" not in code and "_create_unverified_context" not in code and "check_hostname = False" not in code
    assert C.probe_http("http://example.com", "/livez", verify_as="x.example")["error"] == "solo https"
