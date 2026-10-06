import os
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_APP_URL = "postgresql+psycopg://nexoeventos_app@/nexoeventos_test"
TEST_ADMIN_URL = "postgresql+psycopg:///nexoeventos_test"
os.environ["DATABASE_URL"] = TEST_APP_URL
os.environ["TICKET_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
admin_engine = create_engine(TEST_ADMIN_URL)


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("nexoeventos_csrf")
    assert token
    return {"Origin": "http://testserver", "X-CSRF-Token": token}


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def reset_isolated_test_database() -> Iterator[None]:
    def reset() -> None:
        with admin_engine.begin() as connection:
            connection.execute(text("DELETE FROM access_logs"))
            connection.execute(text("DELETE FROM tickets"))
            connection.execute(text("DELETE FROM operator_event_assignments"))
            connection.execute(text("DELETE FROM auth_sessions"))
            connection.execute(text("DELETE FROM auth_rate_limits"))
            connection.execute(text("DELETE FROM event_seats WHERE event_id >= 9000"))
            connection.execute(text("DELETE FROM event_zones WHERE event_id >= 9000"))
            connection.execute(text("DELETE FROM reservations"))
            connection.execute(text("UPDATE events SET organizer_user_id = NULL, reserved_count = 0"))
            connection.execute(text("DELETE FROM users"))
            connection.execute(text("DELETE FROM events WHERE id >= 9000"))

    reset()
    with admin_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO events (id, name, event_date, venue, category, description, price, capacity, reserved_count)
            VALUES
              (9001, 'Último cupo de prueba', DATE '2026-11-20', 'Laboratorio local', 'Prueba',
               'Evento ficticio aislado para probar concurrencia.', 10.00, 1, 0),
              (9002, 'Evento ajeno de prueba', DATE '2026-11-21', 'Laboratorio local', 'Prueba',
               'Evento ficticio para probar separación entre organizadores y operadores.', 10.00, 20, 0),
              (9003, 'Zonas de prueba', DATE '2026-11-22', 'Laboratorio local', 'Prueba',
               'Evento aislado para probar precios por zona.', 10.00, 4, 0),
              (9004, 'Asientos de prueba', DATE '2026-11-23', 'Laboratorio local', 'Prueba',
               'Evento aislado para probar asignación atómica de asientos.', 10.00, 2, 0)
        """))
        connection.execute(text("UPDATE events SET ticket_mode='zones' WHERE id=9003"))
        connection.execute(text("UPDATE events SET ticket_mode='seats' WHERE id=9004"))
        connection.execute(text("""
            INSERT INTO event_zones (event_id, name, price, capacity, reserved_count)
            VALUES
              (9003, 'Preferencial', 25.00, 4, 0),
              (9003, 'VIP agotada', 40.00, 0, 0)
        """))
        seat_zone = connection.scalar(text("""
            INSERT INTO event_zones (event_id, name, price, capacity, reserved_count)
            VALUES (9004, 'Platea', 30.00, 2, 0) RETURNING id
        """))
        connection.execute(text("""
            INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
            VALUES (9004, :zone, 'A', 1), (9004, :zone, 'A', 2)
        """), {"zone": seat_zone})
    yield
    reset()


@pytest.fixture
def privileged_accounts() -> dict[str, str]:
    from app.auth import hash_password

    passwords = {
        "organizer": "Only-For-Tests-Organizer-2026!",
        "organizer_other": "Only-For-Tests-Organizer-Other!",
        "operator": "Only-For-Tests-Operator-2026!",
        "operator_other": "Only-For-Tests-Operator-Other!",
    }
    with admin_engine.begin() as connection:
        rows = connection.execute(text("""
            INSERT INTO users (id, email, display_name, password_hash, role)
            VALUES
              (gen_random_uuid(), 'organizador@example.com', 'Organizador de prueba', :organizer_hash, 'organizer'),
              (gen_random_uuid(), 'otro-organizador@example.com', 'Otro organizador', :organizer_other_hash, 'organizer'),
              (gen_random_uuid(), 'operador@example.com', 'Operador de prueba', :operator_hash, 'operator'),
              (gen_random_uuid(), 'otro-operador@example.com', 'Otro operador', :operator_other_hash, 'operator')
            RETURNING id, email
        """), {
            "organizer_hash": hash_password(passwords["organizer"]),
            "organizer_other_hash": hash_password(passwords["organizer_other"]),
            "operator_hash": hash_password(passwords["operator"]),
            "operator_other_hash": hash_password(passwords["operator_other"]),
        }).mappings().all()
        ids = {row["email"]: row["id"] for row in rows}
        connection.execute(text("UPDATE events SET organizer_user_id = :id WHERE id IN (1, 9001)"), {
            "id": ids["organizador@example.com"],
        })
        connection.execute(text("UPDATE events SET organizer_user_id = :id WHERE id = 9002"), {
            "id": ids["otro-organizador@example.com"],
        })
        connection.execute(text("""
            INSERT INTO operator_event_assignments (operator_user_id, event_id)
            VALUES (:operator_id, 1), (:operator_id, 9001), (:other_operator_id, 9002)
        """), {
            "operator_id": ids["operador@example.com"],
            "other_operator_id": ids["otro-operador@example.com"],
        })
    return passwords
