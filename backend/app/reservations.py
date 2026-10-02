import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, Reservation, Ticket, User
from app.schemas import ReservationCreate
from app.ticket_tokens import create_ticket_secret


class EventNotFoundError(Exception):
    pass


class CapacityExceededError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


@dataclass(frozen=True)
class ReservationResult:
    reservation: Reservation
    available_capacity: int
    ticket_count: int
    replayed: bool


def _request_hash(event_id: int, user_id: UUID, payload: ReservationCreate) -> str:
    canonical = json.dumps(
        {"event_id": event_id, "user_id": str(user_id), "quantity": payload.quantity},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _existing_result(
    session: Session,
    event_id: int,
    user_id: UUID,
    key: str,
    request_hash: str,
) -> ReservationResult | None:
    reservation = session.scalar(select(Reservation).where(Reservation.idempotency_key == key))
    if reservation is None:
        return None
    if reservation.user_id != user_id or reservation.event_id != event_id or reservation.request_hash != request_hash:
        raise IdempotencyConflictError
    event = session.get(Event, event_id)
    if event is None:
        raise EventNotFoundError
    ticket_count = session.scalar(select(func.count(Ticket.id)).where(Ticket.reservation_id == reservation.id)) or 0
    return ReservationResult(reservation, event.capacity - event.reserved_count, ticket_count, True)


def create_reservation(
    session: Session,
    event_id: int,
    user: User,
    payload: ReservationCreate,
    idempotency_key: str,
) -> ReservationResult:
    request_hash = _request_hash(event_id, user.id, payload)
    try:
        existing = _existing_result(session, event_id, user.id, idempotency_key, request_hash)
        if existing is not None:
            session.commit()
            return existing
        event = session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        if event is None:
            session.rollback()
            raise EventNotFoundError
        if payload.quantity > event.capacity - event.reserved_count:
            session.rollback()
            raise CapacityExceededError

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
        for _ in range(payload.quantity):
            _, secret_hash, ciphertext = create_ticket_secret()
            session.add(Ticket(
                reservation_id=reservation.id,
                event_id=event_id,
                owner_user_id=user.id,
                token_hash=secret_hash,
                token_ciphertext=ciphertext,
            ))
        session.flush()
        result = ReservationResult(reservation, event.capacity - event.reserved_count, payload.quantity, False)
        session.commit()
        return result
    except IntegrityError:
        session.rollback()
        existing = _existing_result(session, event_id, user.id, idempotency_key, request_hash)
        if existing is None:
            raise
        session.commit()
        return existing
