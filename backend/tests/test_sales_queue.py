from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app
from tests.conftest import TEST_ADMIN_URL, TEST_APP_URL, csrf_headers
from tests.test_api import post_reservation, register_client
from tests.test_organizer_management import new_event, organizer_client


def published_general_event(organizer: TestClient, capacity: int = 20) -> int:
    event = new_event(organizer, layout_id=9004, sections=[], price=15, capacity=capacity, time="19:00:00")
    assert organizer.post(f"/api/organizer/events/{event['id']}/publish", headers=csrf_headers(organizer)).status_code == 200
    return event["id"]


def configure(organizer: TestClient, event_id: int, start: datetime | None, queue: bool, active: int = 2, minutes: int = 10):
    return organizer.put(
        f"/api/organizer/events/{event_id}/sales", headers=csrf_headers(organizer),
        json={"sales_start_at": start.isoformat() if start else None, "queue_enabled": queue, "queue_max_active": active, "queue_pass_minutes": minutes},
    )


def sales(client: TestClient, event_id: int) -> dict:
    response = client.get(f"/api/events/{event_id}/sales")
    assert response.status_code == 200, response.text
    return response.json()


def join(client: TestClient, event_id: int) -> dict:
    response = client.post(f"/api/events/{event_id}/queue", headers=csrf_headers(client))
    assert response.status_code == 200, response.text
    return response.json()["queue"]


def clients(app, count: int) -> list[TestClient]:
    people = []
    for index in range(count):
        client = TestClient(app)
        register_client(client, f"fila-{index}@example.com")
        people.append(client)
    return people


def reserve_code(client: TestClient, event_id: int, key: str):
    response = post_reservation(client, event_id, key)
    detail = response.json().get("detail")
    return response.status_code, detail.get("code") if isinstance(detail, dict) else detail


def test_sales_window_uses_server_time_and_blocks_reservations_until_it_opens(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    event_id = published_general_event(organizer)
    soon = datetime.now(timezone.utc) + timedelta(hours=2)
    assert configure(organizer, event_id, soon, queue=False).status_code == 200
    buyer = TestClient(app)
    register_client(buyer)
    state = sales(buyer, event_id)
    assert state["sales_open"] is False and state["queue"] is None
    assert abs((datetime.fromisoformat(state["server_time"]) - datetime.now(timezone.utc)).total_seconds()) < 5
    assert reserve_code(buyer, event_id, "before-start-key") == (403, "sales_not_open")
    assert TestClient(app).get(f"/api/events/{event_id}/sales").json()["sales_open"] is False
    with create_engine(TEST_ADMIN_URL).begin() as connection:
        connection.execute(text("UPDATE events SET sales_start_at = now() - interval '1 minute' WHERE id=:id"), {"id": event_id})
    assert sales(buyer, event_id)["sales_open"] is True
    assert post_reservation(buyer, event_id, "after-start-key").status_code == 201
    app.state.engine.dispose()


def test_events_without_configuration_keep_working_exactly_as_before() -> None:
    app = create_app(TEST_APP_URL)
    with TestClient(app) as client:
        register_client(client)
        state = sales(client, 9001)
        assert (state["sales_open"], state["queue_enabled"], state["queue"]) == (True, False, None)
        assert post_reservation(client, 9001, "legacy-flow-key").status_code == 201
        assert client.post("/api/events/9001/queue", headers=csrf_headers(client)).status_code == 409
    app.state.engine.dispose()


def test_virtual_queue_admits_in_order_caps_active_buyers_and_cannot_be_skipped(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    event_id = published_general_event(organizer)
    assert configure(organizer, event_id, None, queue=True, active=2).status_code == 200
    people = clients(app, 5)
    assert reserve_code(people[0], event_id, "no-pass-key-0") == (403, "queue_required")
    queues = [join(person, event_id) for person in people]
    assert [item["status"] for item in queues] == ["admitted", "admitted", "waiting", "waiting", "waiting"]
    assert [item["position"] for item in queues[2:]] == [1, 2, 3]
    assert join(people[2], event_id)["position"] == 1  # unirse otra vez (o refrescar) no cambia el lugar
    assert sales(people[4], event_id)["queue"]["position"] == 3
    assert sales(TestClient(app), event_id)["queue"] is None
    assert reserve_code(people[3], event_id, "skip-line-key") == (403, "queue_required")
    assert post_reservation(people[0], event_id, "admitted-key-0").status_code == 201
    assert sales(people[2], event_id)["queue"]["status"] == "admitted"  # el lugar liberado pasa al siguiente
    assert sales(people[3], event_id)["queue"] == {**sales(people[3], event_id)["queue"], "status": "waiting", "position": 1}
    assert reserve_code(people[0], event_id, "second-purchase-key") == (403, "queue_required")  # un turno, una compra
    assert post_reservation(people[0], event_id, "admitted-key-0").status_code == 200  # la repetición idempotente no exige turno
    with create_engine(TEST_ADMIN_URL).begin() as connection:
        connection.execute(text("UPDATE queue_entries SET expires_at = now() - interval '1 second' WHERE status='admitted' AND user_id=(SELECT id FROM users WHERE email='fila-1@example.com')"))
    assert reserve_code(people[1], event_id, "expired-pass-key") == (403, "queue_required")
    assert sales(people[3], event_id)["queue"]["status"] == "admitted"
    leave = people[4].delete(f"/api/events/{event_id}/queue", headers=csrf_headers(people[4]))
    assert leave.status_code == 200 and leave.json()["queue"] is None
    with create_engine(TEST_ADMIN_URL).connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM queue_entries WHERE event_id=:id AND status='admitted'"), {"id": event_id}) <= 2
    app.state.engine.dispose()


def test_queue_waits_for_sales_start_and_twelve_simultaneous_joins_never_exceed_the_cap(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    organizer = organizer_client(app, privileged_accounts)
    event_id = published_general_event(organizer)
    assert configure(organizer, event_id, datetime.now(timezone.utc) + timedelta(hours=1), queue=True, active=3).status_code == 200
    people = clients(app, 12)
    barrier = Barrier(12)

    def attempt(person: TestClient) -> str:
        barrier.wait()
        return join(person, event_id)["status"]

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert set(pool.map(attempt, people)) == {"waiting"}  # antes del inicio nadie es admitido
    with create_engine(TEST_ADMIN_URL).begin() as connection:
        connection.execute(text("UPDATE events SET sales_start_at = now() - interval '1 second' WHERE id=:id"), {"id": event_id})
    statuses = [sales(person, event_id)["queue"] for person in people]
    assert sum(item["status"] == "admitted" for item in statuses) == 3
    waiting = sorted(item["position"] for item in statuses if item["status"] == "waiting")
    assert waiting == list(range(1, 10))
    app.state.engine.dispose()


def test_only_the_owner_can_configure_sales_and_start_is_frozen_after_sales(privileged_accounts: dict[str, str]) -> None:
    app = create_app(TEST_APP_URL)
    owner = organizer_client(app, privileged_accounts)
    intruder = organizer_client(app, privileged_accounts, "organizer_other")
    event_id = published_general_event(owner)
    assert configure(intruder, event_id, None, queue=True).status_code == 404
    with TestClient(app) as client:
        register_client(client)
        assert client.put(f"/api/organizer/events/{event_id}/sales", headers=csrf_headers(client), json={"queue_enabled": True}).status_code == 403
        assert post_reservation(client, event_id, "sale-before-config-key").status_code == 201
    assert configure(owner, event_id, datetime.now(timezone.utc) + timedelta(days=1), queue=False).status_code == 409
    assert configure(owner, event_id, None, queue=True, active=5, minutes=15).status_code == 200
    assert owner.put(f"/api/organizer/events/{event_id}/sales", headers=csrf_headers(owner), json={"queue_max_active": 0}).status_code == 422
    app.state.engine.dispose()
