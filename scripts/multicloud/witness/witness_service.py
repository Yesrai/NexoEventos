#!/usr/bin/env python3
"""SERVICIO del testigo de frescura independiente (apto para Cloud Run: escucha en $PORT, sin estado local; el historial vive en un bucket de solo adición con retención y la firma en Cloud KMS).
Endpoints:  GET /healthz · GET /attest?nonce=<hex 16–64> · POST /report {reporter, payload, sig} → recibo firmado · GET /entry?seq=N.
Configuración por entorno: WITNESS_STORE=file:<ruta> | gcs:<bucket>  ·  WITNESS_SIGNER=local-ecdsa:<archivo 0600> | kms:<CryptoKeyVersion>  ·  WITNESS_REPORTERS_FILE=<JSON {informante: [clave pública Ed25519 base64]}>
Esta versión se ejecuta en LOCAL (pruebas); NO se ha desplegado. El servicio NO recibe credenciales de AWS ni de OCI: solo claves PÚBLICAS de los informantes."""
from __future__ import annotations

import base64
import http.server
import json
import os
import re
import sys
import threading
import urllib.parse
from pathlib import Path

_parents = Path(__file__).resolve().parents
if len(_parents) > 3: sys.path.insert(0, str(_parents[3] / "backend"))      # en el repositorio; en la imagen se usa PYTHONPATH=/srv/backend
from app.failover.lease import Ed25519Auth  # noqa: E402
from app.failover.store import StoreError, StoreUnavailable  # noqa: E402
from app.failover.witness import Witness  # noqa: E402

NONCE = re.compile(r"^[0-9a-f]{16,64}$")
MAX_BODY = 8192


class Invokers:
    """Control de acceso a nivel de servicio (defensa en profundidad; en Cloud Run se añade IAM de invocador con `--no-allow-unauthenticated`). Fichero 0600: {"tokens": [{"id", "sha256", "scopes": [attest|report|entry]}]}.
    Solo se guarda el SHA-256 de cada token. La SEGURIDAD de fondo no depende de esto: los informes van firmados por informantes anclados y las atestaciones las firma el testigo."""
    def __init__(self, tokens: list[dict]): self.tokens = tokens
    @staticmethod
    def from_file(path):
        import stat
        p = Path(path)
        if p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO): raise SystemExit("WITNESS_INVOKER_TOKENS_FILE debe tener permisos 0600")
        return Invokers(json.loads(p.read_text())["tokens"])
    def check(self, header: str | None, scope: str) -> int:
        import hashlib, hmac
        if not header or not header.startswith("Bearer "): return 401                                       # anónimo
        h = hashlib.sha256(header[7:].encode()).hexdigest()
        for t in self.tokens:
            if hmac.compare_digest(h, t["sha256"]): return 200 if scope in t["scopes"] else 403             # identidad válida sin ese alcance
        return 403                                                                                             # identidad desconocida


def make_handler(witness: Witness, invokers: "Invokers | None" = None):
    lock = threading.Lock()                                                  # un informe a la vez DENTRO del proceso; entre instancias manda la creación condicional del almacén

    class H(http.server.BaseHTTPRequestHandler):
        server_version = "nexo-witness"
        def log_message(self, *a): pass
        def _send(self, code, obj):
            b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
            try:
                if u.path == "/healthz": return self._send(200, {"ok": True})
                scope = "attest" if u.path.endswith("/attest") else ("entry" if u.path.endswith("/entry") else None)
                if scope and invokers is not None:
                    c = invokers.check(self.headers.get("Authorization"), scope)
                    if c != 200: return self._send(c, {"error": "no autorizado"})
                if u.path.endswith("/attest"):
                    n = (q.get("nonce") or [""])[0]
                    if not NONCE.match(n): return self._send(400, {"error": "nonce inválido"})
                    with lock: return self._send(200, witness.attest(n))
                if u.path.endswith("/entry"):
                    seq = int((q.get("seq") or ["0"])[0]); e = witness.entry(seq)
                    return self._send(200 if e else 404, e or {"error": "no existe"})
                return self._send(404, {"error": "ruta"})
            except (StoreUnavailable, StoreError): return self._send(503, {"error": "no disponible"})
            except ValueError: return self._send(400, {"error": "petición inválida"})
        def do_POST(self):
            if not self.path.endswith("/report"): return self._send(404, {"error": "ruta"})
            if invokers is not None:
                c = invokers.check(self.headers.get("Authorization"), "report")
                if c != 200: return self._send(c, {"error": "no autorizado"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n <= 0 or n > MAX_BODY: return self._send(413, {"error": "cuerpo fuera de límites"})
                d = json.loads(self.rfile.read(n)); rep, payload, sig = str(d["reporter"]), d["payload"], str(d["sig"])
                if not isinstance(payload, dict): raise ValueError
                with lock: r = witness.report_with_receipt(rep, payload, sig)
                return self._send(200 if r["ok"] else 409, r)
            except (StoreUnavailable, StoreError): return self._send(503, {"error": "no disponible"})
            except (ValueError, KeyError, TypeError): return self._send(400, {"error": "informe ilegible"})
    return H


def serve(witness: Witness, host="127.0.0.1", port=0, invokers=None):
    srv = http.server.ThreadingHTTPServer((host, port), make_handler(witness, invokers)); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv


def assert_key_separation(witness_pub: bytes, reporters: dict) -> None:
    """La clave de firma del TESTIGO (KMS) no puede coincidir con la de ningún informante: el testigo no puede hacerse pasar por un informante ni al revés."""
    for who, keys in reporters.items():
        for k in keys:
            if bytes(k) == bytes(witness_pub): raise SystemExit(f"la clave del testigo coincide con la del informante «{who}»: deben ser claves DISTINTAS")


def build_from_env(env=None):
    env = os.environ if env is None else env
    st = env.get("WITNESS_STORE", ""); sg = env.get("WITNESS_SIGNER", "")
    if st.startswith("file:"): store = st[5:]
    elif st.startswith("gcs:"):
        from app.failover.witness import GcsAppendStore; store = GcsAppendStore(st[4:])
    else: raise SystemExit("WITNESS_STORE debe ser file:<ruta> o gcs:<bucket>")
    raw = json.loads(Path(env["WITNESS_REPORTERS_FILE"]).read_text()); rep = {k: [base64.b64decode(x) for x in v] for k, v in raw.items()}
    if sg.startswith("kms:"):
        from app.failover.witness import GcpKmsSigner; signer = GcpKmsSigner(sg[4:]); pub = None
    elif sg.startswith("local-ecdsa:") and env.get("WITNESS_ALLOW_LOCAL_SIGNER") == "1":              # SOLO desarrollo/contenedor local: la clave vive en un archivo 0600; en Cloud Run se usa kms:
        from app.failover.witness import LocalEcdsaFileSigner; signer = LocalEcdsaFileSigner(sg[len("local-ecdsa:"):]); pub = signer.public_der()
    else: raise SystemExit("WITNESS_SIGNER debe ser kms:<CryptoKeyVersion> (local-ecdsa:<archivo> solo con WITNESS_ALLOW_LOCAL_SIGNER=1, para pruebas)")
    if pub is not None: assert_key_separation(pub, rep)
    reporters = Ed25519Auth("witness", b"\x01" * 32, rep)
    return Witness(store, signer, reporters)


def invokers_from_env(env=None):
    env = os.environ if env is None else env
    f = env.get("WITNESS_INVOKER_TOKENS_FILE")
    if f: return Invokers.from_file(f)
    if env.get("WITNESS_REQUIRE_INVOKER", "1") == "1": raise SystemExit("falta WITNESS_INVOKER_TOKENS_FILE (o WITNESS_REQUIRE_INVOKER=0 solo con IAM de invocador delante)")
    return None


if __name__ == "__main__":
    w = build_from_env(); srv = http.server.ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), make_handler(w, invokers_from_env())); srv.serve_forever()
