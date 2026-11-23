"""Subruta detrás de Nginx (NEXOOPS_BASE_PATH): index con recursos prefijados, cookies con la ruta de la subruta y validación estricta del valor."""
import dataclasses
import pytest
from fastapi.testclient import TestClient

from nexoops.app import create_app
from nexoops.mailer import CaptureMailer
from .conftest import EMAIL, PW


def test_index_prefija_recursos_y_publica_base(cfg):
    cfg = dataclasses.replace(cfg, base_path="/nexoops")
    c = TestClient(create_app(cfg, mailer=CaptureMailer()))
    html = c.get("/").text
    assert '<meta name="nexoops-base" content="/nexoops">' in html and '"/nexoops/static/app.js"' in html and '"/static/' not in html


def test_cookie_de_desafio_limitada_a_la_subruta(cfg):
    cfg = dataclasses.replace(cfg, base_path="/nexoops")
    a = create_app(cfg, mailer=CaptureMailer()); a.state.auth.create_user(EMAIL, PW)
    c = TestClient(a, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 200, r.text
    assert "Path=/nexoops" in r.headers.get("set-cookie", "")


@pytest.mark.parametrize("bad", ["nexoops", "/Nexo", "/a/b", "/x\"><script>", "/" + "a" * 40])
def test_base_path_invalido_se_rechaza(cfg, bad):
    with pytest.raises(ValueError):
        dataclasses.replace(cfg, base_path=bad).validate()
