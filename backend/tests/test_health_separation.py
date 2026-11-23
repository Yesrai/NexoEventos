from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import TEST_APP_URL

ROOT = Path(__file__).resolve().parents[2]
# Puerto 1 en localhost: la conexión es rechazada al instante (simula PostgreSQL caído sin tocar ninguna nube).
UNREACHABLE_DB = "postgresql+psycopg://nexoeventos_app@127.0.0.1:1/nexoeventos_test"


def test_liveness_and_readiness_ok_when_postgresql_is_available() -> None:
    with TestClient(create_app(TEST_APP_URL)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_liveness_stays_up_but_readiness_fails_when_postgresql_is_down() -> None:
    with TestClient(create_app(UNREACHABLE_DB)) as client:
        live = client.get("/health")
        ready = client.get("/ready")
    assert live.status_code == 200 and live.json()["status"] == "ok"
    assert ready.status_code == 503
    assert "127.0.0.1" not in ready.text and "nexoeventos_app" not in ready.text


def test_database_endpoint_returns_retryable_503_not_500_when_postgresql_is_down() -> None:
    with TestClient(create_app(UNREACHABLE_DB), raise_server_exceptions=False) as client:
        response = client.get("/api/events")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json() == {"detail": "Servicio no disponible temporalmente"}
    assert "127.0.0.1" not in response.text and "nexoeventos_app" not in response.text


def test_alb_health_check_uses_liveness_and_monitoring_keeps_readiness() -> None:
    nginx = (ROOT / "ansible/roles/nexoeventos/templates/nexoeventos-nginx-alb.conf.j2").read_text()
    assert "location = /livez {" in nginx and "proxy_pass http://127.0.0.1:8000/health;" in nginx
    assert "location = /healthz {" in nginx and "proxy_pass http://127.0.0.1:8000/ready;" in nginx
    alb = (ROOT / "infra/aws-v2/alb.tf").read_text()
    assert 'var.ami_includes_livez ? "/livez" : "/healthz"' in alb
    assert 'health_check_type         = "ELB"' in (ROOT / "infra/aws-v2/compute.tf").read_text()


def test_liveness_handler_runs_on_the_event_loop_not_the_thread_pool() -> None:
    import inspect

    app = create_app(UNREACHABLE_DB)
    route = next(r for r in app.routes if getattr(r, "path", None) == "/health")
    assert inspect.iscoroutinefunction(route.endpoint)


def test_default_keeps_old_amis_safe_from_false_health() -> None:
    variables = (ROOT / "infra/aws-v2/variables.tf").read_text()
    block = variables[variables.index('variable "ami_includes_livez"'):]
    assert "default     = false" in block.split("}")[0]


def test_pool_exhaustion_returns_503_and_liveness_stays_up(monkeypatch) -> None:
    # Pool de 1 conexión sin desborde y 1 s de espera: con la conexión ocupada, una petición de datos falla con 503 (no 500) y /health sigue en 200.
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "1")
    app = create_app(TEST_APP_URL)
    with TestClient(app, raise_server_exceptions=False) as client:
        with app.state.engine.connect():
            busy = client.get("/api/events")
            live = client.get("/health")
    assert busy.status_code == 503 and busy.headers["Retry-After"] == "5"
    assert live.status_code == 200


def test_shutdown_disposes_the_connection_pool() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        assert client.get("/api/events").status_code == 200
        assert app.state.engine.pool.checkedin() >= 1
    # Tras el apagado el pool se reinició: no quedan conexiones abiertas hacia PostgreSQL.
    assert app.state.engine.pool.checkedin() == 0


def test_service_units_stop_gracefully_before_systemd_kills_them() -> None:
    import re

    for unit in ("deploy/systemd/nexoeventos-api.service", "ansible/roles/nexoeventos/templates/nexoeventos-api.service.j2"):
        text = (ROOT / unit).read_text()
        graceful = int(re.search(r"--timeout-graceful-shutdown (\d+)", text).group(1))
        stop = int(re.search(r"TimeoutStopSec=(\d+)", text).group(1))
        assert graceful < stop, unit
