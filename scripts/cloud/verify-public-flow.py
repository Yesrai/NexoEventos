#!/usr/bin/env python3
"""Verifica el recorrido HTTPS sin persistir ni mostrar cookies o tokens QR."""
from __future__ import annotations

import http.cookiejar
import json
import os
import secrets
import urllib.error
import urllib.request


BASE_URL = os.getenv("NEXO_PUBLIC_URL", "https://nexoeventos-demo.duckdns.org").rstrip("/")
ORIGIN = BASE_URL
EVENT_ID = int(os.getenv("NEXO_FLOW_EVENT_ID", "1001"))


class ApiSession:
    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def csrf(self) -> str:
        return next((cookie.value for cookie in self.cookies if cookie.name == "nexoeventos_csrf"), "")

    def request(self, method: str, path: str, payload: dict | None = None, *, csrf: bool = False) -> tuple[int, object]:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "Origin": ORIGIN}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if csrf:
            headers["X-CSRF-Token"] = self.csrf()
        request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            body = error.read()
            return error.code, json.loads(body) if body else None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    operator_email = os.environ["NEXO_DEMO_OPERATOR_EMAIL"]
    operator_password = os.environ["NEXO_DEV_OPERATOR_PASSWORD"]
    client_password = "Flow-" + secrets.token_urlsafe(24)
    client_email = f"cloud-flow-{secrets.token_hex(8)}@example.com"

    public = ApiSession()
    status, catalog = public.request("GET", "/api/events")
    require(status == 200 and isinstance(catalog, list), "El catálogo público no respondió")
    require(len(catalog) == 27, "El catálogo no contiene los 27 eventos esperados")
    require(all(event.get("ticket_mode") in {"general", "zones"} for event in catalog), "El catálogo habilitó asientos")

    client = ApiSession()
    status, registered = client.request(
        "POST",
        "/api/auth/register",
        {"email": client_email, "display_name": "Cliente evidencia cloud", "password": client_password},
    )
    require(status == 201 and registered.get("role") == "client", "Falló el registro de cliente")
    require(bool(client.csrf()), "No se recibió la cookie CSRF")

    idempotency_key = "cloud-flow-" + secrets.token_urlsafe(18)
    data = json.dumps({"quantity": 1}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/api/events/{EVENT_ID}/reservations",
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "X-CSRF-Token": client.csrf(),
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    with client.opener.open(request, timeout=30) as response:
        created = json.loads(response.read())
        require(response.status == 201 and created.get("ticket_count") == 1, "Falló la reserva")

    status, tickets = client.request("GET", "/api/me/tickets")
    require(status == 200 and len(tickets) == 1, "No se obtuvo la entrada del cliente")
    qr_token = tickets[0].get("qr_token", "")
    require(qr_token.startswith("nexo_") and len(qr_token) >= 20, "La entrada no contiene un token válido")

    operator = ApiSession()
    status, logged_in = operator.request(
        "POST", "/api/auth/login", {"email": operator_email, "password": operator_password}
    )
    require(status == 200 and logged_in.get("role") == "operator", "Falló el acceso del operador")
    status, assigned = operator.request("GET", "/api/operator/events")
    require(status == 200 and any(event.get("id") == EVENT_ID for event in assigned), "El evento no está asignado al operador")

    validation = {"event_id": EVENT_ID, "qr_token": qr_token}
    first_status, first = operator.request("POST", "/api/operator/validate", validation, csrf=True)
    require(first_status == 200 and first.get("result") == "accepted", "El primer ingreso no fue aceptado")
    second_status, second = operator.request("POST", "/api/operator/validate", validation, csrf=True)
    require(second_status == 409 and second.get("detail") == "Entrada ya utilizada", "El segundo ingreso no fue rechazado")

    status, refreshed = client.request("GET", "/api/me/tickets")
    require(status == 200 and refreshed[0].get("used_at"), "La entrada no refleja el estado usado")
    logout_status, _ = client.request("POST", "/api/auth/logout", csrf=True)
    require(logout_status == 204, "Falló el cierre de sesión")
    expired_status, _ = client.request("GET", "/api/auth/session")
    require(expired_status == 401, "La sesión siguió activa tras cerrar sesión")

    print("catalog=27; modes=general,zones")
    print("register=201; role=client; reserve=201; tickets=1")
    print("operator_login=200; first_validation=200; second_validation=409")
    print("ticket_state=used; logout=204; session_after_logout=401")
    print("qr_token=not_printed; cookies=in_memory_only")


if __name__ == "__main__":
    main()
