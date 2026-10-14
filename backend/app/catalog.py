from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventSeat, EventZone, VenueLayout
from app.schemas import EventDetail, EventSummary, SeatView, ZoneView


def zone_pricing(session: Session, event_ids: list[int]) -> dict[int, tuple[float, bool]]:
    if not event_ids:
        return {}
    prices_by_event: dict[int, set[float]] = {}
    for event_id, price in session.execute(
        select(EventZone.event_id, EventZone.price).where(EventZone.event_id.in_(event_ids))
    ):
        prices_by_event.setdefault(event_id, set()).add(float(price))
    return {
        event_id: (min(prices), len(prices) > 1)
        for event_id, prices in prices_by_event.items()
        if prices
    }


def event_summary(
    event: Event,
    pricing: tuple[float, bool] | None = None,
    layout: VenueLayout | None = None,
) -> EventSummary:
    display_price, has_multiple_prices = pricing or (float(event.price), False)
    return EventSummary(
        id=event.id,
        name=event.name,
        date=event.event_date,
        time=event.event_time,
        venue=event.venue,
        city=event.city,
        category=event.category,
        price=display_price,
        has_multiple_prices=has_multiple_prices,
        capacity=event.capacity,
        available_capacity=event.capacity - event.reserved_count,
        image_path=event.image_path,
        ticket_mode=event.ticket_mode,
        venue_id=event.venue_id,
        layout_id=event.layout_id,
        layout_name=layout.name if layout else None,
        layout_kind=layout.layout_kind if layout else None,
        is_demo=event.is_demo,
        status=event.status,
    )


def event_detail(event: Event, session: Session) -> EventDetail:
    layout = session.get(VenueLayout, event.layout_id) if event.layout_id else None
    zones = session.scalars(select(EventZone).where(EventZone.event_id == event.id).order_by(EventZone.price, EventZone.id)).all()
    zone_names = {zone.id: zone.name for zone in zones}
    seats = session.scalars(
        select(EventSeat).where(EventSeat.event_id == event.id).order_by(EventSeat.zone_id, EventSeat.row_label, EventSeat.seat_number)
    ).all() if event.ticket_mode == "seats" else []
    zone_prices = {zone.id: float(zone.price) for zone in zones}
    distinct_prices = {float(zone.price) for zone in zones}
    pricing = (min(distinct_prices), len(distinct_prices) > 1) if distinct_prices else None
    return EventDetail(
        **event_summary(event, pricing, layout).model_dump(),
        description=event.description,
        zones=[ZoneView(id=zone.id, name=zone.name, price=float(zone.price), capacity=zone.capacity, available_capacity=zone.capacity - zone.reserved_count) for zone in zones],
        seats=[SeatView(id=seat.id, zone_id=seat.zone_id, zone_name=zone_names[seat.zone_id], row=seat.row_label, number=seat.seat_number, price=zone_prices[seat.zone_id], available=seat.reservation_id is None) for seat in seats],
    )
