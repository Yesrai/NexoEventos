"""Witness del laboratorio: guarda quién es el escritor, su época y un lease con caducidad, y el ESTADO DE PROTECCIÓN de las reservas confirmadas (estado de protección con compare-and-set
sobre su número de secuencia y su época). Estado persistente en /data.
API de control (puerto 8000): GET /state · POST /set {writer, expect_epoch, ttl} (compare-and-set de escritor; invalida la protección: pasa a 'unknown') · POST /renew {node, epoch}
· POST /prot {expect_seq, mode, primario, epoch} (compare-and-set del estado de protección; solo vale dentro de la época vigente) · POST /prot_verify {seq, primario, epoch}.
Comprobaciones para HAProxy: puertos 8101 (pg-aws) y 8102 (pg-oci) → 200 solo si ese nodo es el escritor Y su lease no ha caducado."""
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATH, LOCK, TTL = "/data/state.json", threading.Lock(), 6.0
NODES = {8101: "pg-aws", 8102: "pg-oci"}
MODES = {"unknown", "unprotected", "protected", "degrading", "degraded", "reprotecting", "promoting"}


def load():
    try:
        s = json.load(open(PATH))
    except Exception:
        s = {"writer": None, "epoch": 0, "expires": 0.0}
    s.setdefault("prot", {"mode": "unknown", "seq": 0, "primario": None, "epoch": s.get("epoch", 0), "verified": 0.0})
    return s


def save(s):
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, PATH)


def view(s):
    p = dict(s["prot"])
    v = p.pop("verified", 0.0)
    p["verified_age_s"] = round(time.time() - v, 2) if v else None
    return {"writer": s["writer"], "epoch": s["epoch"], "lease_remaining_s": round(max(0.0, s["expires"] - time.time()), 2), "prot": p}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        port = self.server.server_port
        with LOCK:
            s = load()
        if port in NODES:
            ok = s["writer"] == NODES[port] and time.time() < s["expires"]
            return self.send(200 if ok else 503, {"writer": ok})
        self.send(200, view(s))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with LOCK:
            s = load()
            if self.path == "/set":
                if body.get("expect_epoch") != s["epoch"]:
                    return self.send(409, {"error": "época obsoleta", **view(s)})
                old = s["prot"]
                s = {"writer": body.get("writer"), "epoch": s["epoch"] + 1, "expires": time.time() + float(body.get("ttl", TTL)),
                     "prot": {"mode": "unknown", "seq": old["seq"] + 1, "primario": body.get("writer"), "epoch": s["epoch"] + 1, "verified": 0.0}}
                save(s); return self.send(200, view(s))
            if self.path == "/renew":
                if s["writer"] != body.get("node") or s["epoch"] != body.get("epoch"):
                    return self.send(409, {"error": "no eres el escritor de esta época", **view(s)})
                s["expires"] = time.time() + float(body.get("ttl", TTL)); save(s); return self.send(200, view(s))
            if self.path == "/prot":
                p = s["prot"]
                if body.get("epoch") != s["epoch"]:
                    return self.send(409, {"error": "época obsoleta", **view(s)})
                if body.get("expect_seq") != p["seq"]:
                    return self.send(409, {"error": "secuencia obsoleta (otro cambio de estado ganó)", **view(s)})
                if body.get("mode") not in MODES:
                    return self.send(400, {"error": "modo desconocido"})
                s["prot"] = {"mode": body["mode"], "seq": p["seq"] + 1, "primario": body.get("primario", p.get("primario")), "epoch": s["epoch"],
                             "verified": time.time() if body["mode"] == "protected" else 0.0}
                save(s); return self.send(200, view(s))
            if self.path == "/prot_verify":
                p = s["prot"]
                if p["mode"] != "protected" or body.get("seq") != p["seq"] or body.get("epoch") != s["epoch"] or body.get("primario") != p.get("primario"):
                    return self.send(409, {"error": "el estado de protección cambió", **view(s)})
                p["verified"] = time.time(); save(s); return self.send(200, view(s))
        self.send(404, {})


for p in (8101, 8102):
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", p), H).serve_forever, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
