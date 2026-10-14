"""Reglas de inventario por tipo de plano, compartidas por crear, editar y clonar funciones."""
from decimal import Decimal
from string import ascii_uppercase

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.models import Event, EventSeat, EventZone, Reservation, Ticket, Venue, VenueLayout
from app.schemas import InventoryInput

MODE_BY_KIND = {
    "theatre": "seats", "stadium": "seats",
    "zones": "zones", "concert_zones": "zones",
    "museum": "general", "general": "general",
}
STADIUM_SIDES = ("Norte", "Sur", "Oriente", "Occidente")
MAX_ROWS = {"theatre": 12, "stadium": len(ascii_uppercase)}
MAX_SEATS = 1000


class InventoryError(Exception):
    """Configuración inválida para el tipo de plano; el mensaje es apto para mostrarse."""


def has_sales(session: Session, event: Event) -> bool:
    if event.reserved_count > 0:
        return True
    return bool(session.scalar(select(exists().where(Reservation.event_id == event.id)))) or bool(
        session.scalar(select(exists().where(Ticket.event_id == event.id)))
    )


def validate_inventory(kind: str, payload: InventoryInput) -> None:
    mode = MODE_BY_KIND[kind]
    if mode == "general":
        if payload.price is None or payload.capacity is None:
            raise InventoryError("Indica el precio y el cupo de este tipo de plano")
        if payload.zones or payload.sections:
            raise InventoryError("Este plano usa cupo único; no admite zonas ni asientos")
    elif mode == "zones":
        if not payload.zones:
            raise InventoryError("Define al menos una zona con precio y aforo")
        if payload.sections or payload.price is not None or payload.capacity is not None:
            raise InventoryError("Este plano se configura por zonas; no admite asientos ni cupo único")
        names = [zone.name.strip().lower() for zone in payload.zones]
        if len(set(names)) != len(names):
            raise InventoryError("Los nombres de zona no pueden repetirse")
    else:
        if not payload.sections:
            raise InventoryError("Define al menos una sección con filas y asientos")
        if payload.zones or payload.price is not None or payload.capacity is not None:
            raise InventoryError("Este plano se configura por secciones con asientos numerados")
        names = [section.name.strip().lower() for section in payload.sections]
        if len(set(names)) != len(names):
            raise InventoryError("Los nombres de sección no pueden repetirse")
        if sum(section.rows for section in payload.sections) > MAX_ROWS[kind]:
            raise InventoryError(f"Este plano admite como máximo {MAX_ROWS[kind]} filas en total")
        if sum(section.rows * section.seats_per_row for section in payload.sections) > MAX_SEATS:
            raise InventoryError(f"Este plano admite como máximo {MAX_SEATS} asientos")
        if kind == "stadium":
            for section in payload.sections:
                side = section.name.strip().removeprefix("Tribuna ").strip()
                if not section.name.strip().startswith("Tribuna ") or side not in STADIUM_SIDES:
                    raise InventoryError("Las tribunas del estadio deben llamarse «Tribuna Norte», «Tribuna Sur», «Tribuna Oriente» o «Tribuna Occidente»")


def resolve_layout(session: Session, layout_id: int) -> tuple[VenueLayout, Venue]:
    layout = session.get(VenueLayout, layout_id)
    venue = session.get(Venue, layout.venue_id) if layout else None
    if layout is None or venue is None:
        raise InventoryError("El plano seleccionado no existe")
    return layout, venue


def apply_inventory(session: Session, event: Event, payload: InventoryInput) -> None:
    """Reemplaza plano y localidades de un evento sin ventas. El llamador ya bloqueó la fila del evento."""
    layout, venue = resolve_layout(session, payload.layout_id)
    validate_inventory(layout.layout_kind, payload)
    session.execute(delete(EventSeat).where(EventSeat.event_id == event.id))
    session.execute(delete(EventZone).where(EventZone.event_id == event.id))
    event.venue_id, event.layout_id = venue.id, layout.id
    event.venue, event.city = venue.name, venue.city
    event.ticket_mode = MODE_BY_KIND[layout.layout_kind]
    event.reserved_count = 0
    if event.ticket_mode == "general":
        event.price, event.capacity = Decimal(str(payload.price)), payload.capacity
    elif event.ticket_mode == "zones":
        for zone in payload.zones:
            session.add(EventZone(event_id=event.id, name=zone.name.strip(), price=Decimal(str(zone.price)), capacity=zone.capacity, reserved_count=0))
        event.capacity = sum(zone.capacity for zone in payload.zones)
        event.price = Decimal(str(min(zone.price for zone in payload.zones)))
    else:
        row_index = 0
        for section in payload.sections:
            zone = EventZone(event_id=event.id, name=section.name.strip(), price=Decimal(str(section.price)), capacity=section.rows * section.seats_per_row, reserved_count=0)
            session.add(zone)
            session.flush()
            for _ in range(section.rows):
                for number in range(1, section.seats_per_row + 1):
                    session.add(EventSeat(event_id=event.id, zone_id=zone.id, row_label=ascii_uppercase[row_index], seat_number=number))
                row_index += 1
        event.capacity = sum(section.rows * section.seats_per_row for section in payload.sections)
        event.price = Decimal(str(min(section.price for section in payload.sections)))
    session.flush()


def publish_problems(session: Session, event: Event, today) -> list[str]:
    problems: list[str] = []
    layout = session.get(VenueLayout, event.layout_id) if event.layout_id else None
    if layout is None:
        problems.append("Selecciona un recinto y un plano")
    if event.capacity <= 0:
        problems.append("El aforo debe ser mayor que cero")
    if event.event_date < today:
        problems.append("La fecha de la función ya pasó")
    if layout is not None and layout.layout_kind == "museum" and event.event_time is None:
        problems.append("Los museos reservan por horario: indica la hora de la función")
    if event.ticket_mode != "general":
        zones = session.scalars(select(EventZone).where(EventZone.event_id == event.id)).all()
        if not zones:
            problems.append("Configura al menos una zona o sección")
        elif sum(zone.capacity for zone in zones) != event.capacity:
            problems.append("El aforo no coincide con la suma de las zonas")
        if event.ticket_mode == "seats":
            seat_count = len(session.scalars(select(EventSeat.id).where(EventSeat.event_id == event.id)).all())
            if seat_count != event.capacity:
                problems.append("La cantidad de asientos no coincide con el aforo")
    return problems
