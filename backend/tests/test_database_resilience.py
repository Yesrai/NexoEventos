import app.database as database
from app.database import build_engine


def _captured_kwargs(monkeypatch, url: str) -> dict:
    captured: dict = {}

    def fake_create_engine(received_url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    build_engine(url)
    return captured


def test_remote_database_gets_connect_timeout_keepalives_and_recycle(monkeypatch, tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("ca")
    monkeypatch.delenv("DB_CONNECT_TIMEOUT", raising=False)
    kwargs = _captured_kwargs(monkeypatch, f"postgresql+psycopg://u@db.example.internal/app?sslmode=verify-full&sslrootcert={ca}")
    assert kwargs["connect_args"]["connect_timeout"] == 5
    assert kwargs["connect_args"]["keepalives"] == 1
    assert kwargs["pool_pre_ping"] is True and kwargs["pool_recycle"] == 1800 and kwargs["pool_timeout"] == 30


def test_local_socket_and_localhost_do_not_get_tcp_only_options(monkeypatch) -> None:
    assert _captured_kwargs(monkeypatch, "postgresql+psycopg:///nexoeventos_test")["connect_args"] == {}
    assert _captured_kwargs(monkeypatch, "postgresql+psycopg://u@localhost/app")["connect_args"] == {}


def test_timeouts_are_bounded_by_environment(monkeypatch, tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("ca")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "3")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "12")
    monkeypatch.setenv("DB_POOL_RECYCLE", "600")
    kwargs = _captured_kwargs(monkeypatch, f"postgresql+psycopg://u@db.example.internal/app?sslmode=verify-full&sslrootcert={ca}")
    assert (kwargs["connect_args"]["connect_timeout"], kwargs["pool_timeout"], kwargs["pool_recycle"]) == (3, 12, 600)
