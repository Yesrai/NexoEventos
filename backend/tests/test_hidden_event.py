"""Eventos ocultos de ensayo: publicados pero fuera del catálogo (is_demo=false), accesibles solo por id.

Fijan que el enlace directo no concede nada nuevo: siguen exigiéndose publicación, sesión, fila virtual e inventario, y que los
intentos de validación de una operadora no asignada solo dejan rastro en eventos ficticios del propio ensayo.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app
from tests.conftest import TEST_ADMIN_URL, TEST_APP_URL, csrf_headers, login
from tests.test_api import post_reservation, register_client
from tests.test_organizer_management import new_event, organizer_client
from tests.test_sales_queue import configure, join, published_general_event, reserve_code


def hide(event_id: int) -> None:
    with create_engine(TEST_ADMIN_URL).begin() as connection:
        connection.execute(text("UPDATE events SET is_demo = false WHERE id = :id"), {"id": event_id})


def catalog_ids(client: TestClient) -> list[int]:
    return [item["id"] for item in client.get("/api/events").json()]


def test_hidden_published_event_is_reachable_by_id_but_never_listed_and_keeps_every_rule(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    hidden_id = published_general_event(organizer, capacity=3)
    visible_id = published_general_event(organizer, capacity=3)
    hide(hidden_id)

    with TestClient(app) as anonymous:
        assert hidden_id not in catalog_ids(anonymous) and visible_id in catalog_ids(anonymous)
        assert anonymous.get(f"/api/events/{hidden_id}").status_code == 200
        assert anonymous.get(f"/api/events/{hidden_id}/sales").status_code == 200
        # sin sesión no se reserva, aunque se conozca el id
        assert anonymous.post(f"/api/events/{hidden_id}/reservations", json={"quantity": 1}, headers={"Idempotency-Key": "anon-hidden-key"}).status_code in (401, 403)

    with TestClient(app) as buyer:
        register_client(buyer, "oculto@example.com")
        assert post_reservation(buyer, hidden_id, "hidden-key-0001").status_code == 201
        replay = post_reservation(buyer, hidden_id, "hidden-key-0001")
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert buyer.get(f"/api/events/{hidden_id}").json()["available_capacity"] == 2  # el inventario sigue contándose
        assert hidden_id not in catalog_ids(buyer)

    # un borrador sigue siendo invisible aunque sea oculto
    draft = new_event(organizer, layout_id=9004, sections=[], price=15, capacity=5, time="19:00:00")
    hide(draft["id"])
    with TestClient(app) as buyer:
        register_client(buyer, "borrador@example.com")
        assert buyer.get(f"/api/events/{draft['id']}").status_code == 404
        assert post_reservation(buyer, draft["id"], "draft-hidden-key").status_code == 404
    app.state.engine.dispose()


def test_hidden_event_still_enforces_the_virtual_queue(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    event_id = published_general_event(organizer, capacity=5)
    assert configure(organizer, event_id, None, queue=True, active=1).status_code == 200
    hide(event_id)
    with TestClient(app) as first, TestClient(app) as second:
        register_client(first, "fila-oculta-1@example.com")
        register_client(second, "fila-oculta-2@example.com")
        assert reserve_code(first, event_id, "queue-hidden-0001")[0] in (403, 409, 423)  # sin turno
        assert join(first, event_id)["status"] == "admitted"
        assert join(second, event_id)["status"] == "waiting"
        assert reserve_code(second, event_id, "queue-hidden-0002")[0] in (403, 409, 423)
        assert reserve_code(first, event_id, "queue-hidden-0003")[0] == 201
    app.state.engine.dispose()


def test_unassigned_operator_attempts_only_leave_traces_on_the_dummy_events_used(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    commercial_id = published_general_event(organizer)      # evento «comercial» que no interviene en el ensayo
    assigned_id = published_general_event(organizer)        # ficticio 1: asignado a la operadora
    unassigned_id = published_general_event(organizer)      # ficticio 2: no asignado; recibe el intento denegado
    for event_id in (assigned_id, unassigned_id):
        hide(event_id)
    assert organizer.post(f"/api/organizer/events/{assigned_id}/operators", headers=csrf_headers(organizer), json={"email": "operador@example.com"}).status_code == 201

    with TestClient(app) as buyer:
        register_client(buyer, "ensayo-qr@example.com")
        assert post_reservation(buyer, assigned_id, "dummy-qr-key-0001").status_code == 201
        ticket = buyer.get("/api/me/tickets").json()[0]
        token = buyer.get(f"/api/me/tickets/{ticket['id']}").json()["qr_token"]
        assert buyer.post("/api/operator/validate", headers=csrf_headers(buyer), json={"event_id": assigned_id, "qr_token": token}).status_code == 403  # un cliente no valida

    with TestClient(app) as operator:
        login(operator, "operador@example.com", privileged_accounts["operator"])
        denied = operator.post("/api/operator/validate", headers=csrf_headers(operator), json={"event_id": unassigned_id, "qr_token": token})
        accepted = operator.post("/api/operator/validate", headers=csrf_headers(operator), json={"event_id": assigned_id, "qr_token": token})
        reused = operator.post("/api/operator/validate", headers=csrf_headers(operator), json={"event_id": assigned_id, "qr_token": token})
        assert (denied.status_code, accepted.status_code, reused.status_code) == (403, 200, 409)

    with create_engine(TEST_ADMIN_URL).connect() as connection:
        rows = dict(connection.execute(text("SELECT event_id, count(*) FROM access_logs GROUP BY event_id")).all())
    assert commercial_id not in rows                       # ningún rastro en eventos que no son del ensayo
    assert set(rows) == {assigned_id, unassigned_id}
    app.state.engine.dispose()
