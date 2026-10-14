"""Ventana de ventas y cola virtual. El reloj es el de PostgreSQL y toda decisión vive aquí."""
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Event, QueueEntry, User


class SalesNotOpenError(Exception):
    pass


class QueueRequiredError(Exception):
    pass


class QueueUnavailableError(Exception):
    pass


def server_now(session: Session) -> datetime:
    return session.scalar(select(func.now()))


def sales_open(event: Event, now: datetime) -> bool:
    return event.sales_start_at is None or event.sales_start_at <= now


def _live_entry(session: Session, event_id: int, user_id) -> QueueEntry | None:
    return session.scalar(select(QueueEntry).where(QueueEntry.event_id == event_id, QueueEntry.user_id == user_id, QueueEntry.status.in_(("waiting", "admitted"))))


def refresh(session: Session, event: Event, now: datetime) -> None:
    """Expira turnos vencidos y admite por orden de llegada. El llamador ya bloqueó la fila del evento."""
    session.execute(update(QueueEntry).where(QueueEntry.event_id == event.id, QueueEntry.status == "admitted", QueueEntry.expires_at <= now).values(status="expired"))
    if not event.queue_enabled or not sales_open(event, now):
        return
    active = session.scalar(select(func.count()).select_from(QueueEntry).where(QueueEntry.event_id == event.id, QueueEntry.status == "admitted")) or 0
    free = event.queue_max_active - active
    if free <= 0:
        return
    waiting = session.scalars(select(QueueEntry).where(QueueEntry.event_id == event.id, QueueEntry.status == "waiting").order_by(QueueEntry.joined_at, QueueEntry.id).limit(free)).all()
    for entry in waiting:
        entry.status, entry.admitted_at, entry.expires_at = "admitted", now, now + timedelta(minutes=event.queue_pass_minutes)
    session.flush()


def locked_event(session: Session, event_id: int) -> Event | None:
    event = session.scalar(select(Event).where(Event.id == event_id).with_for_update())
    return event if event is not None and event.status == "published" else None


def join(session: Session, event: Event, user: User) -> QueueEntry:
    if not event.queue_enabled:
        raise QueueUnavailableError
    now = server_now(session)
    refresh(session, event, now)
    entry = _live_entry(session, event.id, user.id)
    if entry is None:
        entry = QueueEntry(event_id=event.id, user_id=user.id, status="waiting", joined_at=now)
        session.add(entry)
        session.flush()
        refresh(session, event, now)
    return entry


def leave(session: Session, event: Event, user: User) -> None:
    now = server_now(session)
    entry = _live_entry(session, event.id, user.id)
    if entry is not None:
        entry.status = "left"
        session.flush()
    refresh(session, event, now)


def position(session: Session, entry: QueueEntry) -> int:
    ahead = session.scalar(select(func.count()).select_from(QueueEntry).where(
        QueueEntry.event_id == entry.event_id, QueueEntry.status == "waiting",
        or_(QueueEntry.joined_at < entry.joined_at, and_(QueueEntry.joined_at == entry.joined_at, QueueEntry.id < entry.id)),
    )) or 0
    return ahead + 1


def status_for(session: Session, event: Event, user: User | None) -> dict:
    now = server_now(session)
    queue = None
    if user is not None and event.queue_enabled:
        entry = _live_entry(session, event.id, user.id)
        if entry is not None:
            waiting_total = session.scalar(select(func.count()).select_from(QueueEntry).where(QueueEntry.event_id == event.id, QueueEntry.status == "waiting")) or 0
            queue = {
                "status": entry.status,
                "position": position(session, entry) if entry.status == "waiting" else None,
                "waiting_total": waiting_total,
                "expires_at": entry.expires_at,
                "seconds_left": max(0, int((entry.expires_at - now).total_seconds())) if entry.expires_at else None,
            }
    return {"server_time": now, "sales_start_at": event.sales_start_at, "sales_open": sales_open(event, now), "queue_enabled": event.queue_enabled, "queue_max_active": event.queue_max_active, "queue_pass_minutes": event.queue_pass_minutes, "queue": queue}


def require_pass(session: Session, event: Event, user: User) -> QueueEntry | None:
    """Autoriza una reserva: ventas abiertas y, con cola activa, un turno vigente. Devuelve el turno a consumir."""
    now = server_now(session)
    if not sales_open(event, now):
        raise SalesNotOpenError
    if not event.queue_enabled:
        return None
    refresh(session, event, now)
    entry = _live_entry(session, event.id, user.id)
    if entry is None or entry.status != "admitted" or entry.expires_at is None or entry.expires_at <= now:
        raise QueueRequiredError
    return entry
