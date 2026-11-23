from nexoops import auth as A
from .conftest import EMAIL, PW, login


def test_flujo_completo_correcto(client, mail):
    r, code = login(client, mail)
    assert r.status_code == 200 and r.json()["step"] == "otp" and len(code) == 6 and code.isdigit()
    assert "HttpOnly" in r.headers["set-cookie"] and "samesite=strict" in r.headers["set-cookie"].lower()
    v = client.post("/api/auth/verify", json={"code": code})
    assert v.status_code == 200 and v.json()["user"]["role"] == "SUPER_ADMIN_TI"
    assert "HttpOnly" in v.headers["set-cookie"]
    assert client.get("/api/auth/session").status_code == 200


def test_sin_segundo_factor_no_hay_acceso(client, mail):
    login(client, mail)                                      # solo contraseña
    for path in ("/api/overview", "/api/auth/session", "/api/audit", "/api/recovery", "/api/actions"):
        assert client.get(path).status_code == 401


def test_contrasena_incorrecta_y_usuario_inexistente_mismo_mensaje(client, mail):
    a = client.post("/api/auth/login", json={"email": EMAIL, "password": "mala-mala-mala"})
    b = client.post("/api/auth/login", json={"email": "nadie@x.test", "password": "mala-mala-mala"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json() and not mail.sent


def test_otp_incorrecto(client, mail):
    _, code = login(client, mail)
    bad = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/verify", json={"code": bad}).status_code == 401
    assert client.get("/api/auth/session").status_code == 401
    assert client.post("/api/auth/verify", json={"code": code}).status_code == 200      # el correcto aún sirve


def test_otp_vencido(client, mail, clock):
    _, code = login(client, mail)
    clock.advance(minutes=5, seconds=1)
    r = client.post("/api/auth/verify", json={"code": code})
    assert r.status_code == 401 and "venció" in r.json()["detail"]


def test_otp_reutilizado(client, mail):
    _, code = login(client, mail)
    assert client.post("/api/auth/verify", json={"code": code}).status_code == 200
    client.cookies.delete("nexoops_session")
    assert client.post("/api/auth/verify", json={"code": code}).status_code == 401


def test_exceso_de_intentos_invalida_incluso_el_codigo_correcto(client, mail):
    _, code = login(client, mail)
    bad = "000000" if code != "000000" else "111111"
    for _ in range(A.OTP_MAX_ATTEMPTS):
        assert client.post("/api/auth/verify", json={"code": bad}).status_code == 401
    assert client.post("/api/auth/verify", json={"code": code}).status_code == 429
    assert client.post("/api/auth/verify", json={"code": code}).status_code == 401


def test_reenvio_limites(client, mail, clock):
    login(client, mail)
    assert client.post("/api/auth/resend").status_code == 429                 # enfriamiento
    for _ in range(A.RESEND_MAX):
        clock.advance(seconds=61)
        assert client.post("/api/auth/resend").status_code == 200
    clock.advance(seconds=61)
    assert client.post("/api/auth/resend").status_code == 429
    assert len(mail.sent) == 1 + A.RESEND_MAX


def test_reenvio_invalida_el_codigo_anterior(client, mail, clock):
    _, old = login(client, mail)
    clock.advance(seconds=61); client.post("/api/auth/resend"); new = mail.sent[-1][1]
    if old != new:
        assert client.post("/api/auth/verify", json={"code": old}).status_code == 401
    assert client.post("/api/auth/verify", json={"code": new}).status_code == 200


def test_bloqueo_por_fallos_de_contrasena(client, mail):
    for _ in range(A.LOGIN_MAX_FAILS):
        client.post("/api/auth/login", json={"email": EMAIL, "password": "mala-mala-mala"})
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 429 and "retry-after" in r.headers and not mail.sent


def test_logout_invalida_sesion(authed):
    assert authed.post("/api/auth/logout").status_code == 200
    assert authed.get("/api/auth/session").status_code == 401


def test_revocar_todas_las_sesiones(authed, app):
    app.state.auth.revoke_all(EMAIL)
    assert authed.get("/api/overview").status_code == 401


def test_sesion_expira_por_inactividad(authed, clock):
    clock.advance(minutes=31)
    assert authed.get("/api/overview").status_code == 401


def test_csrf_obligatorio_en_post(authed):
    h = dict(authed.headers); authed.headers.pop("X-CSRF-Token")
    assert authed.post("/api/actions", json={"name": "status.refresh"}).status_code == 403
    authed.headers.update(h)


def test_origen_cruzado_rechazado(authed):
    assert authed.post("/api/actions", json={"name": "status.refresh"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_credenciales_y_otp_no_se_registran(client, mail, app):
    _, code = login(client, mail)
    client.post("/api/auth/verify", json={"code": code})
    raw = (app.state.audit.path).read_text()
    assert PW not in raw and code not in raw and "nexoops_session" not in raw
    ev = [e["event"] for e in app.state.audit.entries()]
    assert "login_paso1_ok" in ev and "login_ok" in ev and app.state.audit.verify()["ok"]


def test_falla_de_correo_no_da_acceso(cfg, clock):
    from fastapi.testclient import TestClient
    from nexoops import mailer as M
    from nexoops.app import create_app
    class Rota:
        def send(self, *a): raise M.MailError("fallo")
    a = create_app(cfg, mailer=Rota(), clock=clock); a.state.auth.create_user(EMAIL, PW)
    c = TestClient(a)
    assert c.post("/api/auth/login", json={"email": EMAIL, "password": PW}).status_code == 502
    assert c.get("/api/overview").status_code == 401


def test_contrasena_con_argon2id(app):
    h = app.state.auth.db.execute("SELECT password_hash FROM users").fetchone()[0]
    assert h.startswith("$argon2id$")
    v = app.state.auth.db.execute("SELECT verifier FROM challenges").fetchall()
    assert v == []


def test_config_exige_secreto_y_cookie_secure(cfg):
    import pytest
    cfg.otp_secret = b"corto"
    with pytest.raises(ValueError): cfg.validate()
    cfg.otp_secret = b"s" * 40; cfg.env = "production"; cfg.mail_mode = "outbox"
    with pytest.raises(ValueError): cfg.validate()
