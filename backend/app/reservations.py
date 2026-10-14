import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import queue as sales_queue
from app.models import Event, EventSeat, EventZone, Reservation, Ticket, User
from app.schemas import ReservationCreate
from app.ticket_tokens import create_ticket_secret


class EventNotFoundError(Exception):
    pass


class CapacityExceededError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


class SelectionConflictError(Exception):
    pass


class InvalidSelectionError(Exception):
    pass


@dataclass(frozen=True)
class ReservationResult:
    reservation: Reservation
    available_capacity: int
    ticket_count: int
    replayed: bool
    total: Decimal
    ticket_mode: str


def _request_hash(event_id: int, user_id: UUID, payload: ReservationCreate) -> str:
    canonical = json.dumps(
        {
            "event_id": event_id,
            "user_id": str(user_id),
            "quantity": payload.quantity,
            "zone_id": payload.zone_id,
            "seat_ids": sorted(payload.seat_ids),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _existing_result(session: Session, event_id: int, user_id: UUID, key: str, request_hash: str) -> ReservationResult | None:
    reservation = session.scalar(select(Reservation).where(Reservation.idempotency_key == key))
    if reservation is None:
        return None
    if reservation.user_id != user_id or reservation.event_id != event_id or reservation.request_hash != request_hash:
        raise IdempotencyConflictError
    event = session.get(Event, event_id)
    if event is None:
        raise EventNotFoundError
    tickets = session.scalars(select(Ticket).where(Ticket.reservation_id == reservation.id)).all()
    total = sum((ticket.unit_price if ticket.unit_price is not None else event.price for ticket in tickets), Decimal("0"))
    return ReservationResult(reservation, event.capacity - event.reserved_count, len(tickets), True, total, tickets[0].ticket_type if tickets else event.ticket_mode)


def _validate_mode(event: Event, payload: ReservationCreate) -> None:
    if event.ticket_mode == "general" and (payload.zone_id is not None or payload.seat_ids):
        raise InvalidSelectionError("Este evento usa entradas generales; no acepta zona ni asiento")
    if event.ticket_mode == "zones" and (payload.zone_id is None or payload.seat_ids):
        raise InvalidSelectionError("Selecciona una zona válida y una cantidad")
    if event.ticket_mode == "seats" and (payload.zone_id is not None or len(payload.seat_ids) != payload.quantity):
        raise InvalidSelectionError("Selecciona exactamente un asiento por entrada")
    if len(set(payload.seat_ids)) != len(payload.seat_ids):
        raise InvalidSelectionError("No se puede seleccionar el mismo asiento más de una vez")


def create_reservation(session: Session, event_id: int, user: User, payload: ReservationCreate, idempotency_key: str) -> ReservationResult:
    request_hash = _request_hash(event_id, user.id, payload)
    try:
        existing = _existing_result(session, event_id, user.id, idempotency_key, request_hash)
        if existing is not None:
            session.commit()
            return existing
        event = session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        if event is None or event.status != "published":
            session.rollback()
            raise EventNotFoundError
        pass_entry = sales_queue.require_pass(session, event, user)
        _validate_mode(event, payload)
        if payload.quantity > event.capacity - event.reserved_count:
            session.rollback()
            raise CapacityExceededError

        selected_zone: EventZone | None = None
        selected_seats: list[EventSeat] = []
        zone_counts: Counter[int] = Counter()
        unit_prices: list[Decimal]
        if event.ticket_mode == "general":
            unit_prices = [event.price] * payload.quantity
        elif event.ticket_mode == "zones":
            selected_zone = session.scalar(
                select(EventZone).where(EventZone.id == payload.zone_id, EventZone.event_id == event.id).with_for_update()
            )
            if selected_zone is None:
                raise InvalidSelectionError("La zona seleccionada no pertenece a este evento")
            if payload.quantity > selected_zone.capacity - selected_zone.reserved_count:
                raise CapacityExceededError
            selected_zone.reserved_count += payload.quantity
            unit_prices = [selected_zone.price] * payload.quantity
        else:
            selected_seats = list(session.scalars(
                select(EventSeat).where(EventSeat.id.in_(payload.seat_ids)).order_by(EventSeat.id).with_for_update()
            ).all())
            if len(selected_seats) != payload.quantity or any(seat.event_id != event.id for seat in selected_seats):
                raise InvalidSelectionError("Uno o más asientos no pertenecen a este evento")
            if any(seat.reservation_id is not None for seat in selected_seats):
                raise SelectionConflictError
            zone_counts.update(seat.zone_id for seat in selected_seats)
            zones = list(session.scalars(
                select(EventZone).where(EventZone.id.in_(zone_counts.keys())).order_by(EventZone.id).with_for_update()
            ).all())
            zone_by_id = {zone.id: zone for zone in zones}
            if len(zone_by_id) != len(zone_counts):
                raise InvalidSelectionError("La zona de uno o más asientos ya no está disponible")
            for zone_id, count in zone_counts.items():
                zone = zone_by_id[zone_id]
                if count > zone.capacity - zone.reserved_count:
                    raise SelectionConflictError
                zone.reserved_count += count
            unit_prices = [zone_by_id[seat.zone_id].price for seat in selected_seats]

        event.reserved_count += payload.quantity
        reservation = Reservation(
            event_id=event_id,
            user_id=user.id,
            quantity=payload.quantity,
            buyer_alias=user.display_name,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        session.add(reservation)
        session.flush()
        if selected_seats:
            for seat in selected_seats:
                seat.reservation_id = reservation.id
        for index in range(payload.quantity):
            _, secret_hash, ciphertext = create_ticket_secret()
            seat = selected_seats[index] if selected_seats else None
            session.add(Ticket(
                reservation_id=reservation.id,
                event_id=event_id,
                owner_user_id=user.id,
                token_hash=secret_hash,
                token_ciphertext=ciphertext,
                ticket_type=event.ticket_mode,
                zone_id=seat.zone_id if seat else selected_zone.id if selected_zone else None,
                seat_id=seat.id if seat else None,
                unit_price=unit_prices[index],
            ))
        session.flush()
        if pass_entry is not None:
            pass_entry.status = "completed"
        total = sum(unit_prices, Decimal("0"))
        result = ReservationResult(reservation, event.capacity - event.reserved_count, payload.quantity, False, total, event.ticket_mode)
        session.commit()
        return result
    except IntegrityError:
        session.rollback()
        existing = _existing_result(session, event_id, user.id, idempotency_key, request_hash)
        if existing is None:
            raise
        session.commit()
        return existing
