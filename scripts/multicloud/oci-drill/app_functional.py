"""Pruebas FUNCIONALES de reservas sobre la COPIA DESECHABLE recuperada (T3): reserva nueva, idempotencia, validaciones, inventario transaccional bajo concurrencia y ciclo completo
reserva → entrada con QR → validación del operador → duplicado rechazado. Funciona con cualquier cliente compatible con httpx (en producción de la prueba: httpx contra la VM; en las pruebas
locales: el TestClient de la aplicación real sobre PostgreSQL). Escribe SOLO en la copia de OCI (reservas, entradas y access_logs); jamás se ejecuta contra AWS ni contra una base viva.
`check(nombre, ok, detalle)` lo aporta quien llama (app-smoke.py). Todas las comprobaciones llevan el prefijo «funcional:»."""
from __future__ import annotations

import threading
import uuid


def functional_checks(cl, op, events, operator_event_ids, check, csrf, new_client, concurrency=4):
    """cl/op: clientes ya autenticados (cliente y operador). events: lista de /api/events. csrf(c) → cabeceras CSRF/Origin. new_client() → cliente NUEVO con la sesión del cliente."""
    summary: dict = {}
    cands = [e for e in events if e.get("ticket_mode") == "general" and e.get("available_capacity", 0) >= concurrency + 4 and e.get("id") in set(operator_event_ids or [])]
    if not cands:
        check("funcional: hay un evento general reservable asignado al operador", False, "ninguno cumple (modo general, cupos suficientes, asignado al operador)"); return summary
    ev = None; key = "t3-" + uuid.uuid4().hex[:16]; tickets0 = {t["id"] for t in cl.get("/api/me/tickets").json()}      # ANTES de crear nada
    def reserve(c, eid, k, qty=1): return c.post(f"/api/events/{eid}/reservations", json={"quantity": qty}, headers={**csrf(c), "Idempotency-Key": k})
    def avail(eid): return cl.get(f"/api/events/{eid}").json().get("available_capacity")
    for e in cands[:5]:
        before = avail(e["id"]); r = reserve(cl, e["id"], key)
        if r.status_code == 201: ev, first = e, r; break
        if r.status_code not in (403, 409): break              # 403: ventas aún no abiertas o fila virtual; se prueba otro evento
    if ev is None: check("funcional: crear una reserva nueva (201)", False, f"último HTTP {r.status_code}"); return summary
    eid, body = ev["id"], first.json()
    summary.update(evento=eid, cupos_antes=before)
    check("funcional: reserva nueva creada (201, 1 entrada, cupos −1)", body.get("quantity") == 1 and body.get("ticket_count") == 1 and body.get("replayed") is False and avail(eid) == before - 1, f"cupos {before} → {avail(eid)}")
    r2 = reserve(cl, eid, key); b2 = r2.json() if r2.status_code == 200 else {}
    check("funcional: idempotencia: misma clave y mismo cuerpo → misma reserva (200, replayed) y los cupos NO bajan otra vez", r2.status_code == 200 and b2.get("replayed") is True and b2.get("reservation_id") == body["reservation_id"] and avail(eid) == before - 1, f"HTTP {r2.status_code}")
    r3 = reserve(cl, eid, key, qty=2); check("funcional: misma clave con OTRO cuerpo → 409 (conflicto de idempotencia)", r3.status_code == 409, f"HTTP {r3.status_code}")
    bad = [reserve(cl, eid, "t3-" + uuid.uuid4().hex[:16], q).status_code for q in (0, 11)]
    check("funcional: cantidades inválidas (0 y 11) → 422 y sin cambios de inventario", bad == [422, 422] and avail(eid) == before - 1, f"HTTP {bad}")
    mine = {m["id"] for m in cl.get("/api/me/reservations").json()}; tk = cl.get("/api/me/tickets").json(); new_t = [t for t in tk if t["id"] not in tickets0]
    check("funcional: la reserva aparece en «mis reservas» y genera 1 entrada con QR descifrable", body["reservation_id"] in mine and len(new_t) == 1 and isinstance(new_t[0].get("qr_token"), str) and len(new_t[0]["qr_token"]) >= 20, f"{len(new_t)} entrada(s) nuevas")
    base = avail(eid); results = []; lock = threading.Lock()
    def worker(i):
        c = new_client(); rr = reserve(c, eid, "t3c-" + uuid.uuid4().hex[:16])
        with lock: results.append(rr.status_code)
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]; [t.start() for t in ths]; [t.join() for t in ths]
    check(f"funcional: inventario transaccional: {concurrency} reservas CONCURRENTES → {concurrency} × 201 y los cupos bajan exactamente {concurrency} (sin pérdidas ni sobreventa)", sorted(results) == [201] * concurrency and avail(eid) == base - concurrency, f"HTTP {sorted(results)}; cupos {base} → {avail(eid)}")
    if new_t:
        tok = new_t[0]["qr_token"]; v1 = op.post("/api/operator/validate", json={"event_id": eid, "qr_token": tok}, headers=csrf(op)); v2 = op.post("/api/operator/validate", json={"event_id": eid, "qr_token": tok}, headers=csrf(op))
        check("funcional: el operador valida la entrada NUEVA (aceptada) y el segundo intento se rechaza (409 «ya utilizada»)", v1.status_code == 200 and v1.json().get("result") == "accepted" and v2.status_code == 409, f"HTTP {v1.status_code} y {v2.status_code}")
    summary["cupos_despues"] = avail(eid); return summary
