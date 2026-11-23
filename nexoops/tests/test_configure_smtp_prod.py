"""configure-smtp en la VM (NEXOOPS_ENV=production) no puede dejar el archivo en modo dev ni con cookies no seguras, y conserva las demás claves."""
import os
from nexoops import __main__ as M


def test_produccion_no_degrada_cookies_y_conserva_tokens(tmp_path, monkeypatch):
    p = tmp_path / "nexoops.env"; p.write_text("GRAFANA_TOKEN=abc\nNEXOOPS_OTP_SECRET=" + "x" * 48 + "\n"); os.chmod(p, 0o600)
    monkeypatch.setenv("NEXOOPS_ENV_FILE", str(p)); monkeypatch.setenv("NEXOOPS_ENV", "production")
    monkeypatch.setattr("builtins.input", lambda *_: "ops@example.test"); monkeypatch.setattr(M.getpass, "getpass", lambda *_: "abcd efgh ijkl mnop")
    M.configure_smtp()
    d = dict(l.split("=", 1) for l in p.read_text().splitlines())
    assert d["NEXOOPS_ENV"] == "production" and d["NEXOOPS_COOKIE_SECURE"] == "1" and d["GRAFANA_TOKEN"] == "abc" and d["NEXOOPS_OTP_SECRET"] == "x" * 48
    assert oct(p.stat().st_mode & 0o777) == "0o600"
