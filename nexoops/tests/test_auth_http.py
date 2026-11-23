"""Integración del login sobre un socket HTTP real, no mediante TestClient."""
import socket
import threading
import time

import httpx
import uvicorn

from nexoops.app import create_app
from .conftest import EMAIL, PW


def test_flujo_http_real_localhost(cfg, mail, clock):
    app = create_app(cfg, mailer=mail, clock=clock)
    app.state.auth.create_user(EMAIL, PW)
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            first = client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
            assert first.status_code == 200 and client.cookies.get("nexoops_challenge")
            assert client.get("/api/overview").status_code == 401
            verified = client.post("/api/auth/verify", json={"code": mail.sent[-1][1]})
            assert verified.status_code == 200
            csrf = verified.json()["csrf"]
            assert client.get("/api/auth/session").status_code == 200
            assert client.get("/api/overview").status_code == 200
            assert client.post("/api/auth/logout").status_code == 403
            assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
