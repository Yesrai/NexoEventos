"""T2 (ejecutar_t2.py) con DuckDNS y TRES resolvedores UDP SIMULADOS (retraso de propagación configurable). Sin red, sin DuckDNS real."""
import json, os, socket, struct, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import ejecutar_t2 as T2  # noqa: E402

A, B, TOKEN = "93.184.216.34", "151.101.1.69", "tok-abcdef0123456789"


class World:
    """Estado del DNS «verdadero» + visión retrasada por resolvedor."""
    def __init__(self, lag=(0.0, 0.0, 0.0), never=None, ko=False):
        self.ip = A; self.lag = lag; self.never = never; self.ko = ko; self.seen = [A, A, A]; self.calls = []; self.lock = threading.Lock()

    def set_ip(self, ip):
        with self.lock: self.ip = ip
        for i in range(3):
            if self.never == i: continue
            threading.Timer(self.lag[i], lambda i=i, ip=ip: self.seen.__setitem__(i, ip)).start()


def dns_server(world, idx):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0)); s.settimeout(0.2); stop = threading.Event()
    def loop():
        while not stop.is_set():
            try: data, addr = s.recvfrom(512)
            except socket.timeout: continue
            q = data[12:]; ip = world.seen[idx]
            resp = data[:2] + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0) + q + b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton(ip)
            s.sendto(resp, addr)
    threading.Thread(target=loop, daemon=True).start(); return s.getsockname()[1], stop


def api_server(world):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query); world.calls.append(q.get("ip", ["?"])[0])
            ok = (not world.ko) and q.get("token", [""])[0] == TOKEN and q.get("domains", [""])[0] == "nexoeventos-test"
            if ok: world.set_ip(q["ip"][0])
            b = (b"OK\n" + q["ip"][0].encode() + b"\nUPDATED") if ok else b"KO"
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv


@pytest.fixture
def env(tmp_path):
    made = []
    def make(lag=(0.0, 0.0, 0.0), never=None, ko=False, domains=("nexoeventos-test",), min_interval=300):
        w = World(lag, never, ko); ports = []
        for i in range(3):
            p, stop = dns_server(w, i); ports.append(p); made.append(stop)
        api = api_server(w); made.append(type("S", (), {"set": lambda self: api.shutdown()})())
        cfg = {"allowed_domains": list(domains), "allowed_targets": {"a": A, "b": B}, "assumed_ttl_s": 60, "min_interval_s": min_interval, "resolvers": [f"127.0.0.1:{p}" for p in ports], "state_dir": str(tmp_path / "state")}
        cp = tmp_path / "cfg.json"; cp.write_text(json.dumps(cfg)); os.chmod(cp, 0o600); tp = tmp_path / "token"; tp.write_text(TOKEN); os.chmod(tp, 0o600)
        args = ["--config", str(cp), "--token-file", str(tp), "--evidence-root", str(tmp_path / "ev"), "--api-base", f"http://127.0.0.1:{api.server_port}"]
        return w, args
    yield make, tmp_path
    for m in made: m.set()


def go(args, auth=True, monkeypatch=None):
    return T2.main((["--autorizo", T2.FRASE] if auth else []) + args)


def result(tmp):
    d = next((tmp / "ev").iterdir()); return d, json.loads((d / "resultado.json").read_text())


def test_modo_plan_no_cambia_nada_y_muestra_la_frase(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    rc = go(args, auth=False); out = capsys.readouterr().out
    assert rc == 0 and '"resultado": "LISTO"' in out and T2.FRASE in out and w.calls == [] and not (tmp / "ev").exists()


def test_plan_no_listo_si_el_dominio_no_parte_de_A(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(); w.seen = [B, B, B]; monkeypatch.setenv("NEXO_DNS_TEST", "1")
    assert go(args, auth=False) == 2 and "NO LISTO" in capsys.readouterr().out


def test_ejecucion_completa_pass_con_reversion_y_sin_token_en_la_evidencia(env, monkeypatch):
    make, tmp = env; w, args = make(lag=(0.2, 0.6, 1.2)); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    rc = go(args); d, res = result(tmp)
    assert rc == 0 and res["veredicto"] == "PASS", [c for c in res["criterios"] if c["resultado"] != "CUMPLE"]
    assert w.ip == A and w.seen == [A, A, A]                      # DNS final = inicial
    assert w.calls == [B, A]                                     # SOLO dos llamadas al proveedor: apply y rollback (el segundo apply fue rechazado antes de llamar)
    assert not any(TOKEN in p.read_text(errors="ignore") for p in d.rglob("*") if p.is_file())
    vals = {c["id"]: c["valor"] for c in res["criterios"]}
    assert vals["segundo_cambio_rechazado"] is True and vals["rollback_correcto"] is True and 0 < vals["propagacion_apply_s"] < 180 and vals["auditoria_dns_switch_registrada"] is True
    assert {"dns_aplicado", "b_verificado", "dns_revertido", "a_verificado"} <= set(res["marcas"])


def test_proveedor_rechaza_KO_no_hay_cambio_ni_reversion_innecesaria(env, monkeypatch):
    make, tmp = env; w, args = make(ko=True); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    rc = go(args); d, res = result(tmp)
    assert rc == 1 and res["veredicto"] != "PASS" and w.ip == A and w.seen == [A, A, A]
    ev = (d / "events.jsonl").read_text(); assert "sin_cambio_que_revertir" in ev


def test_propagacion_incompleta_revierte_a_A_y_no_es_pass(env, monkeypatch):
    make, tmp = env; w, args = make(never=2); monkeypatch.setenv("NEXO_DNS_TEST", "1")      # el tercer resolvedor NUNCA ve el cambio
    rc = go(args + ["--propagation-timeout", "3", "--poll-interval", "0.5"]); d, res = result(tmp)
    assert rc == 1 and res["veredicto"] != "PASS"
    assert w.ip == A and w.calls == [B, A]                         # se aplicó B, se detectó INCOMPLETO y se revirtió a A
    ev = (d / "events.jsonl").read_text(); assert "interrupcion" in ev and "dns_revertido" in ev
    vals = {c["id"]: c["valor"] for c in res["criterios"]}; assert vals["rollback_correcto"] is True and vals["propagacion_apply_s"] is None


def test_si_la_reversion_tambien_falla_se_avisa_y_no_se_declara_correcta(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    orig = T2.Runner.sh
    def sh(self, label, cmd, change=False, extra=()):
        if cmd == "rollback": return {"label": label, "cmd": cmd, "rc": 4, "out": "", "err": "RECHAZADO: simulado", "t0": "x", "t1": "y"}
        return orig(self, label, cmd, change, extra)
    monkeypatch.setattr(T2.Runner, "sh", sh)
    rc = go(args + ["--propagation-timeout", "3", "--poll-interval", "0.5"]); d, res = result(tmp)
    assert rc == 1 and res["veredicto"] != "PASS"
    assert "REVERSIÓN FALLIDA" in capsys.readouterr().err
    assert w.ip == B                                                   # el DNS quedó en B: el expediente y el aviso permiten restaurar A a mano
    vals = {c["id"]: c["valor"] for c in res["criterios"]}; assert vals.get("rollback_correcto") is not True


def test_produccion_en_la_lista_blanca_aborta_sin_cambiar_nada(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(domains=("nexoeventos-test", "nexoeventos-demo")); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    rc = go(args); assert rc == 2 and "SOLO el subdominio de pruebas" in capsys.readouterr().err and w.calls == [] and not (tmp / "ev").exists()


def test_frase_incorrecta_no_ejecuta(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    assert T2.main(["--autorizo", "si"] + args) == 0 and w.calls == [] and not (tmp / "ev").exists()


def test_plan_no_listo_si_el_tls_del_proveedor_no_se_puede_verificar(env, monkeypatch, capsys):
    make, tmp = env; w, args = make(); monkeypatch.setenv("NEXO_DNS_TEST", "1")
    monkeypatch.setattr(T2.Runner, "tls_check", lambda self: {"ok": False, "detalle": "SSLCertVerificationError simulado"})
    assert go(args, auth=False) == 2 and "NO LISTO" in capsys.readouterr().out and w.calls == []
