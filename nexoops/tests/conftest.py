from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from nexoops import mailer as M
from nexoops.app import create_app
from nexoops.config import Config

EMAIL, PW = "ti@nexoeventos.test", "una-contraseña-larga-123"


class Clock:
    def __init__(self): self.t = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    def __call__(self): return self.t
    def advance(self, **kw): self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path / "d", ops_state_dir=tmp_path / "ops", env="dev", cookie_secure=False, otp_secret=b"s" * 40, mail_mode="outbox")


@pytest.fixture
def mail():
    return M.CaptureMailer()


@pytest.fixture
def app(cfg, mail, clock):
    a = create_app(cfg, mailer=mail, clock=clock)
    a.state.auth.create_user(EMAIL, PW)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://testserver")


def login(client, mail, password=PW):
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": password})
    return r, (mail.sent[-1][1] if mail.sent else None)


@pytest.fixture
def authed(client, mail):
    r, code = login(client, mail)
    assert r.status_code == 200
    v = client.post("/api/auth/verify", json={"code": code})
    assert v.status_code == 200
    client.headers["X-CSRF-Token"] = v.json()["csrf"]
    return client
