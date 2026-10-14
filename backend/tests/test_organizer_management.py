from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app
from tests.conftest import TEST_ADMIN_URL, TEST_APP_URL, csrf_headers, login
from tests.test_api import post_reservation, register_client

FUTURE = (date.today() + timedelta(days=30)).isoformat()
THEATRE = {"layout_id": 9000, "sections": [{"name": "General", "price": 30, "rows": 2, "seats_per_row": 4}, {"name": "Preferencial", "price": 55, "rows": 1, "seats_per_row": 4}]}


def new_event(client: TestClient, **overrides) -> dict:
    body = {"name": "Función creada por organizador", "date": FUTURE, "time": "20:00:00", "category": "Teatro y stand-up", "description": "Evento ficticio creado desde el panel del organizador.", **THEATRE, **overrides}
    response = client.post("/api/organizer/events", headers=csrf_headers(client), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def organizer_client(app, passwords: dict[str, str], who: str = "organizer") -> TestClient:
    client = TestClient(app)
    email = {"organizer": "organizador@example.com", "organizer_other": "otro-organizador@example.com"}[who]
    login(client, email, passwords[who])
    return client


def test_complete_flow_create_configure_publish_reserve_issue_qr_and_validate(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    venues = organizer.get("/api/organizer/venues").json()
    assert any(layout["layout_id"] == 9000 and layout["ticket_mode"] == "seats" for venue in venues for layout in venue["layouts"])

    draft = new_event(organizer)
    event_id = draft["id"]
    assert (draft["status"], draft["ticket_mode"], draft["layout_kind"], draft["capacity"]) == ("draft", "seats", "theatre", 12)
    assert draft["venue"] == "Auditorio de prueba" and len(draft["seats"]) == 12
    assert sorted({seat["row"] for seat in draft["seats"]}) == ["A", "B", "C"]
    assert {zone["name"]: zone["price"] for zone in draft["zones"]} == {"General": 30.0, "Preferencial": 55.0}

    with TestClient(app) as buyer:
        register_client(buyer)
        assert event_id not in [item["id"] for item in buyer.get("/api/events").json()]
        assert buyer.get(f"/api/events/{event_id}").status_code == 404
        assert post_reservation(buyer, event_id, "draft-reservation-key").status_code == 404
        assert organizer.get(f"/api/organizer/events/{event_id}").status_code == 200

        state = organizer.get(f"/api/organizer/events/{event_id}/state").json()
        assert state["can_publish"] and state["can_edit_inventory"] and state["publish_problems"] == []
        published = organizer.post(f"/api/organizer/events/{event_id}/publish", headers=csrf_headers(organizer))
        assert published.status_code == 200 and published.json()["status"] == "published"

        assert event_id in [item["id"] for item in buyer.get("/api/events").json()]
        detail = buyer.get(f"/api/events/{event_id}").json()
        seat = next(item for item in detail["seats"] if item["row"] == "C" and item["number"] == 1)
        assert seat["price"] == 55.0
        reserved = buyer.post(f"/api/events/{event_id}/reservations", headers={**csrf_headers(buyer), "Idempotency-Key": "organizer-flow-key"}, json={"quantity": 1, "seat_ids": [seat["id"]]})
        assert reserved.status_code == 201 and reserved.json()["total"] == 55.0
        ticket = buyer.get("/api/me/tickets").json()[0]
        token = buyer.get(f"/api/me/tickets/{ticket['id']}").json()["qr_token"]
        assert (ticket["row"], ticket["seat"], ticket["zone"]) == ("C", 1, "Preferencial")

    assert organizer.post(f"/api/organizer/events/{event_id}/operators", headers=csrf_headers(organizer), json={"email": "nadie@example.com"}).status_code == 404
    assigned = organizer.post(f"/api/organizer/events/{event_id}/operators", headers=csrf_headers(organizer), json={"email": "operador@example.com"})
    assert assigned.status_code == 201 and [item["email"] for item in assigned.json()] == ["operador@example.com"]
    with TestClient(app) as operator:
        login(operator, "operador@example.com", privileged_accounts["operator"])
        assert event_id in [item["id"] for item in operator.get("/api/operator/events").json()]
        first = operator.post("/api/operator/validate", headers=csrf_headers(operator), json={"event_id": event_id, "qr_token": token})
        second = operator.post("/api/operator/validate", headers=csrf_headers(operator), json={"event_id": event_id, "qr_token": token})
        assert (first.status_code, second.status_code) == (200, 409)
        assert "Preferencial" in first.json()["ticket_location"]

    stats = organizer.get(f"/api/organizer/events/{event_id}/stats").json()
    assert (stats["sold"], stats["revenue"], stats["checked_in"], stats["available"]) == (1, 55.0, 1, 11)

    state = organizer.get(f"/api/organizer/events/{event_id}/state").json()
    assert state["has_sales"] and not any([state["can_edit_inventory"], state["can_unpublish"], state["can_delete"]])
    blocked = {
        "inventory": organizer.put(f"/api/organizer/events/{event_id}/inventory", headers=csrf_headers(organizer), json={"layout_id": 9000, "sections": [{"name": "Única", "price": 1, "rows": 1, "seats_per_row": 2}]}),
        "date": organizer.patch(f"/api/organizer/events/{event_id}", headers=csrf_headers(organizer), json={"date": (date.today() + timedelta(days=60)).isoformat()}),
        "time": organizer.patch(f"/api/organizer/events/{event_id}", headers=csrf_headers(organizer), json={"time": "10:00:00"}),
        "unpublish": organizer.post(f"/api/organizer/events/{event_id}/unpublish", headers=csrf_headers(organizer)),
        "delete": organizer.delete(f"/api/organizer/events/{event_id}", headers=csrf_headers(organizer)),
    }
    assert {name: response.status_code for name, response in blocked.items()} == dict.fromkeys(blocked, 409)
    assert organizer.patch(f"/api/organizer/events/{event_id}", headers=csrf_headers(organizer), json={"description": "Descripción corregida después de las ventas."}).status_code == 200
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM event_seats WHERE event_id=:id"), {"id": event_id}) == 12
        assert connection.scalar(text("SELECT count(*) FROM tickets WHERE event_id=:id"), {"id": event_id}) == 1
    app.state.engine.dispose()


def test_each_ticket_mode_is_configured_from_its_layout_and_invalid_combinations_are_rejected(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    concert = new_event(organizer, layout_id=9002, sections=[], zones=[{"name": "Campo", "price": 45, "capacity": 100}, {"name": "Preferencial", "price": 80, "capacity": 40}])
    assert (concert["ticket_mode"], concert["layout_kind"], concert["capacity"], concert["seats"]) == ("zones", "concert_zones", 140, [])
    museum = new_event(organizer, layout_id=9003, sections=[], price=18, capacity=60, time="11:00:00")
    assert (museum["ticket_mode"], museum["layout_kind"], museum["capacity"], museum["price"]) == ("general", "museum", 60, 18.0)
    stadium = new_event(organizer, layout_id=9001, sections=[{"name": "Tribuna Norte", "price": 40, "rows": 2, "seats_per_row": 12}, {"name": "Tribuna Sur", "price": 50, "rows": 2, "seats_per_row": 12}])
    assert stadium["ticket_mode"] == "seats" and stadium["capacity"] == 48

    def reject(**overrides):
        response = organizer.post("/api/organizer/events", headers=csrf_headers(organizer), json={"name": "Inválido", "date": FUTURE, "category": "Prueba", "description": "Configuración inválida de prueba.", **overrides})
        assert response.status_code in (422,), response.text
        return response.json()["detail"]

    reject(layout_id=9000, sections=[], zones=[{"name": "Zona", "price": 1, "capacity": 5}])
    reject(layout_id=9002, sections=[{"name": "Fila", "price": 1, "rows": 1, "seats_per_row": 2}])
    reject(layout_id=9003, sections=[], price=10)
    reject(layout_id=9004, sections=[], price=10, capacity=10, zones=[{"name": "Extra", "price": 1, "capacity": 1}])
    reject(layout_id=9001, sections=[{"name": "Platea", "price": 1, "rows": 1, "seats_per_row": 2}])
    reject(layout_id=9000, sections=[{"name": "A", "price": 1, "rows": 8, "seats_per_row": 2}, {"name": "B", "price": 1, "rows": 8, "seats_per_row": 2}])
    reject(layout_id=9002, sections=[], zones=[{"name": "Campo", "price": 1, "capacity": 5}, {"name": "campo", "price": 2, "capacity": 5}])
    reject(layout_id=424242, sections=[], price=1, capacity=1)
    app.state.engine.dispose()


def test_publish_checks_museum_time_and_past_dates_and_drafts_can_be_reconfigured_and_deleted(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    museum = new_event(organizer, layout_id=9003, sections=[], price=18, capacity=60, time=None)
    refused = organizer.post(f"/api/organizer/events/{museum['id']}/publish", headers=csrf_headers(organizer))
    assert refused.status_code == 422 and "hora" in refused.json()["detail"]
    assert organizer.patch(f"/api/organizer/events/{museum['id']}", headers=csrf_headers(organizer), json={"time": "10:30:00"}).status_code == 200
    assert organizer.post(f"/api/organizer/events/{museum['id']}/publish", headers=csrf_headers(organizer)).status_code == 200

    past = new_event(organizer)
    with create_engine(TEST_ADMIN_URL).begin() as connection:
        connection.execute(text("UPDATE events SET event_date = DATE '2020-01-01' WHERE id = :id"), {"id": past["id"]})
    assert organizer.post(f"/api/organizer/events/{past['id']}/publish", headers=csrf_headers(organizer)).status_code == 422

    rebuilt = organizer.put(f"/api/organizer/events/{past['id']}/inventory", headers=csrf_headers(organizer), json={"layout_id": 9002, "zones": [{"name": "Campo", "price": 20, "capacity": 30}]})
    assert rebuilt.status_code == 200 and (rebuilt.json()["ticket_mode"], rebuilt.json()["capacity"], rebuilt.json()["seats"]) == ("zones", 30, [])
    assert organizer.delete(f"/api/organizer/events/{past['id']}", headers=csrf_headers(organizer)).status_code == 204
    assert organizer.get(f"/api/organizer/events/{past['id']}").status_code == 404
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM event_zones WHERE event_id=:id"), {"id": past["id"]}) == 0
    app.state.engine.dispose()


def test_new_function_copies_configuration_but_keeps_inventory_and_sales_independent(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    source = new_event(organizer)
    assert organizer.post(f"/api/organizer/events/{source['id']}/publish", headers=csrf_headers(organizer)).status_code == 200
    with TestClient(app) as buyer:
        register_client(buyer)
        seat = source["seats"][0]
        assert buyer.post(f"/api/events/{source['id']}/reservations", headers={**csrf_headers(buyer), "Idempotency-Key": "function-source-key"}, json={"quantity": 1, "seat_ids": [seat["id"]]}).status_code == 201
    later = (date.today() + timedelta(days=45)).isoformat()
    cloned = organizer.post(f"/api/organizer/events/{source['id']}/functions", headers=csrf_headers(organizer), json={"date": later, "time": "18:30:00"})
    assert cloned.status_code == 201, cloned.text
    copy = cloned.json()
    assert copy["id"] != source["id"] and copy["status"] == "draft" and copy["date"] == later and copy["time"] == "18:30:00"
    assert (copy["name"], copy["layout_id"], copy["capacity"], copy["available_capacity"]) == (source["name"], source["layout_id"], 12, 12)
    assert all(item["available"] for item in copy["seats"]) and {item["id"] for item in copy["seats"]}.isdisjoint({item["id"] for item in source["seats"]})
    assert {zone["id"] for zone in copy["zones"]}.isdisjoint({zone["id"] for zone in source["zones"]})
    assert organizer.get(f"/api/organizer/events/{source['id']}").json()["available_capacity"] == 11
    app.state.engine.dispose()


def test_organizers_cannot_see_or_change_each_others_events_and_clients_have_no_access(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    owner = organizer_client(app, privileged_accounts)
    intruder = organizer_client(app, privileged_accounts, "organizer_other")
    event = new_event(owner)
    event_id = event["id"]
    headers = csrf_headers(intruder)
    attempts = [
        intruder.get(f"/api/organizer/events/{event_id}"),
        intruder.get(f"/api/organizer/events/{event_id}/state"),
        intruder.get(f"/api/organizer/events/{event_id}/stats"),
        intruder.get(f"/api/organizer/events/{event_id}/operators"),
        intruder.patch(f"/api/organizer/events/{event_id}", headers=headers, json={"name": "Robado"}),
        intruder.put(f"/api/organizer/events/{event_id}/inventory", headers=headers, json=THEATRE),
        intruder.post(f"/api/organizer/events/{event_id}/publish", headers=headers),
        intruder.post(f"/api/organizer/events/{event_id}/unpublish", headers=headers),
        intruder.post(f"/api/organizer/events/{event_id}/functions", headers=headers, json={"date": FUTURE}),
        intruder.post(f"/api/organizer/events/{event_id}/operators", headers=headers, json={"email": "operador@example.com"}),
        intruder.delete(f"/api/organizer/events/{event_id}", headers=headers),
    ]
    assert [response.status_code for response in attempts] == [404] * len(attempts)
    assert event_id not in [item["id"] for item in intruder.get("/api/organizer/events").json()]
    assert owner.get(f"/api/organizer/events/{event_id}").json()["name"] == "Función creada por organizador"

    with TestClient(app) as client:
        register_client(client)
        headers = csrf_headers(client)
        assert client.get("/api/organizer/events").status_code == 403
        assert client.get("/api/organizer/venues").status_code == 403
        assert client.post("/api/organizer/events", headers=headers, json={"name": "X", "date": FUTURE, "category": "Y", "description": "Intento de cliente sin permiso.", **THEATRE}).status_code == 403
    assert TestClient(app).get("/api/organizer/venues").status_code == 401
    # Sin cabecera CSRF una mutación se rechaza aunque la sesión sea válida.
    assert owner.post(f"/api/organizer/events/{event_id}/publish").status_code in (400, 403)
    app.state.engine.dispose()
