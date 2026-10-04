from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app
from tests.conftest import TEST_ADMIN_URL, TEST_APP_URL, csrf_headers, login

CLIENT_PASSWORD = "Only-For-Tests-Client-2026!"


def register_client(client: TestClient, email: str = "cliente-a@example.com") -> dict:
    response = client.post(
        "/api/auth/register",
        headers={"Origin": "http://testserver"},
        json={"email": email, "display_name": "Cliente de prueba", "password": CLIENT_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def post_reservation(client: TestClient, event_id: int, key: str, quantity: int = 1):
    return client.post(
        f"/api/events/{event_id}/reservations",
        headers={**csrf_headers(client), "Idempotency-Key": key},
        json={"quantity": quantity},
    )


def test_health_and_catalog_come_from_postgresql() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "service": "nexoeventos-api"}
        assert client.get("/ready").json() == {"status": "ready"}
        response = client.get("/api/events")
        assert response.status_code == 200
        assert [event["id"] for event in response.json()][:3] == [1, 2, 3]
        detail = client.get("/api/events/1").json()
        assert detail["name"] == "Noche Prisma"
        assert detail["available_capacity"] == 240
        assert detail["description"]
    app.state.engine.dispose()


def test_private_routes_reject_unauthenticated_access() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        assert client.get("/api/me/reservations").status_code == 401
        assert client.get("/api/me/tickets").status_code == 401
        assert client.get("/api/operator/events").status_code == 401
        assert client.get("/api/organizer/events").status_code == 401
        response = client.post(
            "/api/events/1/reservations",
            headers={"Idempotency-Key": "no-session-key"},
            json={"quantity": 1},
        )
        assert response.status_code == 401
    app.state.engine.dispose()


def test_public_registration_cannot_assign_privileged_role() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            headers={"Origin": "http://testserver"},
            json={
                "email": "intruso@example.com",
                "display_name": "Intruso de prueba",
                "password": CLIENT_PASSWORD,
                "role": "organizer",
            },
        )
    app.state.engine.dispose()
    assert response.status_code == 422
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users WHERE email = 'intruso@example.com'")) == 0


def test_events_reservations_and_tickets_persist_across_backend_restart() -> None:
    first_app = create_app(TEST_APP_URL)
    with TestClient(first_app) as client:
        register_client(client)
        created = post_reservation(client, 1, "persist-after-restart", quantity=2)
        assert created.status_code == 201, created.text
        reservation_id = created.json()["reservation_id"]
        assert created.json()["ticket_count"] == 2
    first_app.state.engine.dispose()

    restarted_app = create_app(TEST_APP_URL)
    with TestClient(restarted_app) as client:
        login(client, "cliente-a@example.com", CLIENT_PASSWORD)
        reservations = client.get("/api/me/reservations").json()
        tickets = client.get("/api/me/tickets").json()
        assert reservations[0]["id"] == reservation_id
        assert len(tickets) == 2
        assert all(ticket["qr_token"].startswith("nexo_") for ticket in tickets)
        assert all(ticket["event_date"] == "2026-10-17" for ticket in tickets)
        assert all(ticket["event_venue"] == "Centro Cultural de Lima" for ticket in tickets)
        assert client.get("/api/events/1").json()["available_capacity"] == 238
    restarted_app.state.engine.dispose()


def test_duplicate_registration_uses_a_generic_message() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        client.cookies.clear()
        response = client.post(
            "/api/auth/register",
            headers={"Origin": "http://testserver"},
            json={
                "email": "cliente-a@example.com",
                "display_name": "Otro nombre",
                "password": CLIENT_PASSWORD,
            },
        )
    app.state.engine.dispose()
    assert response.status_code == 409
    assert response.json() == {
        "detail": "No se pudo completar el registro. Revisa los datos o intenta iniciar sesión."
    }


def test_two_concurrent_requests_for_last_seat_create_exactly_one_reservation() -> None:
    barrier = Barrier(2)

    def attempt(index: int):
        app = create_app(TEST_APP_URL)
        with TestClient(app) as client:
            register_client(client, f"cliente-{index}@example.com")
            barrier.wait()
            response = post_reservation(client, 9001, f"concurrent-key-{index}")
        app.state.engine.dispose()
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(attempt, [1, 2]))

    assert statuses == [201, 409]
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM reservations WHERE event_id = 9001")) == 1
        assert connection.scalar(text("SELECT reserved_count FROM events WHERE id = 9001")) == 1
        assert connection.scalar(text("SELECT count(*) FROM tickets WHERE event_id = 9001")) == 1


def test_idempotency_replay_conflicts_and_is_scoped_to_owner() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as owner:
        register_client(owner)
        first = post_reservation(owner, 1, "same-request-key", quantity=2)
        replay = post_reservation(owner, 1, "same-request-key", quantity=2)
        conflict = post_reservation(owner, 1, "same-request-key", quantity=1)
        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["reservation_id"] == first.json()["reservation_id"]
        assert replay.json()["replayed"] is True
        assert conflict.status_code == 409

    with TestClient(app) as other:
        register_client(other, "cliente-b@example.com")
        cross_owner = post_reservation(other, 1, "same-request-key", quantity=2)
        assert cross_owner.status_code == 409
        assert other.get("/api/me/reservations").json() == []
    app.state.engine.dispose()


def test_client_cannot_read_another_clients_ticket() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as owner:
        register_client(owner)
        assert post_reservation(owner, 1, "owner-ticket-key").status_code == 201
        ticket_id = owner.get("/api/me/tickets").json()[0]["id"]
    with TestClient(app) as other:
        register_client(other, "cliente-b@example.com")
        assert other.get(f"/api/me/tickets/{ticket_id}").status_code == 404
        assert other.get("/api/me/tickets").json() == []
    app.state.engine.dispose()


def test_operator_cannot_validate_unassigned_event(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        post_reservation(client, 9002, "ticket-for-foreign-event")
        token = client.get("/api/me/tickets").json()[0]["qr_token"]
        client.cookies.clear()
        login(client, "operador@example.com", privileged_accounts["operator"])
        response = client.post(
            "/api/operator/validate",
            headers=csrf_headers(client),
            json={"event_id": 9002, "qr_token": token},
        )
        assert response.status_code == 403
    app.state.engine.dispose()


def test_two_simultaneous_validations_accept_exactly_once(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        post_reservation(client, 1, "ticket-for-concurrent-scan")
        token = client.get("/api/me/tickets").json()[0]["qr_token"]
    app.state.engine.dispose()
    barrier = Barrier(2)

    def attempt() -> int:
        local_app = create_app(TEST_APP_URL)
        with TestClient(local_app) as operator:
            login(operator, "operador@example.com", privileged_accounts["operator"])
            barrier.wait()
            response = operator.post(
                "/api/operator/validate",
                headers=csrf_headers(operator),
                json={"event_id": 1, "qr_token": token},
            )
        local_app.state.engine.dispose()
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: attempt(), [1, 2]))

    assert statuses == [200, 409]
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM tickets WHERE used_at IS NOT NULL")) == 1
        results = connection.execute(text("SELECT result FROM access_logs ORDER BY created_at")).scalars().all()
        assert sorted(results) == ["accepted", "already_used"]
        assert connection.scalar(text("SELECT bool_and(length(token_fingerprint) = 16) FROM access_logs")) is True


def test_invalid_and_reused_qr_are_controlled(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        post_reservation(client, 1, "ticket-for-reuse")
        token = client.get("/api/me/tickets").json()[0]["qr_token"]
        client.cookies.clear()
        login(client, "operador@example.com", privileged_accounts["operator"])
        invalid = client.post(
            "/api/operator/validate",
            headers=csrf_headers(client),
            json={"event_id": 1, "qr_token": "nexo_este-token-no-existe-000000"},
        )
        first = client.post(
            "/api/operator/validate", headers=csrf_headers(client), json={"event_id": 1, "qr_token": token}
        )
        reused = client.post(
            "/api/operator/validate", headers=csrf_headers(client), json={"event_id": 1, "qr_token": token}
        )
        assert invalid.status_code == 404
        assert first.status_code == 200
        assert reused.status_code == 409
        assert reused.json() == {"detail": "Entrada ya utilizada"}
    app.state.engine.dispose()


def test_organizer_only_manages_owned_events(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        login(client, "organizador@example.com", privileged_accounts["organizer"])
        ids = [event["id"] for event in client.get("/api/organizer/events").json()]
        assert 1 in ids and 9002 not in ids
        own = client.patch(
            "/api/organizer/events/1",
            headers=csrf_headers(client),
            json={"description": "Descripción ficticia actualizada por su organizador."},
        )
        foreign = client.patch(
            "/api/organizer/events/9002",
            headers=csrf_headers(client),
            json={"description": "No debe modificarse este evento ajeno."},
        )
        assert own.status_code == 200
        assert foreign.status_code == 404
    app.state.engine.dispose()


def test_logout_invalidates_server_session() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        session_cookie = client.cookies.get("nexoeventos_session")
        csrf = client.cookies.get("nexoeventos_csrf")
        assert client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 204
        client.cookies.set("nexoeventos_session", session_cookie)
        client.cookies.set("nexoeventos_csrf", csrf)
        assert client.get("/api/me/tickets").status_code == 401
    app.state.engine.dispose()


def test_login_attempts_are_limited_and_do_not_log_credentials() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        client.cookies.clear()
        statuses = []
        for _ in range(5):
            response = client.post(
                "/api/auth/login",
                headers={"Origin": "http://testserver"},
                json={"email": "cliente-a@example.com", "password": "incorrecta"},
            )
            statuses.append(response.status_code)
        assert statuses == [401, 401, 401, 401, 429]
        blocked = client.post(
            "/api/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": "cliente-a@example.com", "password": CLIENT_PASSWORD},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert CLIENT_PASSWORD not in blocked.text
    app.state.engine.dispose()


def test_reservations_are_not_exposed_by_public_get_endpoint() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        assert client.get("/api/reservations").status_code == 404
    app.state.engine.dispose()


def test_production_configuration_requires_secure_https(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config

    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", frozenset({"http://example.test"}))
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        config.validate_production_config()

    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    with pytest.raises(RuntimeError, match="HTTPS"):
        config.validate_production_config()

    monkeypatch.setattr(config, "ALLOWED_ORIGINS", frozenset({"https://example.test"}))
    monkeypatch.setenv("SECURITY_HASH_KEY", "test-only-security-hash-key")
    config.validate_production_config()


def test_application_database_role_cannot_create_objects() -> None:
    with create_engine(TEST_APP_URL).connect() as connection:
        assert connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")) is False
        assert connection.scalar(text("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")) is False
