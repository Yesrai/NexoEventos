"""Simulador LOCAL de ALB + Auto Scaling para probar la arquitectura de AWS V2 SIN nube: instancias REALES de la API (uvicorn, la misma `app.main:app`) detrás de un balanceador que imita
el target group de `infra/aws-v2` (algoritmo least_outstanding_requests, health check /health a intervalo fijo con umbrales healthy/unhealthy, sin afinidad de sesión) y de un «ASG» que
mantiene la capacidad deseada repartida en zonas y SUSTITUYE las instancias no sanas.

Límites honestos: no es AWS (sin latencias de red reales, sin las cuotas ni el calentamiento del ALB, tiempos de health check acelerados); un objetivo muerto que el balanceador aún no ha marcado como
no sano devuelve 502 (como el ALB real) durante la ventana de detección: se MIDE, no se oculta. No sustituye la prueba real de ALB + EC2."""
from __future__ import annotations

import http.client
import http.server
import itertools
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length"}


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Instance:
    """Una «EC2»: un proceso uvicorn con la API real y una zona de disponibilidad etiquetada."""
    _ids = itertools.count(1)

    def __init__(self, zone: str, env: dict, python: str | None = None):
        self.id, self.zone, self.port = f"i-{next(self._ids):04d}", zone, free_port()
        self.state = "initial"            # initial → healthy → unhealthy → draining
        self.ok, self.bad, self.outstanding, self.served, self.born = 0, 0, 0, 0, time.monotonic()
        self.unhealthy_since: float | None = None
        e = {**os.environ, **env, "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen([python or sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port), "--no-access-log", "--log-level", "warning"],
                                     cwd=BACKEND, env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self, sig=signal.SIGKILL) -> None:
        if self.alive(): self.proc.send_signal(sig)

    def freeze(self) -> None:
        if self.alive(): self.proc.send_signal(signal.SIGSTOP)       # proceso colgado: acepta conexiones (cola del kernel) pero no responde

    def terminate(self) -> None:
        self.kill(signal.SIGTERM)
        try: self.proc.wait(5)
        except subprocess.TimeoutExpired: self.kill(); self.proc.wait(5)


class Alb:
    """Balanceador HTTP + health checks + ASG en un solo objeto. `target` imita `aws_lb_target_group.web`: interval, timeout, healthy/unhealthy_threshold; `health_path` es el /livez de producción (Nginx → /health)."""

    def __init__(self, env: dict, zones=("a", "b"), desired=2, max_size=3, interval=0.4, timeout=0.6, healthy=2, unhealthy=2, grace=1.5, health_path="/health", python=None):
        self.env, self.zones, self.desired, self.max_size, self.python = env, list(zones), desired, max_size, python
        self.interval, self.timeout, self.healthy, self.unhealthy, self.grace, self.health_path = interval, timeout, healthy, unhealthy, grace, health_path
        self.lock = threading.RLock(); self.instances: list[Instance] = []; self.history: list[tuple[float, str, str]] = []
        self.stats = {"2xx": 0, "4xx": 0, "5xx": 0, "502": 0}; self._stop = threading.Event(); self.t0 = time.monotonic()
        self.replacements = 0; self.asg_enabled = True
        self.port = free_port()
        alb = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def _go(self):
                n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
                status, hdrs, data = alb.route(self.command, self.path, {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}, body)
                self.send_response(status)
                for k, v in hdrs:
                    if k.lower() not in HOP: self.send_header(k, v)
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _go

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), H); self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._health_loop, daemon=True).start()
        for i in range(desired): self.launch()

    @property
    def url(self) -> str: return f"http://127.0.0.1:{self.port}"

    def log(self, what: str, who: str = "") -> None:
        self.history.append((round(time.monotonic() - self.t0, 2), what, who))

    # --- ASG
    def launch(self) -> Instance:
        with self.lock:
            counts = {z: sum(1 for i in self.instances if i.zone == z and i.state != "draining") for z in self.zones}
            zone = min(counts, key=lambda z: (counts[z], z))                       # reparto equilibrado entre zonas
            inst = Instance(zone, self.env, self.python); self.instances.append(inst); self.log("launch", f"{inst.id}@{zone}"); return inst

    def healthy_targets(self) -> list[Instance]:
        with self.lock: return [i for i in self.instances if i.state == "healthy"]

    def wait_healthy(self, n: int, timeout_s: float = 60.0) -> None:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if len(self.healthy_targets()) >= n: return
            time.sleep(0.1)
        raise TimeoutError(f"no hay {n} instancias sanas: {[(i.id, i.state) for i in self.instances]}")

    # --- health checks (hilo)
    def _probe(self, inst: Instance) -> bool:
        try:
            c = http.client.HTTPConnection("127.0.0.1", inst.port, timeout=self.timeout); c.request("GET", self.health_path); ok = c.getresponse().status == 200; c.close(); return ok
        except Exception: return False

    def _health_loop(self) -> None:
        while not self._stop.wait(self.interval):
            with self.lock: snapshot = [i for i in self.instances if i.state != "draining"]
            for inst in snapshot:
                if self._stop.is_set(): return
                ok = self._probe(inst)
                with self.lock:
                    if ok: inst.ok, inst.bad = inst.ok + 1, 0
                    else: inst.bad, inst.ok = inst.bad + 1, 0
                    if inst.state in ("initial", "unhealthy") and inst.ok >= self.healthy:
                        inst.state, inst.unhealthy_since = "healthy", None; self.log("healthy", inst.id)
                    elif inst.state == "healthy" and inst.bad >= self.unhealthy:
                        inst.state, inst.unhealthy_since = "unhealthy", time.monotonic(); self.log("unhealthy", inst.id)
            self._asg_step()

    def _asg_step(self) -> None:
        """Health check de tipo ELB: una instancia no sana más allá del periodo de gracia se TERMINA y se lanza otra (la capacidad deseada se mantiene)."""
        if not self.asg_enabled: return
        with self.lock:
            now = time.monotonic()
            for i in list(self.instances):
                if i.state in ("unhealthy",) and i.unhealthy_since and now - i.unhealthy_since >= self.grace and now - i.born >= self.grace:
                    i.state = "draining"; self.log("terminate", i.id); self.replacements += 1
                    threading.Thread(target=i.terminate, daemon=True).start()
            live = [i for i in self.instances if i.state != "draining"]
            for _ in range(max(0, self.desired - len(live))): self.launch()
            self.instances = [i for i in self.instances if i.state != "draining" or i.alive()]

    # --- enrutamiento: least_outstanding_requests entre los sanos
    def route(self, method, path, headers, body):
        with self.lock:
            cands = [i for i in self.instances if i.state == "healthy"]
            if not cands:
                self.stats["5xx"] += 1; return 503, [("Content-Type", "text/plain")], b"no healthy targets"
            inst = min(cands, key=lambda i: (i.outstanding, i.served)); inst.outstanding += 1
        try:
            c = http.client.HTTPConnection("127.0.0.1", inst.port, timeout=15)
            c.request(method, path, body=body, headers=headers); r = c.getresponse(); data = r.read(); out = (r.status, r.getheaders(), data); c.close()
        except Exception:
            with self.lock: self.stats["5xx"] += 1; self.stats["502"] += 1
            return 502, [("Content-Type", "text/plain")], b"bad gateway"
        finally:
            with self.lock: inst.outstanding -= 1
        with self.lock:
            inst.served += 1; self.stats["2xx" if out[0] < 400 else "4xx" if out[0] < 500 else "5xx"] += 1
        return out

    def close(self) -> None:
        self._stop.set(); self.server.shutdown()
        for i in list(self.instances): i.terminate()
