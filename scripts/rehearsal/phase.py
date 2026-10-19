#!/usr/bin/env python3
"""Pasos de ensayo de actualización contra una API LOCAL (127.0.0.1) y su base desechable.

  phase.py seed   <base> <estado.json>   crea usuario y reservas (general, zonas y asientos) y guarda lo creado
  phase.py verify <base> <estado.json>   comprueba que lo guardado sigue visible y que aún se puede reservar y validar

Rechaza cualquier host que no sea 127.0.0.1/localhost. No elimina datos.
"""
import json
import sys
import uuid
from urllib.parse import urlparse

import httpx

ORIGIN = {"Origin": "http://localhost:5173"}
PASSWORD = "Ensayo-local-1234"


def client(base: str) -> httpx.Client:
    if urlparse(base).hostname not in ("127.0.0.1", "localhost"):
        sys.exit("Solo se permite un host local.")
    return httpx.Client(base_url=base, headers=ORIGIN, timeout=20)


def csrf(c: httpx.Client) -> dict:
    return {"X-CSRF-Token": c.cookies.get("nexoeventos_csrf", "")}


def pick_targets(c: httpx.Client) -> list[dict]:
    events = c.get("/api/events").json()
    targets = []
    general = next(e for e in events if e["ticket_mode"] == "general" and e["available_capacity"] >= 5)
    targets.append({"event_id": general["id"], "body": {"quantity": 2}})
    for e in events:
        if e["ticket_mode"] not in ("zones", "seats"):
            continue
        detail = c.get(f"/api/events/{e['id']}").json()
        if detail["seats"]:
            free = [s for s in detail["seats"] if s.get("status", "available") == "available"][:2]
            targets.append({"event_id": e["id"], "body": {"quantity": len(free), "seat_ids": [s["id"] for s in free]}})
            break
    for e in events:
        if e["ticket_mode"] == "zones":
            detail = c.get(f"/api/events/{e['id']}").json()
            if detail["zones"] and not detail["seats"]:
                targets.append({"event_id": e["id"], "body": {"quantity": 1, "zone_id": detail["zones"][0]["id"]}})
                break
    return targets


def snapshot(c: httpx.Client) -> dict:
    res = c.get("/api/me/reservations")
    tix = c.get("/api/me/tickets")
    assert res.status_code == 200 and tix.status_code == 200, (res.status_code, tix.status_code)
    return {"reservations": sorted(r["reservation_id"] if "reservation_id" in r else r["id"] for r in res.json()),
            "tickets": sorted(t["id"] for t in tix.json())}


def main() -> None:
    mode, base, path = sys.argv[1:4]
    c = client(base)
    if mode == "seed":
        email = f"ensayo-{uuid.uuid4().hex[:8]}@example.com"
        r = c.post("/api/auth/register", json={"email": email, "display_name": "Ensayo local", "password": PASSWORD})
        assert r.status_code == 201, r.text
        created = []
        for t in pick_targets(c):
            r = c.post(f"/api/events/{t['event_id']}/reservations", json=t["body"], headers={**csrf(c), "Idempotency-Key": uuid.uuid4().hex})
            assert r.status_code == 201, (t, r.status_code, r.text)
            created.append({**t, "key_replay": r.json()["reservation_id"]})
        state = {"email": email, "created": created, "snapshot": snapshot(c)}
        json.dump(state, open(path, "w"), indent=1)
        print(f"seed OK: {len(created)} reservas, {len(state['snapshot']['tickets'])} entradas")
    else:
        state = json.load(open(path))
        r = c.post("/api/auth/login", json={"email": state["email"], "password": PASSWORD})
        assert r.status_code == 200, r.text
        now = snapshot(c)
        # las guardadas deben seguir ahí; pueden existir más (verificaciones previas crean una reserva nueva)
        assert set(state["snapshot"]["reservations"]) <= set(now["reservations"]), "falta una reserva"
        assert set(state["snapshot"]["tickets"]) <= set(now["tickets"]), "falta una entrada"
        # el QR se descifra y sigue siendo válido
        t = c.get(f"/api/me/tickets/{state['snapshot']['tickets'][0]}")
        assert t.status_code == 200, t.text
        # una reserva nueva funciona con el esquema/código actual
        tgt = pick_targets(c)[0]
        r = c.post(f"/api/events/{tgt['event_id']}/reservations", json=tgt["body"], headers={**csrf(c), "Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code == 201, r.text
        # el catálogo responde
        assert c.get("/api/events").status_code == 200
        print(f"verify OK: {len(now['reservations'])} reservas y {len(now['tickets'])} entradas intactas; reserva nueva 201")


if __name__ == "__main__":
    main()
