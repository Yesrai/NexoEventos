"""Gestión de eventos, funciones, recintos e inventario por parte del organizador.

Una función es una fila de `events` con inventario propio; clonar una función copia
la configuración, nunca reservas, asientos ocupados ni entradas.
"""
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_csrf_role, require_role
from app.catalog import event_detail, event_summary, zone_pricing
from app.database import get_session
from app.inventory import MODE_BY_KIND, InventoryError, apply_inventory, has_sales, publish_problems
from app.models import Event, EventSeat, EventZone, OperatorEventAssignment, Ticket, User, Venue, VenueLayout
from app.schemas import (
    EventCreate,
    EventDetail,
    EventState,
    EventSummary,
    EventUpdate,
    FunctionCreate,
    InventoryInput,
    LayoutOption,
    OperatorAssign,
    OperatorView,
    OrganizerEventStats,
    VenueOption,
    ZoneStats,
)

router = APIRouter(prefix="/api/organizer", tags=["organizer"])
LIMA = ZoneInfo("America/Lima")


def _today() -> date:
    return datetime.now(LIMA).date()


def _owned_event(session: Session, event_id: int, organizer_id, lock: bool = False) -> Event:
    query = select(Event).where(Event.id == event_id, Event.organizer_user_id == organizer_id)
    event = session.scalar(query.with_for_update() if lock else query)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return event


def _state(session: Session, event: Event) -> EventState:
    sold = has_sales(session, event)
    problems = publish_problems(session, event, _today()) if event.status == "draft" else []
    return EventState(
        has_sales=sold,
        can_edit_inventory=not sold,
        can_publish=event.status == "draft" and not problems,
        can_unpublish=event.status == "published" and not sold,
        can_delete=event.status == "draft" and not sold,
        publish_problems=problems,
    )


def _next_event_id(session: Session) -> int:
    session.execute(text("SELECT pg_advisory_xact_lock(7001)"))
    return (session.scalar(select(func.coalesce(func.max(Event.id), 0))) or 0) + 1


def _summaries(session: Session, events: list[Event]) -> list[EventSummary]:
    pricing = zone_pricing(session, [event.id for event in events])
    layouts = {layout.id: layout for layout in session.scalars(select(VenueLayout).where(VenueLayout.id.in_([event.layout_id for event in events if event.layout_id]))).all()}
    return [event_summary(event, pricing.get(event.id), layouts.get(event.layout_id)) for event in events]


@router.get("/events", response_model=list[EventSummary])
def organizer_events(context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> list[EventSummary]:
    events = session.scalars(select(Event).where(Event.organizer_user_id == context.user.id).order_by(Event.event_date, Event.id)).all()
    return _summaries(session, list(events))


@router.get("/venues", response_model=list[VenueOption])
def organizer_venues(context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> list[VenueOption]:
    """Catálogo compartido de recintos y planos (solo lectura): no contiene datos de otros organizadores."""
    layouts = session.scalars(select(VenueLayout).order_by(VenueLayout.venue_id, VenueLayout.id)).all()
    by_venue: dict[int, list[LayoutOption]] = {}
    for layout in layouts:
        by_venue.setdefault(layout.venue_id, []).append(LayoutOption(layout_id=layout.id, name=layout.name, layout_kind=layout.layout_kind, ticket_mode=MODE_BY_KIND[layout.layout_kind]))
    venues = session.scalars(select(Venue).where(Venue.id.in_(by_venue.keys())).order_by(Venue.name)).all() if by_venue else []
    return [VenueOption(venue_id=venue.id, name=venue.name, city=venue.city, layouts=by_venue[venue.id]) for venue in venues]


@router.get("/events/{event_id}", response_model=EventDetail)
def organizer_event(event_id: int, context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    """Detalle completo, incluidos borradores: es la fuente de la vista previa."""
    return event_detail(_owned_event(session, event_id, context.user.id), session)


@router.get("/events/{event_id}/state", response_model=EventState)
def organizer_event_state(event_id: int, context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> EventState:
    return _state(session, _owned_event(session, event_id, context.user.id))


@router.post("/events", response_model=EventDetail, status_code=201)
def create_event(payload: EventCreate, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    event = Event(
        id=_next_event_id(session), name=payload.name.strip(), event_date=payload.date, event_time=payload.time,
        venue="", city="", category=payload.category.strip(), description=payload.description.strip(),
        price=Decimal("0"), capacity=0, reserved_count=0, image_path=payload.image_path,
        ticket_mode="general", is_demo=True, status="draft", organizer_user_id=context.user.id,
    )
    session.add(event)
    session.flush()
    try:
        apply_inventory(session, event, InventoryInput(**payload.model_dump(include=set(InventoryInput.model_fields))))
    except InventoryError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return event_detail(event, session)


@router.patch("/events/{event_id}", response_model=EventDetail)
def update_event(event_id: int, payload: EventUpdate, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    event = _owned_event(session, event_id, context.user.id, lock=True)
    changes = payload.model_dump(exclude_none=True)
    sold = has_sales(session, event)
    if event.ticket_mode != "general" and ("capacity" in changes or "price" in changes):
        raise HTTPException(status_code=409, detail="El aforo y los precios de este evento se administran por zona; no se pueden editar en conjunto")
    if event.venue_id is not None and "venue" in changes and changes["venue"] != event.venue:
        raise HTTPException(status_code=409, detail="El recinto está vinculado a un plano configurado y no puede renombrarse desde aquí")
    if sold and ({"date", "time"} & changes.keys()):
        raise HTTPException(status_code=409, detail="La fecha y la hora no pueden cambiar porque ya hay reservas o entradas emitidas")
    if "capacity" in changes and changes["capacity"] < event.reserved_count:
        raise HTTPException(status_code=409, detail="La capacidad no puede ser menor que las reservas")
    if "date" in changes:
        changes["event_date"] = changes.pop("date")
    if "time" in changes:
        changes["event_time"] = changes.pop("time")
    for field, value in changes.items():
        setattr(event, field, value)
    session.commit()
    return event_detail(event, session)


@router.put("/events/{event_id}/inventory", response_model=EventDetail)
def replace_inventory(event_id: int, payload: InventoryInput, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    event = _owned_event(session, event_id, context.user.id, lock=True)
    if has_sales(session, event):
        raise HTTPException(status_code=409, detail="El recinto y el inventario no pueden cambiar porque ya hay reservas o entradas emitidas")
    try:
        apply_inventory(session, event, payload)
    except InventoryError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return event_detail(event, session)


@router.post("/events/{event_id}/functions", response_model=EventDetail, status_code=201)
def create_function(event_id: int, payload: FunctionCreate, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    """Nueva función del mismo evento: copia la configuración, con inventario y reservas independientes."""
    source = _owned_event(session, event_id, context.user.id)
    clone = Event(
        id=_next_event_id(session), name=source.name, event_date=payload.date, event_time=payload.time or source.event_time,
        venue=source.venue, city=source.city, category=source.category, description=source.description,
        price=source.price, capacity=source.capacity, reserved_count=0, image_path=source.image_path,
        ticket_mode=source.ticket_mode, is_demo=True, status="draft", organizer_user_id=context.user.id,
        venue_id=source.venue_id, layout_id=source.layout_id,
    )
    session.add(clone)
    session.flush()
    zone_map: dict[int, int] = {}
    for zone in session.scalars(select(EventZone).where(EventZone.event_id == source.id).order_by(EventZone.id)).all():
        copy = EventZone(event_id=clone.id, name=zone.name, price=zone.price, capacity=zone.capacity, reserved_count=0)
        session.add(copy)
        session.flush()
        zone_map[zone.id] = copy.id
    for seat in session.scalars(select(EventSeat).where(EventSeat.event_id == source.id).order_by(EventSeat.id)).all():
        session.add(EventSeat(event_id=clone.id, zone_id=zone_map[seat.zone_id], row_label=seat.row_label, seat_number=seat.seat_number))
    session.commit()
    return event_detail(clone, session)


@router.post("/events/{event_id}/publish", response_model=EventDetail)
def publish_event(event_id: int, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    event = _owned_event(session, event_id, context.user.id, lock=True)
    problems = publish_problems(session, event, _today())
    if problems:
        raise HTTPException(status_code=422, detail="No se puede publicar: " + "; ".join(problems))
    event.status = "published"
    session.commit()
    return event_detail(event, session)


@router.post("/events/{event_id}/unpublish", response_model=EventDetail)
def unpublish_event(event_id: int, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> EventDetail:
    event = _owned_event(session, event_id, context.user.id, lock=True)
    if has_sales(session, event):
        raise HTTPException(status_code=409, detail="No se puede despublicar: ya hay reservas o entradas emitidas")
    event.status = "draft"
    session.commit()
    return event_detail(event, session)


@router.delete("/events/{event_id}", status_code=204)
def delete_draft(event_id: int, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> None:
    event = _owned_event(session, event_id, context.user.id, lock=True)
    if event.status != "draft" or has_sales(session, event):
        raise HTTPException(status_code=409, detail="Solo se pueden eliminar borradores sin reservas ni entradas")
    session.delete(event)
    session.commit()


@router.get("/events/{event_id}/operators", response_model=list[OperatorView])
def event_operators(event_id: int, context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> list[OperatorView]:
    _owned_event(session, event_id, context.user.id)
    rows = session.execute(select(User).join(OperatorEventAssignment, OperatorEventAssignment.operator_user_id == User.id).where(OperatorEventAssignment.event_id == event_id).order_by(User.email)).scalars().all()
    return [OperatorView(user_id=user.id, email=user.email, display_name=user.display_name) for user in rows]


@router.post("/events/{event_id}/operators", response_model=list[OperatorView], status_code=201)
def assign_operator(event_id: int, payload: OperatorAssign, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> list[OperatorView]:
    _owned_event(session, event_id, context.user.id)
    operator = session.scalar(select(User).where(User.email == str(payload.email).strip().lower(), User.role == "operator", User.is_active.is_(True)))
    if operator is None:
        raise HTTPException(status_code=404, detail="No existe un operador activo con ese correo")
    if session.get(OperatorEventAssignment, (operator.id, event_id)) is None:
        session.add(OperatorEventAssignment(operator_user_id=operator.id, event_id=event_id))
        session.commit()
    return event_operators(event_id, context, session)


@router.delete("/events/{event_id}/operators/{operator_id}", response_model=list[OperatorView])
def remove_operator(event_id: int, operator_id: str, context: AuthContext = Depends(require_csrf_role("organizer")), session: Session = Depends(get_session)) -> list[OperatorView]:
    _owned_event(session, event_id, context.user.id)
    try:
        from uuid import UUID
        assignment = session.get(OperatorEventAssignment, (UUID(operator_id), event_id))
    except ValueError:
        assignment = None
    if assignment is not None:
        session.delete(assignment)
        session.commit()
    return event_operators(event_id, context, session)


@router.get("/events/{event_id}/stats", response_model=OrganizerEventStats)
def organizer_event_stats(event_id: int, context: AuthContext = Depends(require_role("organizer")), session: Session = Depends(get_session)) -> OrganizerEventStats:
    event = _owned_event(session, event_id, context.user.id)
    tickets = session.execute(select(Ticket.zone_id, Ticket.unit_price, Ticket.used_at).where(Ticket.event_id == event.id)).all()
    zones = session.scalars(select(EventZone).where(EventZone.event_id == event.id).order_by(EventZone.price, EventZone.id)).all()
    sold_by_zone: dict[int, int] = {}
    revenue_by_zone: dict[int, Decimal] = {}
    revenue = Decimal("0")
    for zone_id, unit_price, _used in tickets:
        amount = unit_price if unit_price is not None else event.price
        revenue += amount
        if zone_id is not None:
            sold_by_zone[zone_id] = sold_by_zone.get(zone_id, 0) + 1
            revenue_by_zone[zone_id] = revenue_by_zone.get(zone_id, Decimal("0")) + amount
    sold = len(tickets)
    checked_in = sum(1 for _zone, _price, used_at in tickets if used_at is not None)
    return OrganizerEventStats(
        event_id=event.id, name=event.name, ticket_mode=event.ticket_mode, capacity=event.capacity, sold=sold,
        available=event.capacity - event.reserved_count,
        occupancy_percent=round(sold / event.capacity * 100, 1) if event.capacity else 0.0,
        revenue=float(revenue), checked_in=checked_in, pending_entry=sold - checked_in,
        zones=[ZoneStats(zone_id=zone.id, name=zone.name, price=float(zone.price), capacity=zone.capacity, sold=sold_by_zone.get(zone.id, 0), available=zone.capacity - zone.reserved_count, revenue=float(revenue_by_zone.get(zone.id, Decimal("0")))) for zone in zones],
    )
