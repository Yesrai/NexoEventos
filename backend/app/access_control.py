from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessLog, Event, OperatorEventAssignment, Ticket
from app.ticket_tokens import token_fingerprint, token_hash


class EventNotAssignedError(Exception):
    pass


class TicketNotFoundError(Exception):
    pass


class TicketAlreadyUsedError(Exception):
    pass


class TicketWrongEventError(Exception):
    pass


@dataclass(frozen=True)
class ValidationAccepted:
    ticket_id: UUID
    event_id: int
    used_at: datetime


def _log(session: Session, event_id: int, operator_id: UUID, token: str, result: str, ticket_id: UUID | None = None) -> None:
    session.add(AccessLog(
        event_id=event_id,
        ticket_id=ticket_id,
        operator_user_id=operator_id,
        result=result,
        token_fingerprint=token_fingerprint(token),
    ))


def validate_ticket(session: Session, operator_id: UUID, event_id: int, token: str) -> ValidationAccepted:
    error: Exception | None = None
    accepted: ValidationAccepted | None = None
    event = session.get(Event, event_id)
    if event is None:
        session.rollback()
        error = EventNotAssignedError()
    elif session.get(OperatorEventAssignment, (operator_id, event_id)) is None:
        _log(session, event_id, operator_id, token, "wrong_event")
        error = EventNotAssignedError()
    else:
        ticket = session.scalar(select(Ticket).where(Ticket.token_hash == token_hash(token)).with_for_update())
        if ticket is None:
            _log(session, event_id, operator_id, token, "invalid_token")
            error = TicketNotFoundError()
        elif ticket.event_id != event_id:
            _log(session, event_id, operator_id, token, "wrong_event", ticket.id)
            error = TicketWrongEventError()
        elif ticket.used_at is not None:
            _log(session, event_id, operator_id, token, "already_used", ticket.id)
            error = TicketAlreadyUsedError()
        else:
            used_at = datetime.now(timezone.utc)
            ticket.used_at = used_at
            ticket.used_by_user_id = operator_id
            _log(session, event_id, operator_id, token, "accepted", ticket.id)
            accepted = ValidationAccepted(ticket.id, event_id, used_at)
    if event is not None:
        session.flush()
        session.commit()
    if error is not None:
        raise error
    assert accepted is not None
    return accepted
